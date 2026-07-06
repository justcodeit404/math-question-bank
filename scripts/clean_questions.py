"""Clean Unicode artifacts from PyMuPDF text extraction in questions.json."""
import json, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import QUESTIONS_JSON, DATAJS, clean_text, generate_datajs
from utils import write_json_atomic


def main():
    with open(QUESTIONS_JSON, 'r', encoding='utf-8') as f:
        data = json.load(f)

    print(f'Original: {len(data)} questions')

    bad_before = sum(1 for q in data if any(
        '' <= c <= '' or '' <= c <= ''
        for c in q['content']
    ))

    for q in data:
        q['content'] = clean_text(q['content'])
        if q.get('options'):
            q['options'] = {k: clean_text(v) for k, v in q['options'].items()}
        if q.get('sub_questions'):
            q['sub_questions'] = [clean_text(s) for s in q['sub_questions']]

    bad_after = sum(1 for q in data if any(
        '' <= c <= '' or '' <= c <= ''
        for c in q['content']
    ))

    print(f'PUA before: {bad_before}, after: {bad_after}')

    write_json_atomic(QUESTIONS_JSON, data, indent=2)
    print(f'Saved: {QUESTIONS_JSON}')

    generate_datajs(data)


if __name__ == '__main__':
    main()
