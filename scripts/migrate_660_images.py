#!/usr/bin/env python3
"""Migrate 660 image crops from temp/ to 660题/math-bank/images/.

Backs up questions.json, copies only referenced images, updates image_ref.cropped paths.
"""
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')

ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = ROOT / 'temp' / '660_crops_v2'
DST_DIR = ROOT / '660题' / 'math-bank' / 'images'
QUESTIONS_PATH = ROOT / '660题' / 'questions.json'
BACKUP_DIR = ROOT / 'temp' / 'backups' / f'migrate_660_images_{datetime.now():%Y%m%d_%H%M%S}'


def main():
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copy2(QUESTIONS_PATH, BACKUP_DIR / 'questions.json')

    with open(QUESTIONS_PATH, 'r', encoding='utf-8') as f:
        data = json.load(f)

    copied = 0
    updated = 0
    missing = []
    DST_DIR.mkdir(parents=True, exist_ok=True)

    for ch in data.get('chapters', []):
        for q in ch.get('questions', []):
            ref = q.get('image_ref')
            if not ref or not ref.get('cropped'):
                continue
            old_path = ROOT / ref['cropped'].replace('/', '\\') if '\\' in str(ROOT) else ROOT / ref['cropped']
            # ref is like '../../temp/660_crops_v2/page_016_q1.png'
            rel = Path(ref['cropped'])
            filename = rel.name
            src = SRC_DIR / filename
            dst = DST_DIR / filename
            if not src.exists():
                missing.append(str(src))
                continue
            if not dst.exists():
                shutil.copy2(src, dst)
                copied += 1
            ref['cropped'] = f'images/{filename}'
            updated += 1

    with open(QUESTIONS_PATH, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f'Updated {updated} image refs, copied {copied} images to {DST_DIR}')
    if missing:
        print(f'Missing source files: {len(missing)}')
        for p in missing[:10]:
            print(' ', p)
    print(f'Backup at {BACKUP_DIR}')


if __name__ == '__main__':
    main()
