"""Extract 660 questions using local OCR (PaddleOCR)."""
import json
import os
import re
import sys
from pathlib import Path

os.environ['FLAGS_use_mkldnn'] = '0'
os.environ['OMP_NUM_THREADS'] = '1'

sys.path.insert(0, str(Path(__file__).resolve().parent))

sys.stdout.reconfigure(encoding='utf-8')

import cv2
import numpy as np
from PIL import Image
from paddleocr import PaddleOCR

from common_660 import (
    BASE, PDF_IMAGES, QUESTIONS_JSON, get_chapter, get_question_type,
    pdf_to_printed, generate_datajs,
)

ocr = PaddleOCR(
    use_angle_cls=True,
    lang='ch',
    show_log=False,
    use_gpu=False,
)


# --- Image processing: detect pink question number boxes ---

def _read_image(image_path):
    pil_img = Image.open(str(image_path)).convert('RGB')
    return cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)


def detect_pink_boxes(image_path):
    img = _read_image(image_path)
    if img is None:
        return []

    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    lower1 = np.array([0, 60, 120])
    upper1 = np.array([10, 255, 255])
    lower2 = np.array([160, 60, 120])
    upper2 = np.array([180, 255, 255])
    mask = cv2.bitwise_or(
        cv2.inRange(hsv, lower1, upper1),
        cv2.inRange(hsv, lower2, upper2),
    )
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    h_img, w_img = img.shape[:2]
    boxes = []
    for cnt in contours:
        x, y, w, h = cv2.boundingRect(cnt)
        if w < 35 or h < 35 or w > 140 or h > 90:
            continue
        aspect = w / h
        if aspect < 1.0 or aspect > 3.0:
            continue
        if x < 30 or x > 250:
            continue
        if y < 50 or y > h_img * 0.85:
            continue
        area = cv2.contourArea(cnt)
        rect_area = w * h
        if rect_area <= 0:
            continue
        if area / rect_area < 0.65:
            continue
        boxes.append((x, y, w, h))

    boxes.sort(key=lambda b: b[1])
    return boxes


def crop_number_box(image_path, box):
    """Crop just the pink number box."""
    img = _read_image(image_path)
    x, y, w, h = box
    margin = 5
    return img[max(0, y - margin):y + h + margin, max(0, x - margin):x + w + margin]


def crop_stem_text(image_path, box):
    """Crop the text to the right of the number box."""
    img = _read_image(image_path)
    x, y, w, h = box
    h_img, w_img = img.shape[:2]
    x1 = x + w + 5
    x2 = min(w_img, w_img - 10)
    y1 = max(0, y - 10)
    y2 = min(h_img, y + h + 20)
    return img[y1:y2, x1:x2]


# --- OCR and text post-processing ---

def recognize_image(np_image, invert=False):
    """Run PaddleOCR on a numpy BGR image."""
    tmp_path = Path('temp/_ocr_tmp.png')
    tmp_path.parent.mkdir(parents=True, exist_ok=True)
    if invert and len(np_image.shape) == 2:
        np_image = cv2.bitwise_not(np_image)
    cv2.imwrite(str(tmp_path), np_image)
    result = ocr.ocr(str(tmp_path.resolve()), cls=True)
    lines = []
    if result and result[0]:
        for line in result[0]:
            if line:
                _, (text, score) = line
                lines.append((text, score))
    return lines


def recognize_number_box(np_image):
    """Recognize white digits on pink background."""
    gray = cv2.cvtColor(np_image, cv2.COLOR_BGR2GRAY)
    _, binary = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY_INV)
    return recognize_image(binary)


IGNORED_PHRASES = [
    '函数 极限 连续', '函数极限连续', '函数 极限', '函数极限',
    '660题', '填空题', '选择题', '答题区', '笔记区', '计算',
    '难度', '目标分', '必做', '答题收获', '核心结论', '易错细节',
    '特例反例', '知识盲区', '考点提示',
]


def clean_ocr_lines(lines):
    """Merge OCR lines and remove decorative UI text."""
    # Sort by vertical position
    lines = sorted(lines, key=lambda item: item[0][1] if isinstance(item[0], (list, tuple)) and len(item[0]) >= 2 else 0)
    texts = [text for text, score in lines]
    full = ' '.join(texts)
    for phrase in IGNORED_PHRASES:
        full = full.replace(phrase, ' ')
    full = re.sub(r'\s+', ' ', full).strip()
    return full


def extract_number(text):
    """Extract leading question number from stem text."""
    m = re.match(r'^\s*(\d+)\s*', text)
    if m:
        return int(m.group(1))
    # Sometimes OCR merges digits: e.g. "12" or "121"
    m = re.match(r'^\s*(\d{1,3})\s*', text)
    return int(m.group(1)) if m else None


def postprocess_math(text):
    """Convert common OCR math fragments to LaTeX-ish strings."""
    # Strip leading number
    text = re.sub(r'^\s*\d+\s*', '', text)

    # Greek letters commonly mis-OCR'd
    text = text.replace('α', '\\alpha ')
    text = text.replace('β', '\\beta ')
    text = text.replace('γ', '\\gamma ')
    text = text.replace('θ', '\\theta ')
    text = text.replace('π', '\\pi ')
    text = text.replace('∞', '\\infty ')

    # Common math operators
    text = text.replace('lim', '\\lim')
    text = text.replace('√', '\\sqrt')
    text = text.replace('≤', '\\leq ')
    text = text.replace('≥', '\\geq ')
    text = text.replace('≠', '\\neq ')
    text = text.replace('×', '\\times ')
    text = text.replace('·', '\\cdot ')

    # Arrows / limits
    text = re.sub(r'x\s*[-—]\s*0\+', r'x \\to 0^{+}', text)
    text = re.sub(r'x\s*[-—]\s*0-', r'x \\to 0^{-}', text)
    text = re.sub(r'x\s*[-—]\s*0', r'x \\to 0', text)
    text = re.sub(r'x\s*[-—]\s*∞', r'x \\to \\infty', text)
    text = re.sub(r'x\s*[-—]\s*\+∞', r'x \\to +\\infty', text)
    text = re.sub(r'n\s*[-—]\s*∞', r'n \\to \\infty', text)

    # Superscripts for simple cases
    text = re.sub(r'([a-zA-Z])²', r'\1^{2}', text)
    text = re.sub(r'([a-zA-Z])³', r'\1^{3}', text)
    text = re.sub(r'([a-zA-Z])ⁿ', r'\1^{n}', text)

    # Subscripts for simple cases
    text = re.sub(r'([a-zA-Z])₀', r'\1_{0}', text)
    text = re.sub(r'([a-zA-Z])₁', r'\1_{1}', text)
    text = re.sub(r'([a-zA-Z])₂', r'\1_{2}', text)
    text = re.sub(r'([a-zA-Z])ₙ', r'\1_{n}', text)

    # Wrap isolated math fragments lightly
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def process_page(image_path, page_num):
    boxes = detect_pink_boxes(image_path)
    questions = []
    for box in boxes:
        # Recognize number box separately for robustness
        num_img = crop_number_box(image_path, box)
        num_lines = recognize_number_box(num_img)
        num_text = clean_ocr_lines(num_lines)
        qnum = extract_number(num_text)

        # Recognize stem text to the right
        stem_img = crop_stem_text(image_path, box)
        stem_lines = recognize_image(stem_img)
        raw_text = clean_ocr_lines(stem_lines)
        if not raw_text:
            continue
        content = postprocess_math(raw_text)
        questions.append({
            'qnum': qnum,
            'content': content,
            'page': page_num,
            'printed_page': pdf_to_printed(page_num),
            'chapter': get_chapter(page_num),
            'type': get_question_type(page_num),
        })
    return questions


def main():
    PDF_IMAGES.mkdir(parents=True, exist_ok=True)
    BASE.mkdir(parents=True, exist_ok=True)

    all_questions = []
    image_paths = sorted(PDF_IMAGES.glob('page_*.png'))
    for i, img_path in enumerate(image_paths):
        m = img_path.stem.split('_')
        if len(m) != 2 or not m[1].isdigit():
            continue
        page_num = int(m[1])
        if page_num < 16:
            continue

        print(f'[{i + 1}/{len(image_paths)}] Page {page_num}')
        questions = process_page(img_path, page_num)
        if questions:
            print(f'  -> {len(questions)} questions')
        all_questions.extend(questions)

    # Sequential IDs
    for idx, q in enumerate(all_questions, start=1):
        q['id'] = idx

    with open(QUESTIONS_JSON, 'w', encoding='utf-8') as f:
        json.dump(all_questions, f, ensure_ascii=False, indent=2)
    print(f'\nSaved {QUESTIONS_JSON} ({len(all_questions)} questions)')

    generate_datajs(all_questions)


if __name__ == '__main__':
    main()
