#!/usr/bin/env python3
"""Generate math-bank/data.js from a unified schema questions.json.

Usage:
    python scripts/generate_data_js.py --bank 660
    python scripts/generate_data_js.py --bank 880
    python scripts/generate_data_js.py --bank 1000
    python scripts/generate_data_js.py --bank 大学深埋
    python scripts/generate_data_js.py --all
"""
import argparse
import hashlib
import json
import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from utils import write_text_atomic

sys.stdout.reconfigure(encoding='utf-8')

ROOT = Path(__file__).resolve().parent.parent

BANK_CONFIG = {
    '660': {
        'name': '660题',
        'questions': ROOT / '660题' / 'questions.json',
        'data_js': ROOT / '660题' / 'math-bank' / 'data.js',
    },
    '880': {
        'name': '880题',
        'questions': ROOT / '880题' / 'questions.json',
        'data_js': ROOT / '880题' / 'math-bank' / 'data.js',
    },
    '1000': {
        'name': '1000题',
        'questions': ROOT / '1000题' / 'questions.json',
        'data_js': ROOT / '1000题' / 'math-bank' / 'data.js',
    },
    '大学深埋': {
        'name': '大学深埋',
        'questions': ROOT / '大学深埋' / '做题本（高数）_题目.json',
        'data_js': ROOT / '大学深埋' / 'math-bank' / 'data.js',
    },
}

# Fields from the unified question that the viewer needs.
VIEWER_FIELDS = [
    'uid', 'id', 'qnum', 'type', 'content', 'options',
    'sub_questions', 'page', 'printed_page', 'chapter',
    'section', 'has_image', 'image_ref', 'source',
]


def escape_js_str(val):
    """Escape a value for use in a JavaScript string literal."""
    s = str(val)
    s = s.replace('\\', '\\\\')
    s = s.replace('"', '\\"')
    s = s.replace('\n', '\\n')
    s = s.replace('\r', '')
    return s


def js_value(val, indent=0):
    """Serialize a Python value as a JavaScript literal."""
    sp = ' ' * indent
    if val is None:
        return 'null'
    if isinstance(val, bool):
        return 'true' if val else 'false'
    if isinstance(val, (int, float)):
        return str(val)
    if isinstance(val, str):
        return f'"{escape_js_str(val)}"'
    if isinstance(val, (list, tuple)):
        if not val:
            return '[]'
        items = ',\n'.join(f'{sp}  {js_value(item, indent + 2)}' for item in val)
        return f'[\n{items}\n{sp}]'
    if isinstance(val, dict):
        if not val:
            return '{}'
        items = ',\n'.join(
            f'{sp}  {k}: {js_value(v, indent + 2)}'
            for k, v in val.items()
        )
        return f'{{\n{items}\n{sp}}}'
    return json.dumps(val, ensure_ascii=False)


def write_question(q, lines, indent=8):
    """Write a single question object to lines."""
    sp = ' ' * indent
    lines.append(f'{sp}{{')
    for key in VIEWER_FIELDS:
        val = q.get(key)
        if val is None:
            continue
        lines.append(f'{sp}  {key}: {js_value(val, indent + 4)},')
    lines.append(f'{sp}}},')


def generate_data_js(bank_name, questions_path, data_js_path):
    with open(questions_path, encoding='utf-8') as f:
        data = json.load(f)

    lines = []
    lines.append('const QUESTION_BANK = {')
    lines.append(f'  title: "{escape_js_str(data["title"])}",')
    if data.get('total_pages') is not None:
        lines.append(f'  total_pages: {data["total_pages"]},')
    if data.get('content_pages') is not None:
        lines.append(f'  content_pages: {data["content_pages"]},')
    if data.get('total_questions') is not None:
        lines.append(f'  total_questions: {data["total_questions"]},')
    lines.append('  chapters: [')

    for ch in data.get('chapters', []):
        q_count = len(ch.get('questions', []))
        lines.append('    {')
        lines.append(f'      name: "{escape_js_str(ch["name"])}",')
        lines.append(f'      question_count: {q_count},')
        lines.append('      questions: [')
        for q in ch.get('questions', []):
            write_question(q, lines, indent=8)
        lines.append('      ],')
        lines.append('    },')

    lines.append('  ],')
    lines.append('};')
    lines.append('')

    text = '\n'.join(lines)
    write_text_atomic(data_js_path, text)

    # 同步更新 viewer 里的缓存戳，避免浏览器加载旧 data.js
    update_data_js_cache_stamp(data_js_path, text)

    q_count = sum(len(ch.get('questions', [])) for ch in data.get('chapters', []))
    ch_count = len(data.get('chapters', []))
    print(f'Generated {data_js_path}: {len(text)} chars, {q_count} questions, '
          f'{ch_count} chapters')
    return {
        'title': data.get('title', bank_name or ''),
        'total': q_count,
        'chapters': ch_count,
    }


def update_data_js_cache_stamp(data_js_path: Path, text: str):
    """Update the data.js query string in the viewer HTML based on content hash."""
    h = hashlib.sha256(text.encode('utf-8')).hexdigest()[:8]
    stamp = f'data.js?v={h}&t={datetime.now():%Y%m%d%H%M%S}'

    def refresh(path: Path):
        if not path.exists():
            return
        html = path.read_text(encoding='utf-8')
        new_html = re.sub(r'data\.js\?[^"\']*', stamp, html)
        if new_html != html:
            write_text_atomic(path, new_html)
            print(f'  updated cache stamp in {path}')

    refresh(data_js_path.with_name('index.html'))
    refresh(ROOT / 'templates' / 'math-bank.html')


def write_stats_js(stats: dict):
    """生成根目录 stats.js，供首页直接读取，避免 file:// 协议下 fetch 被拦截。"""
    lines = [
        'const BANK_STATS = {',
    ]
    for key, s in stats.items():
        lines.append(f'  "{key}": {{')
        lines.append(f'    title: "{escape_js_str(s["title"])}",')
        lines.append(f'    total: {s["total"]},')
        lines.append(f'    chapters: {s["chapters"]},')
        lines.append('  },')
    lines.append('};')
    lines.append(f'const TOTAL_QUESTIONS = {sum(s["total"] for s in stats.values())};')
    lines.append('')
    stats_js = ROOT / 'stats.js'
    write_text_atomic(stats_js, '\n'.join(lines))
    print(f'Generated {stats_js}')


def main():
    parser = argparse.ArgumentParser(description='Generate math-bank/data.js')
    parser.add_argument('--bank', choices=list(BANK_CONFIG.keys()) + ['all'],
                        default='all')
    args = parser.parse_args()

    banks = list(BANK_CONFIG.keys()) if args.bank == 'all' else [args.bank]
    stats = {}
    for bank in banks:
        cfg = BANK_CONFIG[bank]
        stats[cfg['name']] = generate_data_js(bank, cfg['questions'], cfg['data_js'])

    # 如果只生成单个题库，补齐其余题库统计（读取现有 data.js 或 questions.json）
    for key in BANK_CONFIG:
        cfg = BANK_CONFIG[key]
        if cfg['name'] not in stats:
            data = json.loads(cfg['questions'].read_text(encoding='utf-8'))
            stats[cfg['name']] = {
                'title': data.get('title', ''),
                'total': sum(len(ch.get('questions', [])) for ch in data.get('chapters', [])),
                'chapters': len(data.get('chapters', [])),
            }
    write_stats_js(stats)


if __name__ == '__main__':
    main()
