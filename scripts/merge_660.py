"""Merge 660 高数篇 and 660 线代篇 into a single question bank."""
import json
import sys
from pathlib import Path

from utils import write_json_atomic, write_text_atomic

sys.stdout.reconfigure(encoding='utf-8')

BASE = Path(__file__).resolve().parent.parent / '660题'
QUESTIONS_JSON = BASE / 'questions.json'
DATAJS = BASE / 'math-bank' / 'data.js'


def load_questions(path):
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def merge():
    math = load_questions('660题/questions_高数.json')
    linear = load_questions('660题/questions_线代.json')

    # 高数篇 qnum 1-460，线代篇 461-660；保持原有 qnum，按顺序合并
    combined = math + linear

    # 重新分配全局 id 1-660
    for idx, q in enumerate(combined, start=1):
        q['id'] = idx

    BASE.mkdir(parents=True, exist_ok=True)
    write_json_atomic(QUESTIONS_JSON, combined, indent=2)
    print(f'Saved {QUESTIONS_JSON} ({len(combined)} questions)')

    generate_datajs(combined)


def generate_datajs(questions):
    from collections import OrderedDict

    chapters = OrderedDict()
    for q in questions:
        ch_name = q.get('chapter', '未分类')
        if ch_name not in chapters:
            chapters[ch_name] = []
        chapters[ch_name].append(q)

    lines = []
    lines.append("const QUESTION_BANK = {")
    lines.append('  title: "数学基础过关660题·数二",')
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
                lines.append('            note: "自动裁剪的题目区域（660题合并版）",')
                lines.append("          },")
            lines.append("        },")
        lines.append("      ],")
        lines.append("    },")

    lines.append("  ],")
    lines.append("};")
    lines.append("")

    write_text_atomic(DATAJS, '\n'.join(lines))
    print(f'Saved: {DATAJS} ({len(questions)} questions)')


if __name__ == '__main__':
    merge()
