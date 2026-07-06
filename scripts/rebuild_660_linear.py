"""Rebuild 660 linear algebra questions.json / data.js with corrected qnums."""
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common_660 import SubjectContext
from utils import write_json_atomic

ctx = SubjectContext('linear')

META_PATH = Path('temp/660_linear_question_boxes.json')
RESULTS_PATH = Path('temp/660_linear_extracted_minimax.json')
QUESTIONS_JSON = Path('660题/questions_线代.json')


def build_page_qnums(meta):
    """Assign sequential qnums 461-660 based on detected boxes per page."""
    from collections import defaultdict
    pages = defaultdict(list)
    for item in meta:
        pages[item['page']].append(item)

    page_qnums = {}
    qnum = 461
    for page in sorted(pages):
        count = len(pages[page])
        page_qnums[str(page)] = list(range(qnum, qnum + count))
        qnum += count
    return page_qnums


def main():
    meta = json.loads(META_PATH.read_text(encoding='utf-8'))
    results = json.loads(RESULTS_PATH.read_text(encoding='utf-8'))

    page_qnums = build_page_qnums(meta)
    print(f'Assigned qnums across {len(page_qnums)} pages, first={page_qnums[str(min(int(k) for k in page_qnums))]}, last={page_qnums[str(max(int(k) for k in page_qnums))]}')

    results_by_key = {(r['page'], r['index']): r for r in results}
    meta_sorted = sorted(meta, key=lambda m: (m['page'], m['index']))

    assigned = 0
    missing = 0
    for m in meta_sorted:
        page = m['page']
        idx = m['index']
        nums = page_qnums.get(str(page))
        if isinstance(nums, list) and 1 <= idx <= len(nums):
            qnum = int(nums[idx - 1])
            key = (page, idx)
            if key in results_by_key:
                results_by_key[key]['qnum'] = qnum
                results_by_key[key]['_crop'] = m['crop']
                assigned += 1
        else:
            missing += 1

    print(f'Assigned qnums: {assigned}, missing: {missing}')

    # Rebuild questions.json
    questions = []
    for r in sorted(results_by_key.values(), key=lambda x: (x['page'], x['index'])):
        if 'error' in r or not r.get('content'):
            continue
        qnum = r.get('qnum')
        if qnum is None:
            continue
        try:
            qnum = int(qnum)
        except (ValueError, TypeError):
            continue
        options = r.get('options') or {}
        normalized = {k: str(options.get(k, '')).strip() for k in ['A', 'B', 'C', 'D']}
        has_options = any(normalized.values())
        crop = r.get('_crop', '')
        if crop:
            crop = crop.replace('\\', '/')
            if crop.startswith('temp/'):
                crop = '../../' + crop
        questions.append({
            'qnum': qnum,
            'content': r['content'],
            'options': normalized if has_options else None,
            'page': r['page'],
            'printed_page': ctx.pdf_to_printed(r['page']),
            'chapter': ctx.get_chapter(r['page']),
            'type': ctx.get_question_type(r['page']),
            'has_image': bool(crop),
            'image_ref': {'cropped': crop} if crop else None,
        })

    for idx, q in enumerate(questions, start=1):
        q['id'] = idx

    QUESTIONS_JSON.parent.mkdir(parents=True, exist_ok=True)
    write_json_atomic(QUESTIONS_JSON, questions, indent=2)
    print(f'Saved {QUESTIONS_JSON} ({len(questions)} questions)')
    ctx.generate_datajs(questions)


if __name__ == '__main__':
    main()
