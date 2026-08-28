#!/usr/bin/env python3
"""数学题库增量质量核验流水线。

禁止逐题串行请求模型。采用：
- PDF页按 (PDF哈希+页码+DPI) 缓存，只渲染一次
- 题干按源页批量审核（一页含全部题目一次审核）
- 答案图每6-8题组成高清联系表批量审核（标注uid防串题）
- 双视觉模型并行独立审核，不一致才第三次裁决
- 断点续跑、原子检查点、超时重试、指数退避、配额限制
- 只重审哈希变化项

用法：
    python scripts/quality_pipeline.py init          # 初始化账本
    python scripts/quality_pipeline.py status        # 查看状态
    python scripts/quality_pipeline.py render        # 预渲染所有源页（缓存）
    python scripts/quality_pipeline.py review-source # 题干审核
    python scripts/quality_pipeline.py review-answer # 答案审核
    python scripts/quality_pipeline.py arbitrate     # 冲突裁决
    python scripts/quality_pipeline.py run           # 全流程
    python scripts/quality_pipeline.py export        # 导出报告
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
import traceback
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ── 路径 ──────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).resolve().parent
BANK_ROOT = SCRIPT_DIR.parent
REPO_ROOT = BANK_ROOT.parent.parent
TEMP_DIR = REPO_ROOT / "temp" / "math-quality"
TEMP_DIR.mkdir(parents=True, exist_ok=True)
PDF_CACHE_DIR = TEMP_DIR / "pdf_pages"
PDF_CACHE_DIR.mkdir(parents=True, exist_ok=True)
CONTACT_SHEET_DIR = TEMP_DIR / "contact_sheets"
CONTACT_SHEET_DIR.mkdir(parents=True, exist_ok=True)
MODEL_OUTPUT_DIR = TEMP_DIR / "model_outputs"
MODEL_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

LEDGER_PATH = BANK_ROOT / "quality-ledger.json"
CONFIG_PATH = SCRIPT_DIR / "quality_pipeline_config.json"

BOOKS = ("660题", "880题", "1000题", "大学深埋")

# ── 状态常量 ──────────────────────────────────────────
STATUS_PENDING = "pending"
STATUS_RULE_PASSED = "rule_passed"
STATUS_SOURCE_VERIFIED = "source_verified"
STATUS_ANSWER_VERIFIED = "answer_verified"
STATUS_CONFLICT = "conflict"
STATUS_HOLD = "hold"

# ── 规则/提示词版本 ───────────────────────────────────
RULE_VERSION = "1.0.0"
SOURCE_PROMPT_VERSION = "1.0.0"
ANSWER_PROMPT_VERSION = "1.0.0"

# ── 工具函数 ──────────────────────────────────────────

def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def atomic_write_json(path: Path, data: Any) -> None:
    """原子写入JSON：先写.tmp再replace。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def load_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── 配置 ──────────────────────────────────────────────

DEFAULT_CONFIG = {
    "schema_version": 1,
    "pdf_dpi": 200,
    "contact_sheet": {
        "questions_per_sheet": 7,
        "dpi": 150,
        "label_font_size": 14,
    },
    "models": {
        "primary": {
            "name": "qwen-vl",
            "provider": "openai_compatible",
            "base_url_env": "QWEN_VL_BASE_URL",
            "api_key_env": "QWEN_VL_API_KEY",
            "model_env": "QWEN_VL_MODEL",
            "model_default": "qwen-vl-max",
            "timeout": 60,
            "max_retries": 3,
            "rpm_limit": 20,
        },
        "secondary": {
            "name": "minimax-m3",
            "provider": "openai_compatible",
            "base_url_env": "MINIMAX_VL_BASE_URL",
            "api_key_env": "MINIMAX_VL_API_KEY",
            "model_env": "MINIMAX_VL_MODEL",
            "model_default": "MiniMax-M3",
            "timeout": 60,
            "max_retries": 3,
            "rpm_limit": 20,
        },
        "arbitrator": {
            "name": "qwen-vl",
            "provider": "openai_compatible",
            "base_url_env": "QWEN_VL_BASE_URL",
            "api_key_env": "QWEN_VL_API_KEY",
            "model_env": "QWEN_VL_MODEL",
            "model_default": "qwen-vl-max",
            "timeout": 90,
            "max_retries": 2,
            "rpm_limit": 10,
        },
    },
    "review": {
        "source_batch_by_page": True,
        "answer_contact_sheet_size": 7,
        "confidence_threshold": 0.8,
    },
}


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        atomic_write_json(CONFIG_PATH, DEFAULT_CONFIG)
        return DEFAULT_CONFIG
    cfg = load_json(CONFIG_PATH, DEFAULT_CONFIG)
    # 补全缺失字段
    for k, v in DEFAULT_CONFIG.items():
        if k not in cfg:
            cfg[k] = v
    return cfg


# ── 题库加载 ──────────────────────────────────────────

def load_all_questions() -> list[dict]:
    """加载四库所有题目，返回带book字段的扁平列表。"""
    all_questions = []
    for book in BOOKS:
        qpath = BANK_ROOT / book / "questions.json"
        if not qpath.exists():
            continue
        data = json.loads(qpath.read_text(encoding="utf-8"))
        source_sha = sha256_file(qpath)
        for ch in data.get("chapters", []):
            for q in ch.get("questions", []):
                q["_book"] = book
                q["_source_sha"] = source_sha
                all_questions.append(q)
    return all_questions


def question_content_hash(q: dict) -> str:
    """题干+选项+结构的哈希。"""
    parts = [
        str(q.get("uid", "")),
        str(q.get("content", "")),
        json.dumps(q.get("options"), ensure_ascii=False, sort_keys=True),
        str(q.get("type", "")),
        json.dumps(q.get("sub_questions"), ensure_ascii=False, sort_keys=True),
        str(q.get("has_image", "")),
        json.dumps(q.get("image_ref"), ensure_ascii=False, sort_keys=True),
    ]
    return sha256_text("|".join(parts))


def question_answer_hash(q: dict) -> str:
    """答案相关字段的哈希。"""
    parts = [
        str(q.get("uid", "")),
        json.dumps(q.get("answer_ref"), ensure_ascii=False, sort_keys=True),
        str(q.get("type", "")),
    ]
    return sha256_text("|".join(parts))


# ── PDF渲染缓存 ───────────────────────────────────────

def get_pdf_path(q: dict) -> Path | None:
    """根据题目推断源PDF路径。"""
    book = q.get("_book", "")
    page = q.get("page")
    if page is None:
        return None
    pdf_map = {
        "660题": "《基础过关660》-高数篇 .pdf",  # 简化，实际需区分高数/线代
        "880题": "【A4紧凑版】李林880数二高数篇做题本.pdf",
        "1000题": "27张宇1000题数二-试题册.pdf",
        "大学深埋": "27大雪深埋强化讲义书（扫描版）.pdf",
    }
    pdf_name = pdf_map.get(book)
    if not pdf_name:
        return None
    pdf_dir = REPO_ROOT / "资料" / "数学2" / "电子资料"
    pdf_path = pdf_dir / pdf_name
    return pdf_path if pdf_path.exists() else None


def render_pdf_page(pdf_path: Path, page_num: int, dpi: int = 200) -> Path:
    """渲染PDF指定页，带缓存。返回缓存图片路径。"""
    pdf_hash = sha256_file(pdf_path)[:16]
    cache_key = f"{pdf_hash}_p{page_num}_dpi{dpi}.png"
    cache_path = PDF_CACHE_DIR / cache_key
    if cache_path.exists():
        return cache_path

    try:
        import pymupdf as fitz
    except ImportError:
        raise RuntimeError("需要 PyMuPDF: pip install pymupdf")

    doc = fitz.open(pdf_path)
    if page_num - 1 >= len(doc):
        doc.close()
        raise ValueError(f"页码 {page_num} 超出PDF范围 {len(doc)}")
    page = doc[page_num - 1]
    mat = fitz.Matrix(dpi / 72, dpi / 72)
    pix = page.get_pixmap(matrix=mat, alpha=False)
    pix.save(str(cache_path))
    doc.close()
    return cache_path


# ── 账本管理 ──────────────────────────────────────────

def init_ledger() -> dict:
    """初始化账本：为所有题目创建pending记录。"""
    questions = load_all_questions()
    entries = {}
    for q in questions:
        uid = q.get("uid", "")
        if not uid:
            continue
        content_h = question_content_hash(q)
        answer_h = question_answer_hash(q)
        pdf_path = get_pdf_path(q)
        pdf_hash = sha256_file(pdf_path)[:16] if pdf_path else None
        page = q.get("page")

        # 题图哈希
        image_hash = None
        image_ref = q.get("image_ref")
        if isinstance(image_ref, dict) and image_ref.get("cropped"):
            img_path = BANK_ROOT / q["_book"] / "math-bank" / image_ref["cropped"]
            if img_path.exists():
                image_hash = sha256_file(img_path)[:16]

        # 答案图哈希
        answer_hash = None
        answer_ref = q.get("answer_ref")
        if answer_ref:
            if isinstance(answer_ref, dict):
                ans_path = BANK_ROOT / q["_book"] / "math-bank" / str(answer_ref.get("cropped", answer_ref))
            else:
                ans_path = BANK_ROOT / q["_book"] / "math-bank" / str(answer_ref)
            if ans_path.exists():
                answer_hash = sha256_file(ans_path)[:16]

        entries[uid] = {
            "uid": uid,
            "book": q["_book"],
            "chapter": q.get("chapter"),
            "page": page,
            "type": q.get("type"),
            "content_hash": content_h,
            "answer_hash": answer_h,
            "source_pdf_hash": pdf_hash,
            "source_page": page,
            "source_page_render_hash": None,  # 渲染后填充
            "image_hash": image_hash,
            "answer_image_hash": answer_hash,
            "rule_version": RULE_VERSION,
            "source_prompt_version": SOURCE_PROMPT_VERSION,
            "answer_prompt_version": ANSWER_PROMPT_VERSION,
            "model_versions": {},
            "source_review_status": STATUS_PENDING,
            "answer_review_status": STATUS_PENDING,
            "overall_status": STATUS_PENDING,
            "conflicts": [],
            "issue_codes": [],
            "last_reviewed": None,
            "model_request_count": 0,
        }

    ledger = {
        "schema_version": 1,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "rule_version": RULE_VERSION,
        "total_questions": len(entries),
        "entries": entries,
    }
    atomic_write_json(LEDGER_PATH, ledger)
    return ledger


def load_ledger() -> dict:
    if not LEDGER_PATH.exists():
        return init_ledger()
    return load_json(LEDGER_PATH)


def save_ledger(ledger: dict) -> None:
    ledger["updated_at"] = now_iso()
    atomic_write_json(LEDGER_PATH, ledger)


def update_entry_status(ledger: dict, uid: str, **kwargs) -> None:
    entry = ledger["entries"].get(uid)
    if not entry:
        return
    entry.update(kwargs)
    entry["last_reviewed"] = now_iso()
    # 计算整体状态
    src = entry.get("source_review_status", STATUS_PENDING)
    ans = entry.get("answer_review_status", STATUS_PENDING)
    if src == STATUS_HOLD or ans == STATUS_HOLD or entry.get("conflicts"):
        entry["overall_status"] = STATUS_HOLD
    elif src == STATUS_CONFLICT or ans == STATUS_CONFLICT:
        entry["overall_status"] = STATUS_CONFLICT
    elif src == STATUS_SOURCE_VERIFIED and ans == STATUS_ANSWER_VERIFIED:
        entry["overall_status"] = "strictly_verified"
    elif src == STATUS_RULE_PASSED and ans == STATUS_RULE_PASSED:
        entry["overall_status"] = STATUS_RULE_PASSED
    else:
        entry["overall_status"] = STATUS_PENDING


# ── 视觉模型客户端 ────────────────────────────────────

class VisionModelClient:
    """视觉模型客户端，支持超时重试、指数退避、配额限制。"""

    def __init__(self, model_config: dict, role: str = "primary"):
        self.config = model_config
        self.role = role
        self.name = model_config.get("name", role)
        self.timeout = model_config.get("timeout", 60)
        self.max_retries = model_config.get("max_retries", 3)
        self.rpm_limit = model_config.get("rpm_limit", 20)
        self._last_request_time = 0
        self._request_count = 0

    def is_configured(self) -> bool:
        api_key = os.environ.get(self.config.get("api_key_env", ""))
        base_url = os.environ.get(self.config.get("base_url_env", ""))
        return bool(api_key and base_url)

    def _wait_for_quota(self) -> None:
        """简单的RPM限制：确保请求间隔 >= 60/rpm_limit秒。"""
        min_interval = 60.0 / self.rpm_limit
        elapsed = time.time() - self._last_request_time
        if elapsed < min_interval:
            time.sleep(min_interval - elapsed)

    def review_image(self, image_path: Path, prompt: str) -> dict | None:
        """调用视觉模型审核图片。返回模型输出dict，失败返回None。"""
        if not self.is_configured():
            return None

        self._wait_for_quota()
        self._last_request_time = time.time()
        self._request_count += 1

        api_key = os.environ[self.config["api_key_env"]]
        base_url = os.environ[self.config["base_url_env"]]
        model = os.environ.get(self.config.get("model_env", ""), self.config.get("model_default", ""))

        import base64
        import urllib.request
        import urllib.error

        # 读取并编码图片
        img_data = image_path.read_bytes()
        img_b64 = base64.b64encode(img_data).decode("ascii")
        mime = "image/png" if image_path.suffix.lower() == ".png" else "image/jpeg"

        payload = {
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{img_b64}"}},
                    ],
                }
            ],
            "max_tokens": 2000,
            "temperature": 0.1,
        }

        for attempt in range(self.max_retries):
            try:
                req = urllib.request.Request(
                    f"{base_url.rstrip('/')}/chat/completions",
                    data=json.dumps(payload).encode("utf-8"),
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {api_key}",
                    },
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    result = json.loads(resp.read().decode("utf-8"))
                content = result["choices"][0]["message"]["content"]
                # 尝试解析JSON输出
                try:
                    parsed = json.loads(content)
                except (json.JSONDecodeError, ValueError):
                    parsed = {"raw_text": content}
                return {
                    "model": self.name,
                    "role": self.role,
                    "output": parsed,
                    "raw": content,
                    "attempt": attempt + 1,
                }
            except Exception as e:
                if attempt < self.max_retries - 1:
                    wait = 2 ** attempt * 1.5
                    time.sleep(wait)
                else:
                    return {"model": self.name, "role": self.role, "error": str(e), "attempt": attempt + 1}
        return None


# ── 联系表生成 ────────────────────────────────────────

def build_answer_contact_sheets(questions: list[dict], sheet_size: int = 7) -> list[Path]:
    """为答案图生成联系表，每张sheet_size题，标注uid。"""
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        raise RuntimeError("需要 Pillow")

    sheets = []
    for i in range(0, len(questions), sheet_size):
        batch = questions[i:i + sheet_size]
        images = []
        labels = []
        for q in batch:
            answer_ref = q.get("answer_ref")
            if not answer_ref:
                continue
            if isinstance(answer_ref, dict):
                rel = answer_ref.get("cropped", str(answer_ref))
            else:
                rel = str(answer_ref)
            ans_path = BANK_ROOT / q["_book"] / "math-bank" / rel
            if ans_path.exists():
                images.append(Image.open(ans_path).convert("RGB"))
                labels.append(q.get("uid", "unknown"))
            else:
                # 缺失答案图也占位
                placeholder = Image.new("RGB", (400, 200), (255, 200, 200))
                draw = ImageDraw.Draw(placeholder)
                draw.text((10, 90), f"MISSING: {q.get('uid')}", fill=(200, 0, 0))
                images.append(placeholder)
                labels.append(q.get("uid", "unknown") + " [MISSING]")

        if not images:
            continue

        # 统一宽度
        target_w = 800
        resized = []
        for img in images:
            ratio = target_w / img.width
            resized.append(img.resize((target_w, int(img.height * ratio)), Image.LANCZOS))

        # 标签高度
        label_h = 30
        total_h = sum(img.height + label_h for img in resized) + 20
        sheet = Image.new("RGB", (target_w + 40, total_h), (255, 255, 255))
        draw = ImageDraw.Draw(sheet)
        y = 10
        for img, label in zip(resized, labels):
            draw.text((20, y), label, fill=(0, 0, 0))
            y += label_h
            sheet.paste(img, (20, y))
            y += img.height + 10

        sheet_path = CONTACT_SHEET_DIR / f"answer_sheet_{i // sheet_size:04d}.png"
        sheet.save(sheet_path, optimize=True)
        sheets.append(sheet_path)

    return sheets


# ── 审核提示词 ────────────────────────────────────────

SOURCE_REVIEW_PROMPT = """你是数学题库质量审核专家。请审核这一页源PDF中的所有题目。

对每道题检查：
1. 题干是否与原书一致（无遗漏、无错字、公式完整）
2. LaTeX公式是否正确
3. 选择题选项是否完整（A/B/C/D）且内容正确
4. 题干提到"如图/见图/图中/下图"时是否有对应的图
5. 图是否裁切正确、清晰、没有无关内容

请严格按以下JSON格式输出（不要输出其他内容）：
{
  "questions": [
    {
      "uid": "题目uid（从页面标注读取）",
      "content_match": true/false,
      "latex_ok": true/false,
      "options_ok": true/false,
      "figure_ok": true/false,
      "issues": ["问题代码列表，如 content_mismatch, latex_error, missing_option, missing_figure, wrong_crop"],
      "confidence": 0.0-1.0,
      "notes": "简要说明"
    }
  ]
}
"""

ANSWER_REVIEW_PROMPT = """你是数学题库质量审核专家。这张联系表包含多道题的答案图，每题上方标注了uid。

对每道题检查：
1. 答案图是否存在且清晰
2. 答案图是否对应当前题（不串题）
3. 选择题答案是否为A/B/C/D
4. 填空题答案是否完整
5. 解答题/证明题答案是否完整

请严格按以下JSON格式输出（不要输出其他内容）：
{
  "questions": [
    {
      "uid": "题目uid",
      "answer_exists": true/false,
      "answer_matches": true/false,
      "answer_structurable": true/false,
      "canonical_answer": "标准答案（选择题为A/B/C/D，填空题为标准写法）",
      "issues": ["问题代码列表"],
      "confidence": 0.0-1.0,
      "notes": "简要说明"
    }
  ]
}
"""


# ── 流水线步骤 ────────────────────────────────────────

def cmd_init(args) -> int:
    """初始化账本。"""
    if LEDGER_PATH.exists() and not args.force:
        ledger = load_ledger()
        print(f"账本已存在: {LEDGER_PATH}")
        print(f"题目数: {ledger['total_questions']}")
        return 0
    ledger = init_ledger()
    print(f"账本已初始化: {LEDGER_PATH}")
    print(f"题目数: {ledger['total_questions']}")
    return 0


def cmd_status(args) -> int:
    """查看账本状态。"""
    ledger = load_ledger()
    entries = ledger["entries"]
    by_status = defaultdict(int)
    by_book = defaultdict(lambda: defaultdict(int))
    for e in entries.values():
        by_status[e.get("overall_status", STATUS_PENDING)] += 1
        by_book[e.get("book", "?")][e.get("overall_status", STATUS_PENDING)] += 1

    print(f"账本: {LEDGER_PATH}")
    print(f"总题数: {ledger['total_questions']}")
    print(f"更新时间: {ledger.get('updated_at', '?')}")
    print(f"\n状态统计:")
    for status, count in sorted(by_status.items()):
        print(f"  {status}: {count}")
    print(f"\n按题库:")
    for book, stats in sorted(by_book.items()):
        total = sum(stats.values())
        print(f"  {book} ({total}题):")
        for status, count in sorted(stats.items()):
            print(f"    {status}: {count}")
    return 0


def cmd_render(args) -> int:
    """预渲染所有源页到缓存。"""
    ledger = load_ledger()
    questions = load_all_questions()
    # 按 (book, page) 去重
    pages = set()
    for q in questions:
        page = q.get("page")
        if page:
            pages.add((q["_book"], page))

    print(f"需要渲染 {len(pages)} 个源页")
    rendered = 0
    cached = 0
    errors = 0
    for book, page in sorted(pages):
        # 找一道该页的题来获取PDF路径
        q = next((x for x in questions if x["_book"] == book and x.get("page") == page), None)
        if not q:
            continue
        pdf_path = get_pdf_path(q)
        if not pdf_path:
            errors += 1
            continue
        try:
            cache_path = render_pdf_page(pdf_path, page, dpi=args.dpi)
            if cache_path.exists():
                # 更新账本中的渲染哈希
                render_hash = sha256_file(cache_path)[:16]
                for uid, entry in ledger["entries"].items():
                    if entry.get("book") == book and entry.get("page") == page:
                        entry["source_page_render_hash"] = render_hash
                if cache_path.stat().st_size > 0:
                    rendered += 1
                else:
                    cached += 1
        except Exception as e:
            errors += 1
            print(f"  渲染失败 {book} p{page}: {e}")

    save_ledger(ledger)
    print(f"渲染完成: 新渲染={rendered} 已缓存={cached} 失败={errors}")
    return 0


def cmd_review_source(args) -> int:
    """题干审核（按源页批量）。"""
    ledger = load_ledger()
    config = load_config()
    questions = load_all_questions()

    # 检查模型配置
    primary = VisionModelClient(config["models"]["primary"], "primary")
    secondary = VisionModelClient(config["models"]["secondary"], "secondary")

    if not primary.is_configured():
        print(f"[跳过] 主视觉模型未配置（设置 {primary.config['api_key_env']} 和 {primary.config['base_url_env']}）")
        print("       相关题保持 pending，不伪造审核结果")
        return 0

    # 按页分组
    pages = defaultdict(list)
    for q in questions:
        page = q.get("page")
        if page:
            pages[(q["_book"], page)].append(q)

    print(f"待审核源页: {len(pages)}")
    reviewed = 0
    for (book, page), page_questions in sorted(pages.items()):
        # 检查是否需要重审（哈希变化或未审核）
        needs_review = False
        for q in page_questions:
            uid = q.get("uid")
            entry = ledger["entries"].get(uid)
            if not entry:
                continue
            if entry.get("source_review_status") != STATUS_SOURCE_VERIFIED:
                needs_review = True
                break
            content_h = question_content_hash(q)
            if entry.get("content_hash") != content_h:
                needs_review = True
                break
        if not needs_review and not args.force:
            continue

        # 渲染源页
        q0 = page_questions[0]
        pdf_path = get_pdf_path(q0)
        if not pdf_path:
            continue
        try:
            img_path = render_pdf_page(pdf_path, page, dpi=config["pdf_dpi"])
        except Exception as e:
            print(f"  渲染失败 {book} p{page}: {e}")
            continue

        # 双模型审核
        results = []
        for client in [primary, secondary]:
            if not client.is_configured():
                continue
            result = client.review_image(img_path, SOURCE_REVIEW_PROMPT)
            if result:
                results.append(result)
                # 保存原始输出
                out_path = MODEL_OUTPUT_DIR / f"source_{book}_p{page}_{client.name}.json"
                atomic_write_json(out_path, result)

        # 解析结果并更新账本
        for result in results:
            output = result.get("output", {})
            for q_result in output.get("questions", []):
                uid = q_result.get("uid")
                entry = ledger["entries"].get(uid)
                if not entry:
                    continue
                model_name = result.get("model", "unknown")
                entry["model_versions"][f"source_{model_name}"] = {
                    "confidence": q_result.get("confidence", 0),
                    "issues": q_result.get("issues", []),
                    "reviewed_at": now_iso(),
                }
                entry["model_request_count"] = entry.get("model_request_count", 0) + 1

        # 判断是否一致
        if len(results) >= 2:
            # 比较两模型结果
            for q in page_questions:
                uid = q.get("uid")
                entry = ledger["entries"].get(uid)
                if not entry:
                    continue
                model_results = {k: v for k, v in entry.get("model_versions", {}).items() if k.startswith("source_")}
                if len(model_results) >= 2:
                    # 简单一致性检查：issues是否一致
                    issue_sets = [set(v.get("issues", [])) for v in model_results.values()]
                    if issue_sets[0] == issue_sets[1]:
                        if not issue_sets[0]:
                            update_entry_status(ledger, uid, source_review_status=STATUS_SOURCE_VERIFIED)
                        else:
                            update_entry_status(ledger, uid, source_review_status=STATUS_HOLD,
                                                issue_codes=list(issue_sets[0]))
                    else:
                        update_entry_status(ledger, uid, source_review_status=STATUS_CONFLICT,
                                            conflicts=["source_model_disagreement"])
        elif len(results) == 1:
            # 只有一个模型，标记为需裁决
            for q in page_questions:
                uid = q.get("uid")
                entry = ledger["entries"].get(uid)
                if not entry:
                    continue
                issues = []
                for mv in entry.get("model_versions", {}).values():
                    issues.extend(mv.get("issues", []))
                if issues:
                    update_entry_status(ledger, uid, source_review_status=STATUS_HOLD, issue_codes=list(set(issues)))
                else:
                    update_entry_status(ledger, uid, source_review_status=STATUS_RULE_PASSED)

        reviewed += len(page_questions)
        if reviewed % 50 == 0:
            save_ledger(ledger)
            print(f"  已审核 {reviewed} 题...")

    save_ledger(ledger)
    print(f"题干审核完成: {reviewed} 题")
    return 0


def cmd_review_answer(args) -> int:
    """答案审核（联系表批量）。"""
    ledger = load_ledger()
    config = load_config()
    questions = load_all_questions()

    primary = VisionModelClient(config["models"]["primary"], "primary")
    secondary = VisionModelClient(config["models"]["secondary"], "secondary")

    if not primary.is_configured():
        print(f"[跳过] 主视觉模型未配置")
        return 0

    # 过滤需要审核的题
    to_review = []
    for q in questions:
        uid = q.get("uid")
        entry = ledger["entries"].get(uid)
        if not entry:
            continue
        if entry.get("answer_review_status") == STATUS_ANSWER_VERIFIED and not args.force:
            continue
        answer_h = question_answer_hash(q)
        if entry.get("answer_hash") != answer_h or args.force:
            to_review.append(q)

    print(f"待审核答案: {len(to_review)} 题")

    # 生成联系表
    sheet_size = config["contact_sheet"]["questions_per_sheet"]
    sheets = build_answer_contact_sheets(to_review, sheet_size)
    print(f"生成 {len(sheets)} 张联系表")

    reviewed = 0
    for sheet_idx, sheet_path in enumerate(sheets):
        batch = to_review[sheet_idx * sheet_size:(sheet_idx + 1) * sheet_size]
        results = []
        for client in [primary, secondary]:
            if not client.is_configured():
                continue
            result = client.review_image(sheet_path, ANSWER_REVIEW_PROMPT)
            if result:
                results.append(result)
                out_path = MODEL_OUTPUT_DIR / f"answer_sheet_{sheet_idx:04d}_{client.name}.json"
                atomic_write_json(out_path, result)

        for result in results:
            output = result.get("output", {})
            for q_result in output.get("questions", []):
                uid = q_result.get("uid")
                entry = ledger["entries"].get(uid)
                if not entry:
                    continue
                model_name = result.get("model", "unknown")
                entry["model_versions"][f"answer_{model_name}"] = {
                    "confidence": q_result.get("confidence", 0),
                    "issues": q_result.get("issues", []),
                    "canonical_answer": q_result.get("canonical_answer"),
                    "reviewed_at": now_iso(),
                }
                entry["model_request_count"] = entry.get("model_request_count", 0) + 1

        # 一致性判断（简化）
        if len(results) >= 2:
            for q in batch:
                uid = q.get("uid")
                entry = ledger["entries"].get(uid)
                if not entry:
                    continue
                model_results = {k: v for k, v in entry.get("model_versions", {}).items() if k.startswith("answer_")}
                if len(model_results) >= 2:
                    issue_sets = [set(v.get("issues", [])) for v in model_results.values()]
                    if issue_sets[0] == issue_sets[1]:
                        if not issue_sets[0]:
                            update_entry_status(ledger, uid, answer_review_status=STATUS_ANSWER_VERIFIED)
                        else:
                            update_entry_status(ledger, uid, answer_review_status=STATUS_HOLD,
                                                issue_codes=list(issue_sets[0]))
                    else:
                        update_entry_status(ledger, uid, answer_review_status=STATUS_CONFLICT,
                                            conflicts=["answer_model_disagreement"])
        elif len(results) == 1:
            for q in batch:
                uid = q.get("uid")
                entry = ledger["entries"].get(uid)
                if not entry:
                    continue
                issues = []
                for mv in entry.get("model_versions", {}).values():
                    if "answer_" in str(mv):
                        issues.extend(mv.get("issues", []))
                if issues:
                    update_entry_status(ledger, uid, answer_review_status=STATUS_HOLD, issue_codes=list(set(issues)))
                else:
                    update_entry_status(ledger, uid, answer_review_status=STATUS_RULE_PASSED)

        reviewed += len(batch)
        if reviewed % 50 == 0:
            save_ledger(ledger)
            print(f"  已审核 {reviewed} 题...")

    save_ledger(ledger)
    print(f"答案审核完成: {reviewed} 题")
    return 0


def cmd_arbitrate(args) -> int:
    """冲突裁决：对conflict状态的题用第三模型裁决。"""
    ledger = load_ledger()
    config = load_config()
    arbitrator = VisionModelClient(config["models"]["arbitrator"], "arbitrator")

    if not arbitrator.is_configured():
        print("[跳过] 裁决模型未配置")
        return 0

    conflicts = [uid for uid, e in ledger["entries"].items() if e.get("overall_status") == STATUS_CONFLICT]
    print(f"待裁决冲突题: {len(conflicts)}")
    # 这里实现具体的裁决逻辑，需要重新渲染对应页面/联系表
    # 简化：标记为hold等待人工
    for uid in conflicts:
        update_entry_status(ledger, uid, overall_status=STATUS_HOLD,
                            conflicts=ledger["entries"][uid].get("conflicts", []) + ["needs_arbitration"])
    save_ledger(ledger)
    print(f"已标记 {len(conflicts)} 题为 hold（需人工或第三模型裁决）")
    return 0


def cmd_run(args) -> int:
    """全流程：init → render → review-source → review-answer → arbitrate。"""
    print("=== 1/5 初始化账本 ===")
    cmd_init(argparse.Namespace(force=False))
    print("\n=== 2/5 渲染源页 ===")
    cmd_render(argparse.Namespace(dpi=load_config()["pdf_dpi"]))
    print("\n=== 3/5 题干审核 ===")
    cmd_review_source(argparse.Namespace(force=False))
    print("\n=== 4/5 答案审核 ===")
    cmd_review_answer(argparse.Namespace(force=False))
    print("\n=== 5/5 冲突裁决 ===")
    cmd_arbitrate(argparse.Namespace())
    print("\n=== 最终状态 ===")
    cmd_status(argparse.Namespace())
    return 0


def cmd_export(args) -> int:
    """导出审核报告。"""
    ledger = load_ledger()
    report = {
        "generated_at": now_iso(),
        "rule_version": ledger.get("rule_version"),
        "total": ledger["total_questions"],
        "by_status": {},
        "by_book": {},
        "hold_uids": [],
        "conflict_uids": [],
        "pending_count": 0,
        "strictly_verified_count": 0,
    }
    by_status = defaultdict(int)
    by_book = defaultdict(lambda: defaultdict(int))
    total_requests = 0
    for uid, e in ledger["entries"].items():
        status = e.get("overall_status", STATUS_PENDING)
        by_status[status] += 1
        by_book[e.get("book", "?")][status] += 1
        total_requests += e.get("model_request_count", 0)
        if status == STATUS_HOLD:
            report["hold_uids"].append(uid)
        elif status == STATUS_CONFLICT:
            report["conflict_uids"].append(uid)
        elif status == STATUS_PENDING:
            report["pending_count"] += 1
        elif status == "strictly_verified":
            report["strictly_verified_count"] += 1

    report["by_status"] = dict(by_status)
    report["by_book"] = {k: dict(v) for k, v in by_book.items()}
    report["total_model_requests"] = total_requests

    report_path = TEMP_DIR / "quality_report.json"
    atomic_write_json(report_path, report)
    print(f"报告: {report_path}")
    print(json.dumps(report["by_status"], ensure_ascii=False, indent=2))
    return 0


# ── 入口 ──────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="数学题库增量质量核验流水线")
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init", help="初始化账本")
    p_init.add_argument("--force", action="store_true", help="强制重建")
    p_init.set_defaults(func=cmd_init)

    p_status = sub.add_parser("status", help="查看状态")
    p_status.set_defaults(func=cmd_status)

    p_render = sub.add_parser("render", help="预渲染源页")
    p_render.add_argument("--dpi", type=int, default=200)
    p_render.set_defaults(func=cmd_render)

    p_src = sub.add_parser("review-source", help="题干审核")
    p_src.add_argument("--force", action="store_true")
    p_src.set_defaults(func=cmd_review_source)

    p_ans = sub.add_parser("review-answer", help="答案审核")
    p_ans.add_argument("--force", action="store_true")
    p_ans.set_defaults(func=cmd_review_answer)

    p_arb = sub.add_parser("arbitrate", help="冲突裁决")
    p_arb.set_defaults(func=cmd_arbitrate)

    p_run = sub.add_parser("run", help="全流程")
    p_run.set_defaults(func=cmd_run)

    p_exp = sub.add_parser("export", help="导出报告")
    p_exp.set_defaults(func=cmd_export)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
