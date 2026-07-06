"""Shared utilities for 660 question bank scripts (高数 + 线代)."""
import json
import sys
from collections import OrderedDict
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')

BASE = Path(__file__).resolve().parent.parent / '660题'

CONFIG = {
    'math': {
        'pdf_name': '《基础过关660》-高数篇 .pdf',
        'pdf_images': BASE / 'pdf_images',
        'offset': 15,
        'title': '数学基础过关660题·数二高数篇',
        'fill_threshold': 70,
        'data_js': BASE / 'math-bank' / 'data.js',
        'img_dir': BASE / 'math-bank' / 'images',
        'chapter_ranges': [
            {'name': '第一章 函数·极限·连续', 'printed_start': 1,   'printed_end': 83},
            {'name': '第二章 一元函数微分学', 'printed_start': 84,  'printed_end': 103},
            {'name': '第三章 一元函数微分学', 'printed_start': 104, 'printed_end': 120},
            {'name': '第四章 一元函数积分学', 'printed_start': 121, 'printed_end': 144},
            {'name': '第五章 多元函数微分学', 'printed_start': 145, 'printed_end': 999},
        ],
        'type_ranges': [
            {'printed_start': 1,   'printed_end': 69,  'type': '填空题'},
            {'printed_start': 70,  'printed_end': 999, 'type': '选择题'},
        ],
    },
    'linear': {
        'pdf_name': '《基础过关660》-线代篇.pdf',
        'pdf_images': BASE / 'pdf_images_线代',
        'offset': 3,
        'title': '数学基础过关660题·数二线代篇',
        'fill_threshold': 30,
        'data_js': BASE.parent / 'temp' / 'backups' / '660_split_viewers' / 'math-bank_线代' / 'data.js',
        'img_dir': BASE.parent / 'temp' / 'backups' / '660_split_viewers' / 'math-bank_线代' / 'images',
        'chapter_ranges': [
            {'name': '第一章 行列式',             'printed_start': 1,  'printed_end': 32},
            {'name': '第二章 矩阵',               'printed_start': 33, 'printed_end': 45},
            {'name': '第三章 向量',               'printed_start': 46, 'printed_end': 53},
            {'name': '第四章 线性方程组',         'printed_start': 54, 'printed_end': 58},
            {'name': '第五章 特征值和特征向量',   'printed_start': 59, 'printed_end': 64},
            {'name': '第六章 二次型',             'printed_start': 65, 'printed_end': 68},
        ],
        'type_ranges': [
            {'printed_start': 1,  'printed_end': 29, 'type': '填空题'},
            {'printed_start': 30, 'printed_end': 68, 'type': '选择题'},
        ],
    },
}


class SubjectContext:
    """Runtime context for either 高数 or 线代."""

    def __init__(self, subject):
        if subject not in CONFIG:
            raise ValueError(f"Unknown subject: {subject}; choose from {list(CONFIG)}")
        self.subject = subject
        self.cfg = CONFIG[subject]
        self.pdf_path = BASE.parent / self.cfg['pdf_name']
        self.pdf_images = self.cfg['pdf_images']
        self.data_js = self.cfg['data_js']
        self.img_dir = self.cfg['img_dir']
        self.offset = self.cfg['offset']
        self.title = self.cfg['title']

    def pdf_to_printed(self, pdf_page):
        return pdf_page - self.offset

    def printed_to_pdf(self, printed_page):
        return printed_page + self.offset

    def get_chapter(self, pdf_page):
        printed = self.pdf_to_printed(pdf_page)
        if printed < 1:
            return None
        for ch in self.cfg['chapter_ranges']:
            if ch['printed_start'] <= printed <= ch['printed_end']:
                return ch['name']
        return None

    def get_question_type(self, pdf_page):
        printed = self.pdf_to_printed(pdf_page)
        if printed < 1:
            return None
        for r in self.cfg['type_ranges']:
            if r['printed_start'] <= printed <= r['printed_end']:
                return r['type']
        return None

    def generate_datajs(self, questions, output_path=None):
        """Generate data.js from a flat questions list."""
        if output_path is None:
            output_path = self.data_js

        chapters = OrderedDict()
        for q in questions:
            ch_name = q.get('chapter', '未分类')
            if ch_name not in chapters:
                chapters[ch_name] = []
            chapters[ch_name].append(q)

        lines = []
        lines.append("const QUESTION_BANK = {")
        lines.append(f'  title: "{self.title}",')
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
                    note = q['image_ref'].get('note') or f'自动裁剪的题目区域（660题{"高数篇" if self.subject == "math" else "线代篇"}）'
                    lines.append(f'            note: "{note}",')
                    lines.append("          },")
                lines.append("        },")
            lines.append("      ],")
            lines.append("    },")

        lines.append("  ],")
        lines.append("};")
        lines.append("")

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text('\n'.join(lines), encoding='utf-8')
        print(f'Saved: {output_path} ({len(questions)} questions)')


# Backward-compatible pre-built contexts
math = SubjectContext('math')
linear = SubjectContext('linear')

# Convenience aliases for simple scripts that don't need multiple contexts
def pdf_to_printed(pdf_page): return math.pdf_to_printed(pdf_page)
def printed_to_pdf(printed_page): return math.printed_to_pdf(printed_page)
def get_chapter(pdf_page): return math.get_chapter(pdf_page)
def get_question_type(pdf_page): return math.get_question_type(pdf_page)
def generate_datajs(questions, output_path=None): return math.generate_datajs(questions, output_path)
