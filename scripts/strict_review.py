#!/usr/bin/env python3
"""Luna + Kimi 的数学题库页级严格审核流水线。

本模块负责生成审核包、调用 Kimi Code、保存断点和合并结果。Luna 不通过外部
API 调用，而由 Codex 的 Luna 子代理读取同一批审核包后用 ``ingest`` 导入结果。
任何未同时获得两边独立证据的题目都不会被标记为 strictly_verified。
"""
from __future__ import annotations

import argparse
import base64
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import os
import re
import ssl
import time
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from PIL import Image, ImageDraw, ImageFont

from source_mapping import PdfRef, resolve_answer_pdf, resolve_question_pdf
from strict_audit import atomic_write_json, parse_strict_json


SCRIPT_DIR = Path(__file__).resolve().parent
BANK_ROOT = SCRIPT_DIR.parent
REPO_ROOT = BANK_ROOT.parent.parent
DEFAULT_KEY_FILE = Path(r"C:\Users\16416\Desktop\新建 Markdown 文档.md")
TEMP_ROOT = REPO_ROOT / "temp" / "math-quality" / "strict-review"
BUNDLE_ROOT = TEMP_ROOT / "bundles"
PAGE_ROOT = TEMP_ROOT / "pages"
OUTPUT_ROOT = TEMP_ROOT / "model_outputs"
CHECKPOINT_PATH = TEMP_ROOT / "strict-review-ledger.json"
BOOKS = ("660题", "880题", "1000题", "大学深埋")
KIMI_ENDPOINT = "https://api.kimi.com/coding/v1"
KIMI_MODEL = "kimi-for-coding"
SCHEMA_VERSION = 2
PROVIDER_MODELS = {
    "kimi": KIMI_MODEL,
    "luna": "gpt-5.6-luna",
    "glm": "glm-5.3-flash",
    "terra": "gpt-5.6-terra",
}
VALID_ISSUE_CODES = {
    "source_truncation", "source_mismatch", "source_page_mismatch",
    "formula_mismatch", "options_mismatch", "figure_missing",
    "figure_mismatch", "answer_image_missing", "answer_mismatch",
    "source_image_blurry", "hold_uncertain",
}
REVIEW_BOOLEAN_FIELDS = (
    "source_match", "answer_match", "figure_match", "formula_match", "options_match",
)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_json(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def load_questions() -> list[dict[str, Any]]:
    questions: list[dict[str, Any]] = []
    for book in BOOKS:
        path = BANK_ROOT / book / "questions.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        for chapter in data.get("chapters", []):
            for question in chapter.get("questions", []):
                item = dict(question)
                item["_book"] = book
                item["_chapter"] = chapter.get("name")
                questions.append(item)
    return questions


def read_runtime_kimi_key(path: Path = DEFAULT_KEY_FILE) -> str:
    """从密钥文件运行时读取 Kimi Code Key；绝不打印或持久化。"""
    lines = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    labeled: list[str] = []
    for line in lines:
        match = re.match(r"^kimi\s*[:：]\s*(.+)$", line, flags=re.IGNORECASE)
        if match:
            labeled.append(match.group(1).strip())
    if labeled:
        return labeled[0]
    # 当前文件格式：第1行是第三方 Base URL，第2行 Kimi，第3行 MiniMax。
    if len(lines) >= 2 and lines[0].lower().startswith(("http://", "https://")):
        return lines[1]
    raise RuntimeError("密钥文件中未找到带 kimi: 标签或第二行 Kimi Key")


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for name in (r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\simhei.ttf"):
        if Path(name).is_file():
            try:
                return ImageFont.truetype(name, size)
            except OSError:
                pass
    return ImageFont.load_default()


def _wrap(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, width: int) -> list[str]:
    text = str(text or "").replace("\r", "")
    lines: list[str] = []
    for paragraph in text.split("\n") or [""]:
        current = ""
        for char in paragraph:
            candidate = current + char
            if current and draw.textlength(candidate, font=font) > width:
                lines.append(current)
                current = char
            else:
                current = candidate
        lines.append(current)
    return lines or [""]


def _media_path(book: str, ref: Any) -> Path | None:
    if not ref:
        return None
    rel = ref.get("cropped") if isinstance(ref, dict) else ref
    if not rel:
        return None
    path = (BANK_ROOT / book / "math-bank" / str(rel)).resolve()
    root = (BANK_ROOT / book).resolve()
    if root not in path.parents or not path.is_file():
        return None
    return path


def render_source_page(ref: PdfRef, dpi: int = 150) -> Path:
    if not ref.path.is_file():
        raise FileNotFoundError(f"原题PDF不存在: {ref.path.name}")
    key = f"{sha256_file(ref.path)[:16]}_p{ref.page}_d{dpi}.png"
    output = PAGE_ROOT / key
    if output.is_file():
        return output
    import fitz

    PAGE_ROOT.mkdir(parents=True, exist_ok=True)
    document = fitz.open(ref.path)
    try:
        if ref.page < 1 or ref.page > len(document):
            raise ValueError(f"页码超出范围: {ref.path.name} p{ref.page}/{len(document)}")
        pixmap = document[ref.page - 1].get_pixmap(matrix=fitz.Matrix(dpi / 72, dpi / 72), alpha=False)
        pixmap.save(str(output))
    finally:
        document.close()
    return output


def _thumb(path: Path | None, size: tuple[int, int]) -> Image.Image:
    if path is None:
        return Image.new("RGB", size, "#f4f4f5")
    try:
        image = Image.open(path).convert("RGB")
        image.thumbnail(size, Image.Resampling.LANCZOS)
        canvas = Image.new("RGB", size, "white")
        canvas.paste(image, ((size[0] - image.width) // 2, (size[1] - image.height) // 2))
        return canvas
    except (OSError, ValueError):
        return Image.new("RGB", size, "#fee2e2")


def build_question_sheet(questions: list[dict[str, Any]], output: Path) -> Path:
    width = 1800
    title_font, body_font, small_font = _font(28), _font(24), _font(20)
    row_h = 430
    sheet = Image.new("RGB", (width, 80 + row_h * len(questions)), "white")
    draw = ImageDraw.Draw(sheet)
    draw.text((30, 20), "当前题库数据（与生产 questions.json 同源）", fill="#111827", font=title_font)
    for index, question in enumerate(questions):
        y = 80 + index * row_h
        draw.rectangle((15, y + 5, width - 15, y + row_h - 10), outline="#d1d5db", width=2)
        uid = str(question.get("uid") or "")
        label = f"{uid} | {question.get('type') or ''} | page={question.get('page')}"
        draw.text((35, y + 20), label, fill="#1d4ed8", font=body_font)
        x_text, text_w = 35, 1240
        content = str(question.get("content") or "")
        lines = _wrap(draw, "题干：" + content, body_font, text_w)
        options = question.get("options") or {}
        if isinstance(options, dict):
            option_text = "；".join(f"{key}. {value}" for key, value in options.items())
            lines.extend(_wrap(draw, "选项：" + option_text, small_font, text_w))
        for line_index, line in enumerate(lines[:12]):
            draw.text((x_text, y + 65 + line_index * 29), line, fill="#111827", font=body_font if line_index == 0 else small_font)
        image_path = _media_path(str(question["_book"]), question.get("image_ref"))
        image = _thumb(image_path, (430, 300))
        sheet.paste(image, (1335, y + 50))
        draw.text((1350, y + 355), "题图" if image_path else "无题图", fill="#374151", font=small_font)
    output.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output, "JPEG", quality=86, optimize=True)
    return output


def build_answer_sheet(questions: list[dict[str, Any]], output: Path) -> Path:
    width = 1800
    label_font, small_font = _font(26), _font(20)
    row_h = 360
    sheet = Image.new("RGB", (width, 40 + row_h * len(questions)), "white")
    draw = ImageDraw.Draw(sheet)
    for index, question in enumerate(questions):
        y = 20 + index * row_h
        uid = str(question.get("uid") or "")
        draw.text((30, y + 18), uid, fill="#7c3aed", font=label_font)
        answer_path = _media_path(str(question["_book"]), question.get("answer_ref"))
        sheet.paste(_thumb(answer_path, (1600, 285)), (170, y + 5))
        draw.text((30, y + 320), "答案图" if answer_path else "答案图缺失", fill="#374151", font=small_font)
    output.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output, "JPEG", quality=86, optimize=True)
    return output


def _group_key(question: dict[str, Any]) -> tuple[str, str, int]:
    ref = resolve_question_pdf(question)
    if ref is None:
        raise ValueError(f"题目缺少原题页: {question.get('uid')}")
    return str(question["_book"]), str(ref.path), ref.page


def build_manifest(
    limit: int | None = None,
    books: set[str] | None = None,
    per_book: int | None = None,
) -> dict[str, Any]:
    questions = [q for q in load_questions() if not books or q["_book"] in books]
    grouped: dict[tuple[str, str, int], list[dict[str, Any]]] = defaultdict(list)
    for question in questions:
        grouped[_group_key(question)].append(question)
    bundles: list[dict[str, Any]] = []
    book_counts: defaultdict[str, int] = defaultdict(int)
    for key in sorted(grouped):
        book, source_pdf, page = key
        if per_book is not None and book_counts[book] >= per_book:
            continue
        ref = PdfRef(Path(source_pdf), page)
        source_image = render_source_page(ref)
        page_questions = grouped[key]
        for chunk_index in range(0, len(page_questions), 8):
            chunk = page_questions[chunk_index : chunk_index + 8]
            metadata = [
                {
                    "uid": q.get("uid"),
                    "type": q.get("type"),
                    "content": q.get("content"),
                    "options": q.get("options"),
                    "has_image": bool(q.get("has_image") or q.get("image_ref")),
                    "chapter": q.get("_chapter"),
                }
                for q in chunk
            ]
            bundle_id = hashlib.sha256(
                json.dumps([book, source_pdf, page, chunk_index // 8], ensure_ascii=False).encode("utf-8")
            ).hexdigest()[:20]
            bundle_dir = BUNDLE_ROOT / bundle_id
            question_sheet = build_question_sheet(chunk, bundle_dir / "questions.jpg")
            answer_sheet = build_answer_sheet(chunk, bundle_dir / "answers.jpg")
            bundles.append(
                {
                    "schema_version": SCHEMA_VERSION,
                    "bundle_id": bundle_id,
                    "book": book,
                    "source_pdf": source_pdf,
                    "page": page,
                    "chunk_index": chunk_index // 8,
                    "source_image": str(source_image),
                    "question_sheet": str(question_sheet),
                    "answer_sheet": str(answer_sheet),
                    "questions": metadata,
                    "input_hashes": {
                        "source": sha256_file(source_image),
                        "questions": sha256_file(question_sheet),
                        "answers": sha256_file(answer_sheet),
                    },
                }
            )
            book_counts[book] += 1
            if limit is not None and len(bundles) >= limit:
                break
            if per_book is not None and book_counts[book] >= per_book:
                break
        if limit is not None and len(bundles) >= limit:
            break
    manifest = {"schema_version": SCHEMA_VERSION, "created_at": now_iso(), "bundles": bundles}
    path = TEMP_ROOT / "manifest.json"
    atomic_write_json(path, manifest)
    return manifest


def _image_data(path: Path) -> str:
    suffix = path.suffix.lower()
    mime = "image/png" if suffix == ".png" else "image/jpeg"
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode('ascii')}"


def _prompt(bundle: dict[str, Any]) -> str:
    payload = json.dumps(bundle["questions"], ensure_ascii=False, separators=(",", ":"))
    return f"""你是数学题库严格校对员。请独立审核这一页原PDF、当前题库数据卡片和答案图。
逐题检查题干、LaTeX公式、选择项、题图是否与原PDF一致，答案图是否属于该题且内容完整。
不要猜测；无法确认就把 confidence 降低并加入 issues。只输出严格JSON，不要Markdown围栏，不要解释。
当前题目元数据（UID必须原样返回）：{payload}
返回格式：{{"questions":[{{"uid":"","source_match":true,"answer_match":true,"figure_match":true,"formula_match":true,"options_match":true,"confidence":0.0,"issues":[],"notes":""}}]}}"""


class KimiClient:
    def __init__(self, key: str, endpoint: str = KIMI_ENDPOINT, model: str = KIMI_MODEL):
        self.key = key
        self.endpoint = endpoint.rstrip("/")
        self.model = model

    def review(self, bundle: dict[str, Any]) -> dict[str, Any]:
        content = [{"type": "text", "text": _prompt(bundle)}]
        for field in ("source_image", "question_sheet", "answer_sheet"):
            content.append({"type": "image_url", "image_url": {"url": _image_data(Path(bundle[field]))}})
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": content}],
            # kimi-for-coding 默认开启思考；max_tokens 同时覆盖思考与JSON输出，
            # 过低会在 JSON 中途以 finish_reason=length 截断。
            "max_tokens": 10000,
            # Kimi Code 对该模型仅接受默认温度1，使用严格JSON提示词保证格式。
            "temperature": 1,
            "prompt_cache_key": "bank-math-strict-audit-v2",
            "response_format": {"type": "json_object"},
        }
        request = urllib.request.Request(
            f"{self.endpoint}/chat/completions",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.key}"},
            method="POST",
        )
        started = time.monotonic()
        response_meta: dict[str, Any] = {}
        try:
            # 先直连；本机网络栈超时后再走 AGENTS 约定的 7897 代理。
            try:
                response_ctx = urllib.request.urlopen(request, timeout=30, context=ssl._create_unverified_context())
            except (urllib.error.URLError, TimeoutError):
                proxy = urllib.request.ProxyHandler({"http": "http://127.0.0.1:7897", "https": "http://127.0.0.1:7897"})
                opener = urllib.request.build_opener(proxy, urllib.request.HTTPSHandler(context=ssl._create_unverified_context()))
                response_ctx = opener.open(request, timeout=60)
            with response_ctx as response:
                body = json.loads(response.read().decode("utf-8"))
            choice = body["choices"][0]
            message_obj = choice.get("message") or {}
            message = message_obj.get("content")
            response_meta = {
                "choice_count": len(body.get("choices", [])),
                "message_keys": sorted(message_obj.keys()) if isinstance(message_obj, dict) else [],
                "content_type": type(message).__name__,
                "content_length": len(message) if isinstance(message, str) else None,
                "reasoning_length": len(message_obj.get("reasoning_content", "")) if isinstance(message_obj, dict) and isinstance(message_obj.get("reasoning_content"), str) else None,
                "finish_reason": choice.get("finish_reason"),
            }
            parsed = parse_strict_json(message)
            if not isinstance(parsed.get("questions"), list):
                raise ValueError("响应缺少 questions 数组")
            return {
                "provider": "kimi",
                "model": self.model,
                "status": "ok",
                "latency_ms": round((time.monotonic() - started) * 1000),
                "usage": body.get("usage") or {},
                "questions": parsed["questions"],
                "response_meta": response_meta,
            }
        except urllib.error.HTTPError as error:
            # 只保存经过截断的服务端错误摘要，避免把响应正文/凭证写入检查点。
            message = ""
            try:
                detail = json.loads(error.read().decode("utf-8", errors="replace"))
                err = detail.get("error") if isinstance(detail, dict) else None
                message = str(err.get("message") if isinstance(err, dict) else detail.get("message", ""))
            except (OSError, ValueError, TypeError):
                pass
            message = re.sub(r"Bearer\s+\S+", "Bearer [REDACTED]", message)[:300]
            return {"provider": "kimi", "model": self.model, "status": "http_error", "http_status": error.code, "error_message": message}
        except (urllib.error.URLError, TimeoutError) as error:
            return {"provider": "kimi", "model": self.model, "status": "network_error", "error_type": type(error).__name__}
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            message = re.sub(r"Bearer\s+\S+", "Bearer [REDACTED]", str(error))[:300]
            return {"provider": "kimi", "model": self.model, "status": "invalid_response", "error_type": type(error).__name__, "error_message": message, "response_meta": response_meta}


def _load_checkpoint() -> dict[str, Any]:
    if CHECKPOINT_PATH.is_file():
        return json.loads(CHECKPOINT_PATH.read_text(encoding="utf-8"))
    return {"schema_version": SCHEMA_VERSION, "created_at": now_iso(), "updated_at": now_iso(), "bundles": {}}


def _save_checkpoint(data: dict[str, Any]) -> None:
    data["updated_at"] = now_iso()
    atomic_write_json(CHECKPOINT_PATH, data)


def run_kimi(manifest: dict[str, Any], key_file: Path, limit: int | None = None, skip_ids: set[str] | None = None) -> dict[str, Any]:
    key = read_runtime_kimi_key(key_file)
    client = KimiClient(key)
    checkpoint = _load_checkpoint()
    # 断点文件可能由单包 smoke 创建；运行完整 manifest 时补齐其余包。
    for bundle in manifest.get("bundles", []):
        checkpoint.setdefault("bundles", {}).setdefault(bundle["bundle_id"], {"bundle": bundle})
    pending = []
    for bundle in manifest["bundles"]:
        if skip_ids and bundle["bundle_id"] in skip_ids:
            continue
        record = checkpoint["bundles"].get(bundle["bundle_id"], {})
        if record.get("kimi", {}).get("status") == "ok":
            continue
        pending.append(bundle)
        if limit is not None and len(pending) >= limit:
            break

    def review_with_retry(bundle: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        result: dict[str, Any] = {}
        for attempt in range(3):
            result = client.review(bundle)
            if result.get("status") == "ok":
                break
            if result.get("http_status") in {401, 402}:
                break
            if attempt < 2:
                time.sleep(2 ** attempt)
        return bundle, result

    # 默认并发2；429时剩余任务降为串行，避免继续触发限流。
    concurrency = 2
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = {pool.submit(review_with_retry, bundle): bundle for bundle in pending}
        for future in as_completed(futures):
            bundle, result = future.result()
            record = checkpoint["bundles"].get(bundle["bundle_id"], {})
            record.update({"bundle": bundle, "kimi": result})
            checkpoint["bundles"][bundle["bundle_id"]] = record
            _save_checkpoint(checkpoint)
            if result.get("http_status") in {401, 402}:
                for other in futures:
                    if other is not future:
                        other.cancel()
                break
    return checkpoint


def merge_results(checkpoint: dict[str, Any], provider: str, results: Iterable[dict[str, Any]]) -> dict[str, Any]:
    by_id = {str(item.get("bundle_id")): item for item in results}
    for bundle_id, record in checkpoint.get("bundles", {}).items():
        item = by_id.get(bundle_id)
        if item is not None:
            record[provider] = item.get("result", item)
    _save_checkpoint(checkpoint)
    return checkpoint


def _result_is_pass(result: dict[str, Any]) -> bool:
    """模型只有在所有证据字段为真、置信度足够且无问题时才算通过。"""
    fields = ("source_match", "answer_match", "figure_match", "formula_match", "options_match")
    return all(result.get(field) is True for field in fields) and float(result.get("confidence") or 0) >= 0.9 and not result.get("issues")


def _normalise_provider_results(bundle: dict[str, Any], provider: str, value: Any) -> tuple[dict[str, Any], list[str]]:
    """校验并规范化各 provider 的逐题结果，拒绝未知 UID 和缺失 UID。"""
    if isinstance(value, dict) and isinstance(value.get("questions"), list):
        rows = value["questions"]
    elif isinstance(value, list):
        rows = value
    else:
        raise ValueError("结果必须是 questions 数组或包含 questions 的对象")
    expected = [str(item.get("uid")) for item in bundle.get("questions", [])]
    expected_set = set(expected)
    seen: set[str] = set()
    output: dict[str, Any] = {}
    errors: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            errors.append("row_not_object")
            continue
        uid = str(row.get("uid") or "")
        if uid not in expected_set:
            errors.append(f"unknown_uid:{uid}")
            continue
        if uid in seen:
            errors.append(f"duplicate_uid:{uid}")
            continue
        seen.add(uid)
        clean = {key: row.get(key) for key in (
            "uid", "source_match", "answer_match", "figure_match", "formula_match", "options_match",
            "confidence", "issues", "notes",
        )}
        clean["uid"] = uid
        if provider in {"glm", "terra"}:
            for field in REVIEW_BOOLEAN_FIELDS:
                if not isinstance(clean.get(field), bool):
                    errors.append(f"invalid_{field}:{uid}")
            if not isinstance(clean.get("issues"), list):
                errors.append(f"invalid_issues:{uid}")
            elif any(not isinstance(issue, str) or issue not in VALID_ISSUE_CODES for issue in clean["issues"]):
                errors.append(f"invalid_issue_code:{uid}")
            if not isinstance(clean.get("notes"), str):
                errors.append(f"invalid_notes:{uid}")
            raw_confidence = clean.get("confidence")
            if isinstance(raw_confidence, bool) or not isinstance(raw_confidence, (int, float)) or not 0 <= raw_confidence <= 1:
                errors.append(f"invalid_confidence:{uid}")
            elif "hold_uncertain" in clean.get("issues", []) and raw_confidence > 0.6:
                errors.append(f"hold_confidence_too_high:{uid}")
        clean["issues"] = clean.get("issues") if isinstance(clean.get("issues"), list) else ([str(clean["issues"])] if clean.get("issues") else [])
        try:
            clean["confidence"] = max(0.0, min(1.0, float(clean.get("confidence") or 0)))
        except (TypeError, ValueError):
            clean["confidence"] = 0.0
            clean["issues"].append("invalid_confidence")
        output[uid] = clean
    missing = expected_set - seen
    errors.extend(f"missing_uid:{uid}" for uid in sorted(missing))
    return output, errors


def _provider_rows(record: dict[str, Any], provider: str) -> dict[str, Any]:
    value = record.get(provider, {})
    if value.get("status") != "ok":
        return {}
    rows = value.get("questions_by_uid", {})
    if not rows and isinstance(value.get("questions"), list):
        rows = {str(row.get("uid")): row for row in value["questions"] if isinstance(row, dict) and row.get("uid")}
    return rows if isinstance(rows, dict) else {}


def recompute_question_status(checkpoint: dict[str, Any]) -> dict[str, Any]:
    """按主审(Kimi/Luna)和指定二审(GLM/Terra)汇总；不修改生产题库。"""
    per_uid: dict[str, dict[str, Any]] = {}
    for bundle_id, record in checkpoint.get("bundles", {}).items():
        bundle = record.get("bundle") or {}
        kimi_rows = _provider_rows(record, "kimi")
        luna_rows = _provider_rows(record, "luna")
        secondary_provider = record.get("secondary_provider")
        # 保持旧试验 checkpoint 的 Kimi+Luna 双审语义；正式流程会显式配置 GLM/Terra。
        if secondary_provider is None and kimi_rows and luna_rows:
            secondary_provider = "luna"
        secondary_rows = _provider_rows(record, str(secondary_provider)) if secondary_provider in {"luna", "glm", "terra"} else {}
        for question in bundle.get("questions", []):
            uid = str(question.get("uid"))
            k = kimi_rows.get(uid)
            l = luna_rows.get(uid)
            primary_provider = "kimi" if k is not None else ("luna" if l is not None else None)
            primary = k if primary_provider == "kimi" else l
            secondary = secondary_rows.get(uid)
            status = "pending"
            if primary is not None and secondary is not None:
                primary_pass, secondary_pass = _result_is_pass(primary), _result_is_pass(secondary)
                if primary_pass and secondary_pass:
                    status = "strictly_verified"
                elif primary_pass == secondary_pass:
                    status = "hold"
                else:
                    status = "conflict"
            per_uid[uid] = {
                "uid": uid,
                "bundle_id": bundle_id,
                "book": bundle.get("book"),
                "source_page": bundle.get("page"),
                "input_hashes": bundle.get("input_hashes", {}),
                "kimi_review": k,
                "luna_review": l,
                "glm_review": _provider_rows(record, "glm").get(uid),
                "terra_review": _provider_rows(record, "terra").get(uid),
                "primary_provider": primary_provider,
                "secondary_provider": secondary_provider,
                "primary_review": primary,
                "secondary_review": secondary,
                "overall_status": status,
                "request_count": sum(int(bool(_provider_rows(record, provider).get(uid))) for provider in PROVIDER_MODELS),
                "reviewed_at": now_iso() if primary is not None or secondary is not None else None,
            }
    checkpoint["questions"] = per_uid
    counts: defaultdict[str, int] = defaultdict(int)
    for item in per_uid.values():
        counts[item["overall_status"]] += 1
    checkpoint["question_status_counts"] = dict(counts)
    return checkpoint


def ingest_provider_items(
    checkpoint: dict[str, Any],
    provider: str,
    items: Iterable[dict[str, Any]],
    allowed_bundle_ids: set[str] | None = None,
) -> dict[str, Any]:
    """导入已解析的 provider 结果，并立即更新逐题汇总。"""
    if provider not in PROVIDER_MODELS:
        raise ValueError("provider 必须为 kimi、luna、glm 或 terra")
    by_id: dict[str, dict[str, Any]] = {}
    duplicate_bundle_ids: set[str] = set()
    for item in items:
        if not isinstance(item, dict) or not item.get("bundle_id"):
            continue
        bundle_id = str(item["bundle_id"])
        if bundle_id in by_id:
            duplicate_bundle_ids.add(bundle_id)
        by_id[bundle_id] = item
    invalid = 0
    for bundle_id, item in by_id.items():
        if bundle_id in duplicate_bundle_ids:
            invalid += 1
            continue
        if allowed_bundle_ids is not None and bundle_id not in allowed_bundle_ids:
            invalid += 1
            continue
        record = checkpoint.get("bundles", {}).get(bundle_id)
        if not record:
            invalid += 1
            continue
        bundle = record.get("bundle") or {}
        if provider in {"glm", "terra"} and record.get("secondary_provider") != provider:
            invalid += 1
            continue
        supplied_model = item.get("model")
        if provider in {"glm", "terra"} and supplied_model != PROVIDER_MODELS[provider]:
            invalid += 1
            continue
        if supplied_model and supplied_model != PROVIDER_MODELS[provider]:
            invalid += 1
            continue
        if provider in {"glm", "terra"} and item.get("input_hashes") != bundle.get("input_hashes", {}):
            invalid += 1
            continue
        if item.get("input_hashes") and item.get("input_hashes") != bundle.get("input_hashes", {}):
            invalid += 1
            continue
        if provider in {"glm", "terra"} and not isinstance(item.get("reviewed_at"), str):
            invalid += 1
            continue
        try:
            rows, errors = _normalise_provider_results(bundle, provider, item.get("questions", item))
        except ValueError as exc:
            rows, errors = {}, [str(exc)]
        if errors:
            record[provider] = {
                "provider": provider,
                "status": "invalid_response",
                "error_type": "uid_validation",
                "errors": errors[:100],
                "questions_by_uid": rows,
            }
            invalid += 1
        else:
            record[provider] = {
                "provider": provider,
                "model": PROVIDER_MODELS[provider],
                "status": "ok",
                "input_hashes": item.get("input_hashes") or bundle.get("input_hashes", {}),
                "questions_by_uid": rows,
                "reviewed_at": item.get("reviewed_at") or now_iso(),
            }
    recompute_question_status(checkpoint)
    _save_checkpoint(checkpoint)
    checkpoint["ingest_summary"] = {
        "provider": provider,
        "bundles": len(by_id),
        "invalid": invalid,
        "duplicate_bundle_ids": sorted(duplicate_bundle_ids),
    }
    return checkpoint


def ingest_provider(checkpoint: dict[str, Any], provider: str, path: Path) -> dict[str, Any]:
    """导入单个 Luna/Kimi JSON 文件。"""
    raw = json.loads(path.read_text(encoding="utf-8"))
    items = raw if isinstance(raw, list) else [raw]
    return ingest_provider_items(checkpoint, provider, items)


def load_result_files(results_dir: Path) -> list[dict[str, Any]]:
    """读取分片目录下的 batch JSON；忽略 summary 等非批次文件。"""
    items: list[dict[str, Any]] = []
    for path in sorted(results_dir.rglob("batch-*.json")):
        raw = json.loads(path.read_text(encoding="utf-8"))
        rows = raw if isinstance(raw, list) else [raw]
        if not all(isinstance(row, dict) for row in rows):
            raise ValueError(f"结果文件含非对象记录: {path}")
        items.extend(rows)
    return items


def configure_secondary_plan(checkpoint: dict[str, Any], plan_path: Path) -> dict[str, Any]:
    """将已校验的 GLM/Terra 二审分工写入临时 checkpoint。"""
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    assignments = plan.get("assignments") if isinstance(plan, dict) else None
    if not isinstance(assignments, list):
        raise ValueError("secondary plan 缺少 assignments 数组")
    by_id: dict[str, str] = {}
    for item in assignments:
        if not isinstance(item, dict):
            raise ValueError("secondary plan 含非对象 assignment")
        bundle_id = str(item.get("bundle_id") or "")
        provider = item.get("secondary_provider")
        if not bundle_id or provider not in {"glm", "terra"} or bundle_id in by_id:
            raise ValueError(f"secondary plan assignment 无效: {item}")
        by_id[bundle_id] = provider
    expected = set(checkpoint.get("bundles", {}))
    if set(by_id) != expected:
        missing = sorted(expected - set(by_id))[:5]
        unknown = sorted(set(by_id) - expected)[:5]
        raise ValueError(f"secondary plan 覆盖不完整: missing={missing}, unknown={unknown}")
    for bundle_id, provider in by_id.items():
        checkpoint["bundles"][bundle_id]["secondary_provider"] = provider
    checkpoint["secondary_plan"] = {
        "path": str(plan_path),
        "configured_at": now_iso(),
        "counts": {provider: sum(1 for value in by_id.values() if value == provider) for provider in ("glm", "terra")},
    }
    recompute_question_status(checkpoint)
    _save_checkpoint(checkpoint)
    return checkpoint


def export_quality_ledger(checkpoint: dict[str, Any], ledger_path: Path) -> dict[str, Any]:
    """将严格审核字段写回现有 quality-ledger；未审核题目保持原状态。"""
    ledger = json.loads(ledger_path.read_text(encoding="utf-8")) if ledger_path.is_file() else {
        "schema_version": 1, "entries": {}, "stats": {}
    }
    entries = ledger.setdefault("entries", {})
    for uid, review in checkpoint.get("questions", {}).items():
        entry = entries.get(uid)
        if not entry:
            continue
        entry["luna_review"] = review.get("luna_review")
        entry["kimi_review"] = review.get("kimi_review")
        entry["input_hashes"] = review.get("input_hashes", {})
        entry["model_request_count"] = review.get("request_count", 0)
        if review.get("reviewed_at"):
            entry["reviewed_at"] = review["reviewed_at"]
        status = review.get("overall_status")
        if status in {"strictly_verified", "conflict", "hold"}:
            entry["overall_status"] = status
            entry["source_review_status"] = status if status == "strictly_verified" else "pending"
            entry["answer_review_status"] = status if status == "strictly_verified" else "pending"
            entry["issue_codes"] = sorted({str(issue) for provider in ("kimi_review", "luna_review") for issue in (review.get(provider) or {}).get("issues", [])})
    counts: defaultdict[str, int] = defaultdict(int)
    for entry in entries.values():
        counts[str(entry.get("overall_status", "pending"))] += 1
    ledger["updated_at"] = now_iso()
    ledger["stats"] = {"total": len(entries), **dict(counts)}
    atomic_write_json(ledger_path, ledger)
    return ledger


def main() -> int:
    global CHECKPOINT_PATH
    parser = argparse.ArgumentParser(description="Luna + Kimi 数学题库严格审核")
    sub = parser.add_subparsers(dest="command", required=True)
    p_manifest = sub.add_parser("manifest", help="生成页级审核包")
    p_manifest.add_argument("--limit", type=int)
    p_manifest.add_argument("--per-book", type=int)
    p_manifest.add_argument("--book", action="append")
    p_smoke = sub.add_parser("smoke", help="运行Kimi单审核包测试")
    p_smoke.add_argument("--key-file", type=Path, default=DEFAULT_KEY_FILE)
    p_smoke.add_argument("--limit", type=int, default=1)
    p_run = sub.add_parser("run-kimi", help="断点续跑Kimi审核")
    p_run.add_argument("--manifest", type=Path, default=TEMP_ROOT / "manifest.json")
    p_run.add_argument("--key-file", type=Path, default=DEFAULT_KEY_FILE)
    p_run.add_argument("--limit", type=int)
    p_run.add_argument("--skip-bundle", action="append", default=[])
    p_secondary = sub.add_parser("configure-secondary", help="配置 GLM/Terra 二审分工")
    p_secondary.add_argument("--plan", type=Path, required=True)
    p_secondary.add_argument("--checkpoint", type=Path, default=CHECKPOINT_PATH)
    p_secondary.add_argument("--manifest", type=Path, default=TEMP_ROOT / "manifest.json")
    p_ingest = sub.add_parser("ingest", help="导入 provider 逐题结果")
    p_ingest.add_argument("--provider", choices=tuple(PROVIDER_MODELS), required=True)
    p_ingest.add_argument("--results", type=Path, required=True)
    p_ingest.add_argument("--checkpoint", type=Path, default=CHECKPOINT_PATH)
    p_ingest.add_argument("--manifest", type=Path, default=TEMP_ROOT / "manifest.json")
    p_ingest_dir = sub.add_parser("ingest-dir", help="导入一个或多个 provider 分片结果目录")
    p_ingest_dir.add_argument("--provider", choices=tuple(PROVIDER_MODELS), required=True)
    p_ingest_dir.add_argument("--results-dir", type=Path, action="append", required=True)
    p_ingest_dir.add_argument("--checkpoint", type=Path, default=CHECKPOINT_PATH)
    p_ingest_dir.add_argument("--manifest", type=Path, default=TEMP_ROOT / "manifest.json")
    p_ingest_dir.add_argument("--gap-manifest", type=Path, help="限制只能导入该缺口清单中的 bundle")
    p_export = sub.add_parser("export-ledger", help="将严格审核汇总导出到 quality-ledger.json")
    p_export.add_argument("--checkpoint", type=Path, default=CHECKPOINT_PATH)
    p_export.add_argument("--ledger", type=Path, default=BANK_ROOT / "quality-ledger.json")
    args = parser.parse_args()
    if args.command == "manifest":
        result = build_manifest(args.limit, set(args.book) if args.book else None, args.per_book)
        print(json.dumps({"bundles": len(result["bundles"]), "manifest": str(TEMP_ROOT / "manifest.json")}, ensure_ascii=False))
        return 0
    if args.command == "smoke":
        manifest = json.loads(args.manifest.read_text(encoding="utf-8")) if hasattr(args, "manifest") else build_manifest(args.limit)
        checkpoint = run_kimi(manifest, args.key_file, args.limit, set(args.skip_bundle))
        latest = list(checkpoint["bundles"].values())[-1]
        print(json.dumps({"bundle_id": latest.get("bundle", {}).get("bundle_id"), "kimi": latest.get("kimi", {}).get("status")}, ensure_ascii=False))
        return 0
    if args.command == "run-kimi":
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
        checkpoint = run_kimi(manifest, args.key_file, args.limit)
        statuses = defaultdict(int)
        for record in checkpoint["bundles"].values():
            statuses[record.get("kimi", {}).get("status", "pending")] += 1
        print(json.dumps({"bundles": len(checkpoint["bundles"]), "kimi_status": dict(statuses)}, ensure_ascii=False))
        return 0
    if args.command == "configure-secondary":
        CHECKPOINT_PATH = args.checkpoint
        checkpoint = _load_checkpoint()
        if args.manifest.is_file():
            manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
            for bundle in manifest.get("bundles", []):
                checkpoint.setdefault("bundles", {}).setdefault(bundle["bundle_id"], {"bundle": bundle})
        checkpoint = configure_secondary_plan(checkpoint, args.plan)
        print(json.dumps(checkpoint.get("secondary_plan", {}), ensure_ascii=False))
        return 0
    if args.command == "ingest":
        CHECKPOINT_PATH = args.checkpoint
        checkpoint = _load_checkpoint()
        if args.manifest.is_file():
            manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
            for bundle in manifest.get("bundles", []):
                checkpoint.setdefault("bundles", {}).setdefault(bundle["bundle_id"], {"bundle": bundle})
        checkpoint = ingest_provider(checkpoint, args.provider, args.results)
        print(json.dumps({
            "questions": len(checkpoint.get("questions", {})),
            "status_counts": checkpoint.get("question_status_counts", {}),
            "summary": checkpoint.get("ingest_summary", {}),
        }, ensure_ascii=False))
        return 0
    if args.command == "ingest-dir":
        CHECKPOINT_PATH = args.checkpoint
        checkpoint = _load_checkpoint()
        if args.manifest.is_file():
            manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
            for bundle in manifest.get("bundles", []):
                checkpoint.setdefault("bundles", {}).setdefault(bundle["bundle_id"], {"bundle": bundle})
        items: list[dict[str, Any]] = []
        for result_dir in args.results_dir:
            items.extend(load_result_files(result_dir))
        allowed_ids: set[str] | None = None
        if args.gap_manifest:
            gap = json.loads(args.gap_manifest.read_text(encoding="utf-8"))
            allowed_ids = {str(bundle["bundle_id"]) for bundle in gap.get("bundles", [])}
        checkpoint = ingest_provider_items(checkpoint, args.provider, items, allowed_ids)
        print(json.dumps({
            "questions": len(checkpoint.get("questions", {})),
            "status_counts": checkpoint.get("question_status_counts", {}),
            "summary": checkpoint.get("ingest_summary", {}),
        }, ensure_ascii=False))
        return 0
    if args.command == "export-ledger":
        CHECKPOINT_PATH = args.checkpoint
        checkpoint = _load_checkpoint()
        ledger = export_quality_ledger(checkpoint, args.ledger)
        print(json.dumps({"entries": len(ledger.get("entries", {})), "stats": ledger.get("stats", {})}, ensure_ascii=False))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
