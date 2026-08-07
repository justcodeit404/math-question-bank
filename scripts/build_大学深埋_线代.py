#!/usr/bin/env python3
"""把大学深埋线代 PDF（一页一题）并入现有高数题库，生成统一 questions.json。"""
import json
import re
import shutil
import sys
from pathlib import Path

import cv2
import fitz
import numpy as np
from PIL import Image
from tqdm import tqdm

sys.path.insert(0, str(Path(__file__).resolve().parent))
from utils import write_json_atomic

ROOT = Path(__file__).resolve().parent.parent
PDF_PATH = ROOT / '大学深埋' / '【横版】27ep线代讲义例题做题本.pdf'
PDF_IMAGES_DIR = ROOT / '大学深埋' / 'pdf_images_线代'
IMG_OUT_DIR = ROOT / '大学深埋' / 'math-bank' / 'images' / '线代'
GAOSHU_JSON = ROOT / '大学深埋' / '做题本（高数）_题目.json'
COMBINED_JSON = ROOT / '大学深埋' / 'questions.json'

DPI = 200
HEADER_CROP = (0.05, 0.02, 0.95, 0.10)   # 顶部标题栏（相对坐标）
CONTENT_CROP = (0.02, 0.10, 0.98, 0.90)  # 正文区域（去掉页眉页脚）


def ensure_cnocr():
    try:
        from cnocr import CnOcr
        return CnOcr()
    except Exception as e:
        print(f'[错误] 无法加载 CnOCR: {e}')
        sys.exit(1)


def render_pdf():
    PDF_IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    doc = fitz.open(str(PDF_PATH))
    print(f'PDF 共 {doc.page_count} 页，渲染到 {PDF_IMAGES_DIR}')
    for i in tqdm(range(doc.page_count), desc='渲染页面'):
        out = PDF_IMAGES_DIR / f'page_{i + 1:03d}.png'
        if out.exists():
            continue
        pix = doc[i].get_pixmap(dpi=DPI)
        pix.save(str(out))
    doc.close()


def _rel_crop(img, box):
    h, w = img.shape[:2]
    x1, y1, x2, y2 = box
    return img[int(h * y1):int(h * y2), int(w * x1):int(w * x2)]


def ocr_text(engine, img):
    """OCR 返回拼接文本。"""
    result = engine.ocr(img)
    lines = []
    for r in result or []:
        text = r.get('text', '').strip() if isinstance(r, dict) else str(r).strip()
        if text:
            lines.append(text)
    return '\n'.join(lines)


def parse_section(header_text):
    """从页眉 OCR 文本解析章节号与名称。"""
    # 示例：ep强化讲义例题 · 1.行列式和矩阵
    m = re.search(r'(\d+)\.\s*([^·\n]+)', header_text)
    if not m:
        return None, None
    num = m.group(1)
    name = m.group(2).strip()
    return num, name


def detect_type(text):
    if re.search(r'[A-D][\.、]', text) or ('选项' in text):
        return '选择题'
    if '证明' in text:
        return '证明题'
    if '填空' in text or '____' in text or '_______' in text:
        return '填空题'
    return '计算题'


def extract_example_id(text):
    m = re.search(r'【例\s*(\d+)】', text)
    if m:
        return f'例{m.group(1)}'
    return None


def crop_content_region(img_path, out_path):
    """按非白像素裁剪正文区域，去掉大量空白。"""
    img = Image.open(img_path)
    w, h = img.size
    # 裁剪掉页眉页脚
    content = img.crop((int(w * CONTENT_CROP[0]), int(h * CONTENT_CROP[1]),
                        int(w * CONTENT_CROP[2]), int(h * CONTENT_CROP[3])))
    np_img = np.array(content)
    # 转为灰度并二值化，找内容包围盒
    if len(np_img.shape) == 3:
        gray = cv2.cvtColor(np_img, cv2.COLOR_RGB2GRAY)
    else:
        gray = np_img
    _, binary = cv2.threshold(gray, 240, 255, cv2.THRESH_BINARY_INV)
    coords = cv2.findNonZero(binary)
    if coords is None:
        content.save(out_path, 'PNG')
        return
    x, y, bw, bh = cv2.boundingRect(coords)
    padding = 20
    x = max(0, x - padding)
    y = max(0, y - padding)
    x2 = min(content.width, x + bw + padding * 2)
    y2 = min(content.height, y + bh + padding * 2)
    cropped = content.crop((x, y, x2, y2))
    cropped.save(out_path, 'PNG')


def build_linear_questions(engine):
    IMG_OUT_DIR.mkdir(parents=True, exist_ok=True)
    paths = sorted(PDF_IMAGES_DIR.glob('page_*.png'))

    chapter_map = {}      # section_num -> chapter name
    pages_by_chapter = {} # chapter -> [(page, q)]
    questions = []

    for p in tqdm(paths, desc='识别线代页面'):
        page_num = int(p.stem.split('_')[1])
        img = np.array(Image.open(p))

        header_img = _rel_crop(img, HEADER_CROP)
        header_text = ocr_text(engine, header_img)
        sec_num, sec_name = parse_section(header_text)
        if sec_name is None:
            sec_name = '未知章节'
            sec_num = '0'
        ch_name = f'线代 · {sec_name}'
        chapter_map[sec_num] = ch_name

        content_img = _rel_crop(img, CONTENT_CROP)
        content_text = ocr_text(engine, content_img)
        content_text = re.sub(r'第\s*\d+\s*页，共\s*\d+\s*页', '', content_text)
        content_text = re.sub(r'ep强化讲义例题[^\n]*', '', content_text)
        content_text = content_text.strip()

        qid = extract_example_id(content_text) or f'例{page_num}'
        qtype = detect_type(content_text)

        # 保存裁剪后的题目图
        rel_img = f'images/线代/page_{page_num:03d}.png'
        out_img = IMG_OUT_DIR / f'page_{page_num:03d}.png'
        crop_content_region(p, out_img)

        q = {
            'uid': f'大学深埋-线代-{qid}-p{page_num}',
            'id': qid,
            'qnum': None,
            'type': qtype,
            'content': content_text or f'{qid}（见原图）',
            'options': None,
            'sub_questions': None,
            'page': page_num,
            'printed_page': None,
            'chapter': ch_name,
            'section': f'{sec_num}.{sec_name}',
            'has_image': True,
            'image_ref': {
                'page': page_num,
                'cropped': rel_img,
                'note': f'线代讲义第{page_num}页例题',
            },
            'answer_ref': None,
            'source': '【横版】27ep线代讲义例题做题本.pdf',
        }
        questions.append(q)
        pages_by_chapter.setdefault(ch_name, []).append(q)

    # 按章节顺序输出
    chapters = []
    seen = []
    for q in questions:
        ch = q['chapter']
        if ch not in seen:
            seen.append(ch)
    for ch in seen:
        qs = pages_by_chapter[ch]
        chapters.append({
            'name': ch,
            'questions': qs,
            'question_count': len(qs),
        })
    return chapters


def main():
    if not PDF_PATH.exists():
        print(f'PDF 不存在: {PDF_PATH}')
        sys.exit(1)

    render_pdf()
    engine = ensure_cnocr()
    linear_chapters = build_linear_questions(engine)

    with open(GAOSHU_JSON, 'r', encoding='utf-8') as f:
        gaoshu_data = json.load(f)

    combined = {
        'schema_version': gaoshu_data.get('schema_version', '1.0'),
        'bank': '大学深埋',
        'title': '大学深埋（高数+线代）',
        'total_pages': max(gaoshu_data.get('total_pages', 0),
                           max((ch['questions'][-1]['page'] for ch in linear_chapters if ch['questions']), default=0)),
        'content_pages': gaoshu_data.get('content_pages', 0) + len(linear_chapters),
        'total_questions': gaoshu_data.get('total_questions', 0) + sum(ch['question_count'] for ch in linear_chapters),
        'chapters': gaoshu_data.get('chapters', []) + linear_chapters,
    }

    write_json_atomic(COMBINED_JSON, combined)
    print(f'已生成 {COMBINED_JSON}')
    print(f'高数 {gaoshu_data.get("total_questions", 0)} 道 + 线代 {sum(ch["question_count"] for ch in linear_chapters)} 道 = {combined["total_questions"]} 道')


if __name__ == '__main__':
    main()
