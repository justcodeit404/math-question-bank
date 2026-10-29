#!/usr/bin/env python3
"""Generate math-bank/index.html from the unified template.

Usage:
    python scripts/generate_viewer.py --all
    python scripts/generate_viewer.py --bank 660
"""
import argparse
import hashlib
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / 'templates' / 'math-bank.html'
VIEWER_COMMON = ROOT.parent / 'viewer-common'
# 与 tools/sync_viewer_common.ps1 的 $RuntimeFiles 保持一致
VC_RUNTIME_FILES = (
    'pdf-export.js',
    'pdf-lib.min.js',
    'platform-sync.js',
    'question-notes.js',
    'scratch-ink.js',
    'scratch-pad.js',
    'scratch-pad.css',
    'storage.js',
)

BANKS = {
    '660': ROOT / '660题' / 'math-bank' / 'index.html',
    '880': ROOT / '880题' / 'math-bank' / 'index.html',
    '1000': ROOT / '1000题' / 'math-bank' / 'index.html',
    '大学深埋': ROOT / '大学深埋' / 'math-bank' / 'index.html',
}


DATA_SCRIPT_PLACEHOLDER = '<!-- DATA_SCRIPT -->'
VC_VER_PLACEHOLDER = '@VC_VER@'
CROPS_VER_PLACEHOLDER = '@CROPS_VER@'


def viewer_common_ver() -> str:
    """viewer-common 运行时文件内容 hash，作为统一缓存戳（任一文件变则戳变）。"""
    h = hashlib.sha256()
    for name in VC_RUNTIME_FILES:
        h.update((VIEWER_COMMON / name).read_bytes())
    return h.hexdigest()[:8]


def data_script_tag(dest: Path) -> str:
    """引用带上 data.js 内容哈希，避免浏览器（尤其 iPad Safari 启发式缓存）长期沿用旧题库数据。"""
    data_js = dest.with_name('data.js')
    if data_js.exists():
        h = hashlib.sha256(data_js.read_bytes()).hexdigest()[:8]
        return f'<script src="data.js?v={h}"></script>'
    return '<script src="data.js"></script>'


def crops_ver(dest: Path) -> str:
    """answer_crops 文件名+大小 hash，作为答案图统一缓存戳（重裁同名图后自动变）。"""
    h = hashlib.sha256()
    crops = dest.parent / 'answer_crops'
    if crops.exists():
        for f in sorted(crops.glob('*.png')):
            h.update(f.name.encode())
            h.update(str(f.stat().st_size).encode())
    return h.hexdigest()[:8]


def generate(bank, dest):
    dest.parent.mkdir(parents=True, exist_ok=True)
    text = TEMPLATE.read_text(encoding='utf-8')
    text = text.replace(DATA_SCRIPT_PLACEHOLDER, data_script_tag(dest))
    text = text.replace(VC_VER_PLACEHOLDER, viewer_common_ver())
    text = text.replace(CROPS_VER_PLACEHOLDER, crops_ver(dest))
    dest.write_text(text, encoding='utf-8')
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
