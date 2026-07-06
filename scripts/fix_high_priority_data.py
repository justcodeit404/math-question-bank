#!/usr/bin/env python3
"""Fix a few high-priority data compliance issues in all question banks.

Backs up the original questions.json before writing.
"""
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

from utils import write_json_atomic

sys.stdout.reconfigure(encoding='utf-8')

ROOT = Path(__file__).resolve().parent.parent
BACKUP_DIR = ROOT / 'temp' / 'backups' / f'fix_high_priority_{datetime.now():%Y%m%d_%H%M%S}'

BANKS = {
    '660': ROOT / '660题' / 'questions.json',
    '880': ROOT / '880题' / 'questions.json',
    '1000': ROOT / '1000题' / 'questions.json',
    '大学深埋': ROOT / '大学深埋' / '做题本（高数）_题目.json',
}


def backup(path: Path):
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    dest = BACKUP_DIR / path.relative_to(ROOT)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, dest)
    return dest


def fix_bank(path: Path, bank: str):
    backup(path)
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    fixed_type = 0
    fixed_qc = 0
    fixed_img_page = 0

    chapters = data.get('chapters', [])
    for ch in chapters:
        if 'question_count' not in ch:
            ch['question_count'] = len(ch.get('questions', []))
            fixed_qc += 1

        for q in ch.get('questions', []):
            if q.get('type') == '解答题':
                q['type'] = '计算题'
                fixed_type += 1

            if bank == '660':
                img_ref = q.get('image_ref')
                if img_ref and img_ref.get('page') is None:
                    page = q.get('page')
                    if page is not None:
                        img_ref['page'] = page
                        fixed_img_page += 1

    write_json_atomic(path, data, indent=2)

    print(f'{bank}: type fixes={fixed_type}, question_count fixes={fixed_qc}, image page fixes={fixed_img_page}')


def main():
    for bank, path in BANKS.items():
        fix_bank(path, bank)
    print(f'Backups saved to {BACKUP_DIR}')


if __name__ == '__main__':
    main()
