"""
Apply image crops to math-bank/images/ and update questions.json
so that image_ref.cropped points at the new file.
"""
import argparse
import json
import sys
from pathlib import Path

from PIL import Image

from utils import write_json_atomic


def pad(n):
    return str(n).zfill(3)


def main():
    parser = argparse.ArgumentParser(description='Crop question figures and update questions.json')
    parser.add_argument('--book', default='1000题', help='题库目录名 (默认: 1000题)')
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parent.parent
    base = project_root / args.book
    out_dir = base / 'math-bank' / 'images'
    out_dir.mkdir(parents=True, exist_ok=True)

    boxes_path = base / 'img_boxes.json'
    questions_path = base / 'questions.json'

    if not boxes_path.exists():
        print(f'missing boxes file: {boxes_path}', file=sys.stderr)
        sys.exit(1)
    if not questions_path.exists():
        print(f'missing questions file: {questions_path}', file=sys.stderr)
        sys.exit(1)

    boxes = json.loads(boxes_path.read_text(encoding='utf-8'))['boxes']
    data = json.loads(questions_path.read_text(encoding='utf-8'))

    updated = 0
    for b in boxes:
        page = b['page']
        qid = b['id']
        src = base / 'pdf_images' / f'page_{pad(page)}.png'
        if not src.exists():
            print(f'missing source: {src}', file=sys.stderr)
            continue
        img = Image.open(src)
        iw, ih = img.size
        # Clamp to image bounds
        x = max(0, min(int(b['x']), iw - 1))
        y = max(0, min(int(b['y']), ih - 1))
        w = max(1, min(int(b['w']), iw - x))
        h = max(1, min(int(b['h']), ih - y))
        crop = img.crop((x, y, x + w, y + h))
        out_name = f'p{pad(page)}_q{qid}.png'
        out_path = out_dir / out_name
        crop.save(out_path, optimize=True)
        rel = f'images/{out_name}'

        # Update questions.json
        for ch in data['chapters']:
            for q in ch['questions']:
                if q['page'] == page and q['id'] == qid:
                    q.setdefault('image_ref', {})
                    q['image_ref']['cropped'] = rel
                    q['image_ref']['page'] = page
                    # Keep existing note
                    updated += 1
                    break

    write_json_atomic(questions_path, data, indent=2)
    print(f'cropped {updated} images, saved to {out_dir}')


if __name__ == '__main__':
    main()
