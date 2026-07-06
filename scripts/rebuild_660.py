"""Rebuild 660 questions.json / data.js with corrected qnums from page-level lists."""
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common_660 import SubjectContext
from utils import write_json_atomic

ctx = SubjectContext('math')

META_PATH = Path('temp/660_question_boxes_v2.json')
RESULTS_PATH = Path('temp/660_extracted_minimax.json')
PAGE_QNUMS_PATH = Path('temp/660_page_qnums.json')
QUESTIONS_JSON = Path('660题/questions.json')


def fill_missing_page_qnums(page_qnums):
    """Infer None pages from neighbors, since the question numbers are sequential."""
    pages = sorted([int(k) for k in page_qnums.keys() if isinstance(page_qnums[k], list)])
    # First pass: fill by simple interpolation between known pages
    all_pages = sorted([int(k) for k in page_qnums.keys()])
    for p in all_pages:
        if page_qnums.get(str(p)) is None:
            prev_p = max([pp for pp in pages if pp < p], default=None)
            next_p = min([pp for pp in pages if pp > p], default=None)
            if prev_p is None or next_p is None:
                continue
            prev_nums = page_qnums[str(prev_p)]
            next_nums = page_qnums[str(next_p)]
            gap_pages = next_p - prev_p - 1
            gap_nums = next_nums[0] - prev_nums[-1] - 1
            if gap_pages <= 0 or gap_nums < gap_pages:
                continue
            # Distribute missing numbers evenly across missing pages
            missing = list(range(prev_nums[-1] + 1, next_nums[0]))
            # Heuristic: each missing page likely has the same count as neighbors
            counts = []
            for pp in range(prev_p + 1, next_p):
                counts.append(len(page_qnums.get(str(pp), []) or []))
            # If we don't know counts, assume 3 per page
            if not any(counts):
                per_page = round(len(missing) / gap_pages)
                counts = [per_page] * gap_pages
            idx = 0
            for pp, cnt in zip(range(prev_p + 1, next_p), counts):
                if cnt == 0:
                    cnt = 3
                page_qnums[str(pp)] = missing[idx:idx + cnt]
                idx += cnt
    return page_qnums


def main():
    meta = json.loads(META_PATH.read_text(encoding='utf-8'))
    results = json.loads(RESULTS_PATH.read_text(encoding='utf-8'))
    page_qnums = json.loads(PAGE_QNUMS_PATH.read_text(encoding='utf-8'))

    page_qnums = fill_missing_page_qnums(page_qnums)
    write_json_atomic(PAGE_QNUMS_PATH, page_qnums, indent=2)

    results_by_key = {(r['page'], r['index']): r for r in results}

    # Sort meta boxes to align with results order
    meta_sorted = sorted(meta, key=lambda m: (m['page'], m['index']))

    # Assign qnums
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
        # crop path is like "temp\\660_crops_v2\\page_016_q1.png"
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

    write_json_atomic(QUESTIONS_JSON, questions, indent=2)
    print(f'Saved {QUESTIONS_JSON} ({len(questions)} questions)')
    ctx.generate_datajs(questions)


if __name__ == '__main__':
    main()
