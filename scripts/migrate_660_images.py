#!/usr/bin/env python3
"""Migrate 660 image crops from temp/ to 660题/math-bank/images/.

Backs up questions.json, copies only referenced images, updates image_ref.cropped paths.
Handles both 高数 crops (660_crops_v2) and 线代 crops (660_linear_crops).
"""
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from utils import write_json_atomic

sys.stdout.reconfigure(encoding='utf-8')

ROOT = Path(__file__).resolve().parent.parent
SRC_DIRS = [
    ROOT / 'temp' / '660_crops_v2',
    ROOT / 'temp' / '660_linear_crops',
]
DST_DIR = ROOT / '660题' / 'math-bank' / 'images'
QUESTIONS_PATH = ROOT / '660题' / 'questions.json'
BACKUP_DIR = ROOT / 'temp' / 'backups' / f'migrate_660_images_{datetime.now():%Y%m%d_%H%M%S}'


def find_source(filename):
    """Look for filename in any source dir, also try .png/.jpg variants."""
    base = Path(filename).stem
    candidates = [filename, f'{base}.png', f'{base}.jpg']
    for d in SRC_DIRS:
        for c in candidates:
            p = d / c
            if p.exists():
                return p
    return None


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
            filename = Path(ref['cropped']).name
            src = find_source(filename)
            if src is None:
                missing.append(ref['cropped'])
                continue
            # Preserve actual extension
            dst_name = src.name
            dst = DST_DIR / dst_name
            if not dst.exists():
                shutil.copy2(src, dst)
                copied += 1
            ref['cropped'] = f'images/{dst_name}'
            updated += 1

    write_json_atomic(QUESTIONS_PATH, data, indent=2)

    print(f'Updated {updated} image refs, copied {copied} images to {DST_DIR}')
    if missing:
        print(f'Missing source files: {len(missing)}')
        for p in missing[:10]:
            print(' ', p)
    print(f'Backup at {BACKUP_DIR}')


if __name__ == '__main__':
    main()
