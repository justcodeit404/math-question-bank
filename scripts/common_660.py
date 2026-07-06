"""Shared utilities for 660 question bank scripts."""
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')

BASE = Path(__file__).resolve().parent.parent / '660题'
PDF_PATH = BASE.parent / '《基础过关660》-高数篇 .pdf'
PDF_IMAGES = BASE / 'pdf_images'
QUESTIONS_JSON = BASE / 'questions.json'
DATAJS = BASE / 'math-bank' / 'data.js'
IMG_DIR = BASE / 'math-bank' / 'images'

# PDF page 16 = printed page 1 (first question page)
PDF_TO_PRINTED_OFFSET = 15

# Chapter ranges from the table of contents (printed page numbers).
# Each entry: (printed_start, printed_end, name, question_type)
# The end page is the start of the next chapter minus one.
CHAPTER_RANGES = [
    # 填空题
    {'printed_start': 1,   'printed_end': 10,  'name': '第一章 函数·极限·连续',      'type': '填空题'},
    {'printed_start': 11,  'printed_end': 20,  'name': '第二章 一元函数微分学',      'type': '填空题'},
    {'printed_start': 21,  'printed_end': 23,  'name': '第三章 一元函数微分学',      'type': '填空题'},  # 微分中值定理
    {'printed_start': 24,  'printed_end': 29,  'name': '第四章 一元函数积分学',      'type': '填空题'},  # 不定积分
    {'printed_start': 30,  'printed_end': 42,  'name': '第四章 一元函数积分学',      'type': '填空题'},  # 定积分与反常积分
    {'printed_start': 43,  'printed_end': 46,  'name': '第四章 一元函数积分学',      'type': '填空题'},  # 定积分的应用
    {'printed_start': 47,  'printed_end': 53,  'name': '第六章 微分方程',            'type': '填空题'},
    {'printed_start': 54,  'printed_end': 61,  'name': '第五章 多元函数微分学',      'type': '填空题'},
    {'printed_start': 62,  'printed_end': 69,  'name': '第五章 二重积分',            'type': '填空题'},
    # 选择题
    {'printed_start': 70,  'printed_end': 83,  'name': '第一章 函数·极限·连续',      'type': '选择题'},
    {'printed_start': 84,  'printed_end': 96,  'name': '第二章 一元函数微分学',      'type': '选择题'},
    {'printed_start': 97,  'printed_end': 103, 'name': '第三章 一元函数微分学',      'type': '选择题'},  # 微分中值定理
    {'printed_start': 104, 'printed_end': 106, 'name': '第四章 一元函数积分学',      'type': '选择题'},  # 不定积分
    {'printed_start': 107, 'printed_end': 120, 'name': '第四章 一元函数积分学',      'type': '选择题'},  # 定积分与反常积分
    {'printed_start': 121, 'printed_end': 125, 'name': '第四章 一元函数积分学',      'type': '选择题'},  # 定积分的应用
    {'printed_start': 126, 'printed_end': 133, 'name': '第六章 微分方程',            'type': '选择题'},
    {'printed_start': 134, 'printed_end': 144, 'name': '第五章 多元函数微分学',      'type': '选择题'},
    {'printed_start': 145, 'printed_end': 999, 'name': '第五章 二重积分',            'type': '选择题'},
]

CHAPTER_PRINT_RANGES = [
    {'name': '第一章 函数·极限·连续', 'printed_start': 1,   'printed_end': 83},
    {'name': '第二章 一元函数微分学', 'printed_start': 84,  'printed_end': 103},
    {'name': '第三章 一元函数微分学', 'printed_start': 104, 'printed_end': 120},
    {'name': '第四章 一元函数积分学', 'printed_start': 121, 'printed_end': 144},
    {'name': '第五章 多元函数微分学', 'printed_start': 145, 'printed_end': 999},
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
    for ch in CHAPTER_PRINT_RANGES:
        if ch['printed_start'] <= printed <= ch['printed_end']:
            return ch['name']
    return None


def get_question_type(pdf_page):
    """Return question type (填空题/选择题) for a PDF page."""
    printed = pdf_to_printed(pdf_page)
    if printed < 1:
        return None
    # The book is split at printed page 70 (fill-in vs choice)
    return '填空题' if printed < 70 else '选择题'


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
    lines.append('  title: "数学基础过关660题·数二高数篇",')
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
                lines.append('            note: "自动裁剪的题目区域（660题）",')
                lines.append("          },")
            lines.append("        },")
        lines.append("      ],")
        lines.append("    },")

    lines.append("  ],")
    lines.append("};")
    lines.append("")

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    print(f'Saved: {output_path} ({len(questions)} questions)')
