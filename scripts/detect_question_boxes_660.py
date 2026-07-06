"""Detect colored question-number boxes for 660 (高数 / 线代)."""
import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

sys.stdout.reconfigure(encoding='utf-8')

CONFIG = {
    'math': {
        'pdf_images': Path('660题/pdf_images'),
        'crop_dir': Path('temp/660_crops_v2'),
        'meta_path': Path('temp/660_question_boxes_v2.json'),
        'page_range': (16, 167),
        'saturation_low': 25,
        'x_max': 260,
        'filter_labels': False,
    },
    'linear': {
        'pdf_images': Path('660题/pdf_images_线代'),
        'crop_dir': Path('temp/660_linear_crops'),
        'meta_path': Path('temp/660_linear_question_boxes.json'),
        'page_range': (4, 71),
        'saturation_low': 35,
        'x_max': 180,
        'filter_labels': True,
    },
}


def _read_image(image_path):
    pil_img = Image.open(str(image_path)).convert('RGB')
    return cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)


def detect_number_boxes(image_path, cfg):
    """Detect solid colored question-number boxes in the left margin."""
    img = _read_image(image_path)
    if img is None:
        return []

    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    h_img, w_img = img.shape[:2]

    mask = cv2.inRange(hsv, np.array([0, cfg['saturation_low'], 80]), np.array([179, 255, 255]))

    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    candidates = []
    for cnt in contours:
        x, y, w, h = cv2.boundingRect(cnt)
        aspect = w / h
        if x < 20 or x > cfg['x_max']:
            continue
        if w < 50 or w > 140:
            continue
        if h < 30 or h > 80:
            continue
        if aspect < 1.0 or aspect > 3.0:
            continue
        if y < 40 or y > h_img * 0.92:
            continue
        area = cv2.contourArea(cnt)
        rect_area = w * h
        if rect_area <= 0:
            continue
        if area / rect_area < 0.5:
            continue
        candidates.append((x, y, w, h))

    candidates.sort(key=lambda b: b[1])
    groups = []
    y_tol = 60
    for b in candidates:
        _, y, _, _ = b
        placed = False
        for g in groups:
            if abs(g[0][1] - y) <= y_tol:
                g.append(b)
                placed = True
                break
        if not placed:
            groups.append([b])

    boxes = [min(g, key=lambda b: b[0]) for g in groups]
    boxes.sort(key=lambda b: b[1])

    if cfg.get('filter_labels'):
        # Drop UI labels that sit directly below a question number box (e.g., 难度条).
        min_gap = 150
        filtered = []
        for b in boxes:
            if not filtered:
                filtered.append(b)
                continue
            _, y, _, h = b
            _, prev_y, _, prev_h = filtered[-1]
            if y - (prev_y + prev_h) >= min_gap:
                filtered.append(b)
        boxes = filtered

    return boxes


def crop_questions(image_path, boxes, page_num, out_dir):
    """Crop each question region from just above its number box to just above the next one."""
    img = _read_image(image_path)
    if img is None or not boxes:
        return []

    out_dir.mkdir(parents=True, exist_ok=True)
    crops = []
    h_img, w_img = img.shape[:2]
    boxes_ext = boxes + [(0, h_img, 0, 0)]

    for i, (x, y, w, h) in enumerate(boxes):
        x1 = max(0, x - 20)
        x2 = min(w_img, w_img - 10)
        y1 = max(0, y - 80)
        next_y = boxes_ext[i + 1][1]
        y2 = min(h_img, next_y - 15)
        if y2 <= y1:
            y2 = min(h_img, y + h + 200)

        crop = img[y1:y2, x1:x2]
        out_path = out_dir / f'page_{page_num:03d}_q{i + 1}.png'
        cv2.imwrite(str(out_path), crop)
        crops.append({
            'page': page_num,
            'index': i + 1,
            'box': [int(x), int(y), int(w), int(h)],
            'crop': str(out_path),
        })

    return crops


def main():
    parser = argparse.ArgumentParser(description='Detect 660 question boxes')
    parser.add_argument('--subject', choices=list(CONFIG.keys()), default='math',
                        help='高数 (math) 或 线代 (linear)')
    args = parser.parse_args()

    cfg = CONFIG[args.subject]
    pdf_images = cfg['pdf_images']
    crop_dir = cfg['crop_dir']
    meta_path = cfg['meta_path']
    page_min, page_max = cfg['page_range']

    pdf_images.mkdir(parents=True, exist_ok=True)
    crop_dir.mkdir(parents=True, exist_ok=True)

    all_crops = []
    stats = []
    for img_path in sorted(pdf_images.glob('page_*.png')):
        m = img_path.stem.split('_')
        if len(m) != 2 or not m[1].isdigit():
            continue
        page_num = int(m[1])
        if page_num < page_min or page_num > page_max:
            continue

        boxes = detect_number_boxes(img_path, cfg)
        if boxes:
            stats.append((page_num, len(boxes)))
            crops = crop_questions(img_path, boxes, page_num, crop_dir)
            all_crops.extend(crops)

    meta_path.parent.mkdir(parents=True, exist_ok=True)
    with open(meta_path, 'w', encoding='utf-8') as f:
        json.dump(all_crops, f, ensure_ascii=False, indent=2)

    print(f'Total crops: {len(all_crops)} across {len(stats)} pages')
    if stats:
        print(f'Page range: {min(s[0] for s in stats)} - {max(s[0] for s in stats)}')
        print(f'Questions per page min/max: {min(s[1] for s in stats)} / {max(s[1] for s in stats)}')


if __name__ == '__main__':
    main()
