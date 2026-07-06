#!/usr/bin/env python3
"""Normalize all question banks to the unified schema v1.0.

Reads each bank's questions.json, converts it to the common schema, and writes
it back in-place. Original files are backed up to temp/backups/original_questions/.
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from utils import write_json_atomic

sys.stdout.reconfigure(encoding='utf-8')

ROOT = Path(__file__).resolve().parent.parent

BANKS = {
    '660': {
        'input': ROOT / '660题' / 'questions.json',
        'title': '数学基础过关660题·数二',
        'total_pages': 149,
        'content_pages': 149,
    },
    '880': {
        'input': ROOT / '880题' / 'questions.json',
        'title': '李林880题·数二高数篇',
        'total_pages': 90,
        'content_pages': None,
    },
    '1000': {
        'input': ROOT / '1000题' / 'questions.json',
        'title': '张宇考研数学1000题 数学二',
        'total_pages': 138,
        'content_pages': None,
    },
    '大学深埋': {
        'input': ROOT / '大学深埋' / '做题本（高数）_题目.json',
        'title': '01 27大雪深埋做题本（高数）',
        'total_pages': 159,
        'content_pages': 157,
    },
}


def make_uid(bank, q):
    """Generate a globally unique id for a question."""
    qnum = q.get('qnum')
    raw_id = str(q.get('id', '')).strip()
    chapter = str(q.get('chapter', '')).strip()
    page = q.get('page')

    if bank == '660':
        return f'660-{qnum}'
    if bank == '880':
        return f'880-{raw_id}'
    if bank == '1000':
        return f'1000-{chapter}-{raw_id}'
    # 大学深埋：id 多为“例1/例2”，需要章节+页码区分
    return f'大学深埋-{chapter}-{raw_id}-p{page}'


def normalize_image_ref(ref, bank):
    """Ensure image_ref always has the same shape."""
    if not ref:
        return None
    cropped = ref.get('cropped')
    # 大学深埋的 cropped_images 与 math-bank 同级，viewer 中需用 ../cropped_images/
    if bank == '大学深埋' and cropped and cropped.startswith('cropped_images/'):
        cropped = '../' + cropped
    return {
        'page': ref.get('page'),
        'cropped': cropped,
        'note': ref.get('note'),
        'original_page': ref.get('original_page'),
    }


def normalize_question(bank, q, chapter_name):
    """Convert a single question to the unified schema."""
    raw_id = q.get('id')
    qnum = q.get('qnum')
    if qnum is None:
        # Try to parse a leading number from the id
        m = re.match(r'(\d+)', str(raw_id)) if raw_id is not None else None
        qnum = int(m.group(1)) if m else None

    return {
        'uid': make_uid(bank, {**q, 'chapter': chapter_name, 'qnum': qnum}),
        'id': raw_id,
        'qnum': qnum,
        'type': q.get('type'),
        'content': q.get('content'),
        'options': q.get('options') if q.get('options') else None,
        'sub_questions': q.get('sub_questions') if q.get('sub_questions') else None,
        'page': q.get('page'),
        'printed_page': q.get('printed_page'),
        'chapter': chapter_name,
        'section': q.get('section'),
        'has_image': bool(q.get('has_image', False)),
        'image_ref': normalize_image_ref(q.get('image_ref'), bank),
        'source': BANKS[bank]['title'],
    }


def normalize_bank(bank):
    config = BANKS[bank]
    path = config['input']
    with open(path, encoding='utf-8') as f:
        data = json.load(f)

    chapters = []
    if isinstance(data, list):
        # 660 / 880: flat list, group by chapter
        by_chapter = {}
        for q in data:
            ch_name = q.get('chapter', '未分类')
            by_chapter.setdefault(ch_name, []).append(
                normalize_question(bank, q, ch_name)
            )
        for ch_name, questions in by_chapter.items():
            chapters.append({
                'name': ch_name,
                'question_count': len(questions),
                'questions': questions,
            })
    else:
        # 1000 / 大学深埋: already nested
        for ch in data.get('chapters', []):
            ch_name = ch.get('name', '未分类')
            questions = [
                normalize_question(bank, q, ch_name)
                for q in ch.get('questions', [])
            ]
            chapters.append({
                'name': ch_name,
                'question_count': len(questions),
                'questions': questions,
            })

    total_questions = sum(ch['question_count'] for ch in chapters)

    return {
        'schema_version': '1.0',
        'bank': bank,
        'title': config['title'],
        'total_pages': config['total_pages'],
        'content_pages': config['content_pages'],
        'total_questions': total_questions,
        'chapters': chapters,
    }


def main():
    for bank in BANKS:
        normalized = normalize_bank(bank)
        out_path = BANKS[bank]['input']
        write_json_atomic(out_path, normalized, indent=2)
        print(f'Normalized {bank}: {normalized["total_questions"]} questions, '
              f'{len(normalized["chapters"])} chapters -> {out_path}')


if __name__ == '__main__':
    main()
