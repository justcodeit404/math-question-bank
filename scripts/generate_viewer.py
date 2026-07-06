#!/usr/bin/env python3
"""Generate math-bank/index.html from the unified template.

Usage:
    python scripts/generate_viewer.py --all
    python scripts/generate_viewer.py --bank 660
"""
import argparse
import shutil
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / 'templates' / 'math-bank.html'

BANKS = {
    '660': ROOT / '660题' / 'math-bank' / 'index.html',
    '880': ROOT / '880题' / 'math-bank' / 'index.html',
    '1000': ROOT / '1000题' / 'math-bank' / 'index.html',
    '大学深埋': ROOT / '大学深埋' / 'math-bank' / 'index.html',
}


def generate(bank, dest):
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(TEMPLATE, dest)
    print(f'Generated {dest}')


def main():
    parser = argparse.ArgumentParser(description='Generate math-bank viewer HTML')
    parser.add_argument('--bank', choices=list(BANKS.keys()) + ['all'],
                        default='all')
    args = parser.parse_args()

    if not TEMPLATE.exists():
        print(f'Template not found: {TEMPLATE}', file=sys.stderr)
        sys.exit(1)

    banks = list(BANKS.keys()) if args.bank == 'all' else [args.bank]
    for bank in banks:
        generate(bank, BANKS[bank])


if __name__ == '__main__':
    main()
