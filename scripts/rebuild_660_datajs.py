#!/usr/bin/env python3
"""根据 questions.json 重新生成 660 各 viewer 的 data.js（包含 answer_ref）。"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common_660 import SubjectContext
from utils import write_json_atomic

BASE = Path(__file__).resolve().parent.parent / '660题'
QUESTIONS_PATH = BASE / 'questions.json'

SPLIT_DIR = BASE.parent / 'temp' / 'backups' / '660_split_viewers'


def main():
    with open(QUESTIONS_PATH, 'r', encoding='utf-8') as f:
        data = json.load(f)

    questions = []
    for ch in data.get('chapters', []):
        for q in ch.get('questions', []):
            q.setdefault('chapter', ch.get('name'))
            questions.append(q)

    questions.sort(key=lambda q: q.get('id', q.get('qnum', 0)))

    math_qs = [q for q in questions if q.get('qnum', 0) <= 460]
    linear_qs = [q for q in questions if q.get('qnum', 0) >= 461]

    # 分科 viewer
    math_out = SPLIT_DIR / 'math-bank_高数' / 'data.js'
    linear_out = SPLIT_DIR / 'math-bank_线代' / 'data.js'

    math_ctx = SubjectContext('math')
    math_ctx.generate_datajs(math_qs, output_path=math_out)

    linear_ctx = SubjectContext('linear')
    linear_ctx.generate_datajs(linear_qs, output_path=linear_out)

    # 主 viewer（合并高数 + 线代）
    combined_ctx = SubjectContext('math')
    combined_ctx.title = '数学基础过关660题'
    combined_ctx.generate_datajs(questions)

    print('已更新：')
    print(f'  {combined_ctx.data_js}')
    print(f'  {math_out}')
    print(f'  {linear_out}')


if __name__ == '__main__':
    main()
