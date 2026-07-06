#!/usr/bin/env python3
"""
Auto-crop per-question regions from PDF page images.

Heuristic:
  1. Detect question number markers like (1), (2), ... on each PDF page.
  2. Split the page vertically between consecutive markers.
  3. Pair regions with questions on that page (ordered by id).
  4. Save crops to math-bank/crops/ and update questions.json.

Usage:
  python scripts/crop_question_regions.py --book 880题
  python scripts/crop_question_regions.py --book 1000题 --pdf path/to/book.pdf
"""

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

import fitz  # PyMuPDF
from PIL import Image

from utils import write_json_atomic


QNUM_RE = re.compile(r'^[\s\uf000-\uf0ff]*\((\d+)\)')


def pad(n, width=3):
    return str(n).zfill(width)


def detect_markers(page):
    """Return list of (y, number) for question-start markers on a PDF page."""
    markers = []
    for b in page.get_text('blocks'):
        x, y, x2, y2, text = b[:5]
        t = re.sub(r'[\uf000-\uf0ff]', '', text).strip().replace('\n', ' ')
        m = QNUM_RE.match(t)
        if m:
            markers.append((y + (y2 - y) / 2, int(m.group(1)), t[:60]))
    return sorted(markers, key=lambda x: x[0])


def split_regions(markers, page_height, top_pad=10, bottom_pad=4):
    """Given sorted marker y-positions, return list of (y1, y2) regions.

    Each region starts just above its own marker so we don't pull in the
    previous question's content, and ends just above the next marker.
    """
    if not markers:
        return []
    regions = []
    ys = [m[0] for m in markers]
    for i, y in enumerate(ys):
        y1 = max(0, y - top_pad)
        if i == len(ys) - 1:
            y2 = page_height
        else:
            y2 = min(page_height, ys[i + 1] - bottom_pad)
        regions.append((y1, y2))
    return regions


def load_questions(path):
    data = json.loads(path.read_text(encoding='utf-8'))
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and 'chapters' in data:
        flat = []
        for ch in data['chapters']:
            for q in ch.get('questions', []):
                q['_chapter'] = ch.get('name', '')
                flat.append(q)
        return flat
    raise ValueError('questions.json must be a list or {chapters: [...]}')


def save_questions(path, data, original):
    if isinstance(original, list):
        out = data
    else:
        # rebuild chapters structure
        chapters = {}
        for q in data:
            ch_name = q.pop('_chapter', '')
            chapters.setdefault(ch_name, []).append(q)
        out = dict(original)
        out['chapters'] = [
            {'name': name, 'questions': qs}
            for name, qs in chapters.items()
        ]
    write_json_atomic(path, out, indent=2)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--book', default='880题', help='题库目录名')
    p.add_argument('--pdf', help='PDF 路径（默认在书目录下查找 .pdf）')
    p.add_argument('--pad', type=int, default=3, help='页码补零位数')
    p.add_argument('--dry-run', action='store_true', help='只打印，不保存')
    args = p.parse_args()

    root = Path(__file__).resolve().parent.parent
    book_dir = root / args.book
    questions_path = book_dir / 'questions.json'
    out_dir = book_dir / 'math-bank' / 'crops'

    if not questions_path.exists():
        print(f'[错误] 找不到 {questions_path}', file=sys.stderr)
        sys.exit(1)

    if args.pdf:
        pdf_path = Path(args.pdf)
    else:
        pdfs = list(book_dir.glob('*.pdf'))
        if not pdfs:
            print(f'[错误] 在 {book_dir} 找不到 PDF，请用 --pdf 指定', file=sys.stderr)
            sys.exit(1)
        pdf_path = pdfs[0]

    print(f'[信息] 题库: {args.book}')
    print(f'[信息] PDF: {pdf_path}')
    print(f'[信息] 题目文件: {questions_path}')

    original_data = json.loads(questions_path.read_text(encoding='utf-8'))
    questions = load_questions(questions_path)

    # Group by page
    by_page = {}
    for q in questions:
        page = q.get('page')
        if page is None:
            continue
        by_page.setdefault(page, []).append(q)

    pdf = fitz.open(str(pdf_path))
    if not args.dry_run:
        out_dir.mkdir(parents=True, exist_ok=True)

    cropped = 0
    skipped_pages = []

    for page_num in sorted(by_page.keys()):
        page_idx = page_num - 1
        if page_idx < 0 or page_idx >= len(pdf):
            print(f'[跳过] 页码 {page_num} 超出 PDF 范围')
            continue

        pdf_page = pdf[page_idx]
        pdf_w = pdf_page.rect.width
        pdf_h = pdf_page.rect.height

        img_path = book_dir / 'pdf_images' / f'page_{pad(page_num, args.pad)}.png'
        if not img_path.exists():
            print(f'[跳过] 找不到图片 {img_path}')
            continue

        img = Image.open(img_path)
        iw, ih = img.size
        scale = iw / pdf_w

        markers = detect_markers(pdf_page)
        def qid_key(q):
            m = re.search(r'\d+', str(q.get('id', '0')))
            return int(m.group(0)) if m else 0

        page_qs = sorted(by_page[page_num], key=qid_key)

        if not markers:
            skipped_pages.append((page_num, 'no markers'))
            continue
        if len(markers) != len(page_qs):
            skipped_pages.append((page_num, f'{len(markers)} markers vs {len(page_qs)} questions'))
            continue

        regions = split_regions(markers, pdf_h)

        for q, (y1_pdf, y2_pdf) in zip(page_qs, regions):
            y1 = max(0, int(y1_pdf * scale))
            y2 = min(ih, int(y2_pdf * scale))
            x1, x2 = 0, iw
            h = max(1, y2 - y1)
            crop = img.crop((x1, y1, x2, y1 + h))

            qid = str(q.get('id', '?'))
            out_name = f'p{pad(page_num, args.pad)}_q{qid}.png'
            out_path = out_dir / out_name
            rel = f'crops/{out_name}'

            if not args.dry_run:
                crop.save(out_path, optimize=True)
                q.setdefault('image_ref', {})
                q['image_ref']['page'] = page_num
                q['image_ref']['cropped'] = rel
                q['image_ref']['note'] = q['image_ref'].get('note') or '自动裁剪的题目区域'
                q['has_image'] = True
            cropped += 1

    if not args.dry_run:
        backup = questions_path.with_suffix('.json.bak.crop')
        shutil.copy2(questions_path, backup)
        save_questions(questions_path, questions, original_data)
        print(f'[信息] 已备份原文件: {backup}')

    print(f'[完成] 裁剪 {cropped} 道题，跳过 {len(skipped_pages)} 页')
    if skipped_pages:
        for pn, reason in skipped_pages[:20]:
            print(f'  - 第 {pn} 页: {reason}')
        if len(skipped_pages) > 20:
            print(f'  ... 还有 {len(skipped_pages) - 20} 页')


if __name__ == '__main__':
    main()
