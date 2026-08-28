#!/usr/bin/env python3
"""为选择题和填空题提取结构化答案。

- 选择题：OCR答案图，提取A/B/C/D，judge_mode=choice_exact
- 填空题：OCR答案图，提取标准答案，judge_mode=normalized_math（可靠时）或manual
- 计算题/证明题/解答题：不自动结构化，保留答案图

用法：
    python scripts/extract_structured_answers.py --bank 1000
    python scripts/extract_structured_answers.py --bank all
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from utils import write_json_atomic

ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = ROOT.parent.parent

BANK_CONFIG = {
    '660': {'name': '660题', 'questions': ROOT / '660题' / 'questions.json'},
    '880': {'name': '880题', 'questions': ROOT / '880题' / 'questions.json'},
    '1000': {'name': '1000题', 'questions': ROOT / '1000题' / 'questions.json'},
    '大学深埋': {'name': '大学深埋', 'questions': ROOT / '大学深埋' / 'questions.json'},
}

# OCR单例
_ocr = None
_ocr_backend = None


def get_ocr():
    global _ocr, _ocr_backend
    if _ocr is None:
        try:
            sys.path.insert(0, str(REPO_ROOT / "tools"))
            from ocr_gpu import create_rapid_ocr
            _ocr, _ocr_backend = create_rapid_ocr()
            print(f"[OCR] backend={_ocr_backend}", file=sys.stderr)
        except Exception as e:
            print(f"[OCR] GPU OCR init failed: {e}, falling back", file=sys.stderr)
            from rapidocr_onnxruntime import RapidOCR
            _ocr = RapidOCR()
            _ocr_backend = "cpu_fallback"
    return _ocr, _ocr_backend


def ocr_image(image_path: Path) -> str:
    """OCR图片，返回合并文本。"""
    if not image_path.exists():
        return ""
    ocr, _ = get_ocr()
    try:
        result, _ = ocr(str(image_path))
        if not result:
            return ""
        # result: [[box, text, confidence], ...]
        texts = [item[1] for item in result if len(item) >= 2]
        return " ".join(texts)
    except Exception as e:
        print(f"[OCR] error on {image_path}: {e}", file=sys.stderr)
        return ""


def extract_choice_answer(ocr_text: str) -> str | None:
    """从OCR文本提取选择题答案A/B/C/D。"""
    if not ocr_text:
        return None
    # 常见模式：答案是A、答案：A、解析：A、【答案】A、A. xxx
    patterns = [
        r'答案[：:]\s*([A-D])',
        r'【答案】\s*([A-D])',
        r'^\s*([A-D])\s*[.．、]',
        r'选\s*([A-D])',
        r'正确选项\s*[为是：:]\s*([A-D])',
    ]
    for pat in patterns:
        m = re.search(pat, ocr_text)
        if m:
            return m.group(1)
    # 如果文本只有一个字母A-D
    cleaned = ocr_text.strip().upper()
    if len(cleaned) == 1 and cleaned in "ABCD":
        return cleaned
    # 找第一个独立的A/B/C/D
    for ch in cleaned:
        if ch in "ABCD":
            return ch
    return None


def extract_fill_answer(ocr_text: str) -> tuple[str | None, str]:
    """从OCR文本提取填空题答案，返回(canonical, judge_mode)。"""
    if not ocr_text:
        return None, "manual"
    # 简单提取：去掉"答案"等前缀，取剩余
    text = ocr_text.strip()
    text = re.sub(r'^答案[：:]\s*', '', text)
    text = re.sub(r'^【答案】\s*', '', text)
    text = text.strip()
    if not text:
        return None, "manual"
    # 对于简单的数值/表达式，用normalized_math；复杂的用manual
    if len(text) > 50 or re.search(r'[证明解设]', text):
        return None, "manual"
    return text, "normalized_math"


def process_bank(bank_key: str, dry_run: bool = False) -> dict:
    """处理一个题库的答案结构化。"""
    cfg = BANK_CONFIG[bank_key]
    qpath = cfg['questions']
    data = json.loads(qpath.read_text(encoding='utf-8'))
    book_dir = ROOT / cfg['name']

    stats = {"choice": 0, "fill": 0, "other": 0, "choice_extracted": 0, "fill_extracted": 0, "failed": 0}

    for ch in data.get('chapters', []):
        for q in ch.get('questions', []):
            qtype = q.get('type', '')
            uid = q.get('uid', '')

            if qtype == '选择题':
                stats['choice'] += 1
                answer_ref = q.get('answer_ref')
                if answer_ref:
                    if isinstance(answer_ref, dict):
                        rel = answer_ref.get('cropped', str(answer_ref))
                    else:
                        rel = str(answer_ref)
                    ans_path = book_dir / 'math-bank' / rel
                    text = ocr_image(ans_path)
                    answer = extract_choice_answer(text)
                    if answer:
                        q['answer_structured'] = {
                            'kind': 'choice',
                            'canonical': answer,
                            'aliases': [],
                            'judge_mode': 'choice_exact',
                            'source_ref': rel,
                        }
                        stats['choice_extracted'] += 1
                    else:
                        stats['failed'] += 1
                else:
                    stats['failed'] += 1

            elif qtype == '填空题':
                stats['fill'] += 1
                answer_ref = q.get('answer_ref')
                if answer_ref:
                    if isinstance(answer_ref, dict):
                        rel = answer_ref.get('cropped', str(answer_ref))
                    else:
                        rel = str(answer_ref)
                    ans_path = book_dir / 'math-bank' / rel
                    text = ocr_image(ans_path)
                    canonical, mode = extract_fill_answer(text)
                    if canonical:
                        q['answer_structured'] = {
                            'kind': 'fill',
                            'canonical': canonical,
                            'aliases': [],
                            'judge_mode': mode,
                            'source_ref': rel,
                        }
                        stats['fill_extracted'] += 1
                    else:
                        q['answer_structured'] = {
                            'kind': 'fill',
                            'canonical': None,
                            'aliases': [],
                            'judge_mode': 'manual',
                            'source_ref': rel,
                        }
                        stats['failed'] += 1
                else:
                    stats['failed'] += 1
            else:
                stats['other'] += 1

    if not dry_run:
        write_json_atomic(qpath, data, indent=2)

    print(f"{cfg['name']}: choice={stats['choice']} extracted={stats['choice_extracted']}, "
          f"fill={stats['fill']} extracted={stats['fill_extracted']}, "
          f"other={stats['other']}, failed={stats['failed']}")
    return stats


def main():
    parser = argparse.ArgumentParser(description='提取结构化答案')
    parser.add_argument('--bank', choices=list(BANK_CONFIG.keys()) + ['all'], default='all')
    parser.add_argument('--dry-run', action='store_true', help='只统计不写入')
    args = parser.parse_args()

    banks = list(BANK_CONFIG.keys()) if args.bank == 'all' else [args.bank]
    total = {}
    for bank in banks:
        total[bank] = process_bank(bank, dry_run=args.dry_run)

    print("\n汇总:")
    for bank, s in total.items():
        print(f"  {bank}: {s}")


if __name__ == '__main__':
    main()
