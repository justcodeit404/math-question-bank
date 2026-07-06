"""Detect colored question number boxes for 660 linear algebra."""
import json
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

sys.stdout.reconfigure(encoding='utf-8')

PDF_IMAGES = Path('660题/pdf_images_线代')
CROP_DIR = Path('temp/660_linear_crops')
META_PATH = Path('temp/660_linear_question_boxes.json')


def _read_image(image_path):
    pil_img = Image.open(str(image_path)).convert('RGB')
    return cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)


def detect_number_boxes(image_path):
    """Detect solid colored question-number boxes in the left margin."""
    img = _read_image(image_path)
    if img is None:
        return []

    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    h_img, w_img = img.shape[:2]

    # Question number boxes use colored fills; some are pale (S~40).
    # Keep saturation >= 35 to catch pale boxes while staying above gray UI labels.
    mask = cv2.inRange(hsv, np.array([0, 35, 80]), np.array([179, 255, 255]))

    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    candidates = []
    for cnt in contours:
        x, y, w, h = cv2.boundingRect(cnt)
        aspect = w / h
        if x < 20 or x > 180:
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
    return filtered


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
    PDF_IMAGES.mkdir(parents=True, exist_ok=True)
    CROP_DIR.mkdir(parents=True, exist_ok=True)

    all_crops = []
    stats = []
    for img_path in sorted(PDF_IMAGES.glob('page_*.png')):
        m = img_path.stem.split('_')
        if len(m) != 2 or not m[1].isdigit():
            continue
        page_num = int(m[1])
        # Contents: page 1-3; questions: page 4-71 (printed pages 1-68); answers after that.
        if page_num < 4 or page_num > 71:
            continue

        boxes = detect_number_boxes(img_path)
        if boxes:
            stats.append((page_num, len(boxes)))
            crops = crop_questions(img_path, boxes, page_num, CROP_DIR)
            all_crops.extend(crops)

    with open(META_PATH, 'w', encoding='utf-8') as f:
        json.dump(all_crops, f, ensure_ascii=False, indent=2)

    print(f'Total crops: {len(all_crops)} across {len(stats)} pages')
    if stats:
        print(f'Page range: {min(s[0] for s in stats)} - {max(s[0] for s in stats)}')
        print(f'Questions per page min/max: {min(s[1] for s in stats)} / {max(s[1] for s in stats)}')


if __name__ == '__main__':
    main()
