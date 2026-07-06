"""Shared utilities for 660 linear algebra question bank scripts."""
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')

BASE = Path(__file__).resolve().parent.parent / '660题'
PDF_PATH = BASE.parent / '《基础过关660》-线代篇.pdf'
PDF_IMAGES = BASE / 'pdf_images_线代'
QUESTIONS_JSON = BASE / 'questions_线代.json'
DATAJS = BASE / '..' / 'temp' / 'backups' / '660_split_viewers' / 'math-bank_线代' / 'data.js'
IMG_DIR = BASE / '..' / 'temp' / 'backups' / '660_split_viewers' / 'math-bank_线代' / 'images'

# PDF page 4 = printed page 1 (first question page)
PDF_TO_PRINTED_OFFSET = 3

# Chapter ranges from the table of contents (printed page numbers).
# 填空题
FILL_CHAPTER_RANGES = [
    {'printed_start': 1,  'printed_end': 2,  'name': '第一章 行列式'},
    {'printed_start': 3,  'printed_end': 10, 'name': '第二章 矩阵'},
    {'printed_start': 11, 'printed_end': 16, 'name': '第三章 向量'},
    {'printed_start': 17, 'printed_end': 20, 'name': '第四章 线性方程组'},
    {'printed_start': 21, 'printed_end': 26, 'name': '第五章 特征值和特征向量'},
    {'printed_start': 27, 'printed_end': 29, 'name': '第六章 二次型'},
]

# 选择题
CHOICE_CHAPTER_RANGES = [
    {'printed_start': 30, 'printed_end': 32, 'name': '第一章 行列式'},
    {'printed_start': 33, 'printed_end': 45, 'name': '第二章 矩阵'},
    {'printed_start': 46, 'printed_end': 53, 'name': '第三章 向量'},
    {'printed_start': 54, 'printed_end': 58, 'name': '第四章 线性方程组'},
    {'printed_start': 59, 'printed_end': 64, 'name': '第五章 特征值和特征向量'},
    {'printed_start': 65, 'printed_end': 68, 'name': '第六章 二次型'},
]

CHAPTER_RANGES = [
    {**r, 'type': '填空题'} for r in FILL_CHAPTER_RANGES
] + [
    {**r, 'type': '选择题'} for r in CHOICE_CHAPTER_RANGES
]


def pdf_to_printed(pdf_page):
    """Convert PDF page number to printed page number."""
    return pdf_page - PDF_TO_PRINTED_OFFSET


def printed_to_pdf(printed_page):
    return printed_page + PDF_TO_PRINTED_OFFSET


def get_chapter(pdf_page):
    """Return chapter name for a PDF page."""
    printed = pdf_to_printed(pdf_page)
    if printed < 1:
        return None
    for ch in CHAPTER_RANGES:
        if ch['printed_start'] <= printed <= ch['printed_end']:
            return ch['name']
    return None


def get_question_type(pdf_page):
    """Return question type (填空题/选择题) for a PDF page."""
    printed = pdf_to_printed(pdf_page)
    if printed < 1:
        return None
    return '填空题' if printed < 30 else '选择题'


def generate_datajs(questions, output_path=DATAJS):
    """Generate data.js from questions list."""
    from collections import OrderedDict

    chapters = OrderedDict()
    for q in questions:
        ch_name = q.get('chapter', '未分类')
        if ch_name not in chapters:
            chapters[ch_name] = []
        chapters[ch_name].append(q)

    lines = []
    lines.append("const QUESTION_BANK = {")
    lines.append('  title: "数学基础过关660题·数二线代篇",')
    lines.append("  chapters: [")

    for ch_name, qs in chapters.items():
        lines.append("    {")
        lines.append(f'      name: "{ch_name}",')
        lines.append(f"      question_count: {len(qs)},")
        lines.append("      questions: [")
        for q in qs:
            lines.append("        {")
            lines.append(f"          id: {q['id']},")
            lines.append(f"          type: \"{q['type']}\",")
            lines.append(f"          content: \"{q['content'].replace(chr(92), chr(92)+chr(92)).replace('\"', chr(92)+'\"').replace(chr(10), chr(92)+'n')}\",")
            if q.get('options'):
                lines.append("          options: {")
                for k, v in q['options'].items():
                    safe = str(v).replace(chr(92), chr(92)+chr(92)).replace('"', chr(92)+'"').replace(chr(10), chr(92)+'n')
                    lines.append(f'            "{k}": "{safe}",')
                lines.append("          },")
            if q.get('page'):
                lines.append(f"          page: {q['page']},")
            if q.get('printed_page'):
                lines.append(f"          printed_page: {q['printed_page']},")
            if q.get('has_image') and q.get('image_ref', {}).get('cropped'):
                crop = q['image_ref']['cropped']
                page = q.get('page', '')
                lines.append(f"          has_image: true,")
                lines.append("          image_ref: {")
                lines.append(f'            cropped: "{crop}",')
                lines.append(f"            page: {page},")
                lines.append('            note: "自动裁剪的题目区域（660题线代篇）",')
                lines.append("          },")
            lines.append("        },")
        lines.append("      ],")
        lines.append("    },")

    lines.append("  ],")
    lines.append("};")
    lines.append("")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    print(f'Saved: {output_path} ({len(questions)} questions)')
