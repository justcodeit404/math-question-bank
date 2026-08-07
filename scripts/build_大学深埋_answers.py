#!/usr/bin/env python3
"""为大学深埋（高数+线代）题目从强化讲义中裁剪精准答案图。

答案来源：大学深埋/27大雪深埋强化讲义书（扫描版）.pdf
策略：
1. OCR 答案 PDF 的页眉，按章节切分页面范围。
2. 在每个章节内 OCR 检测【例 N】的位置，确定每道题答案区域的
   起始页/起始 y 和结束页/结束 y（下一道题之前或章节结束）。
3. 对单页答案直接裁剪；跨页答案拼接为多页图片（合成一张长图）。
4. 更新 questions.json 中的 answer_ref 字段，并重新生成 data.js。
"""
import json
import re
import sys
import shutil
from pathlib import Path
from collections import defaultdict

import cv2
import fitz
import numpy as np
from PIL import Image
from tqdm import tqdm

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tools"))
from ocr_gpu import create_rapid_ocr  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from utils import write_json_atomic

ROOT = Path(__file__).resolve().parent.parent
PDF_PATH = ROOT / '大学深埋' / '27大雪深埋强化讲义书（扫描版）.pdf'
PDF_IMAGES_DIR = ROOT / '大学深埋' / 'pdf_images_答案'
ANSWER_IMAGES_DIR = ROOT / '大学深埋' / 'math-bank' / 'images' / 'answers'
QUESTIONS_JSON = ROOT / '大学深埋' / 'questions.json'

DPI = 200
HEADER_CROP = (0.10, 0.02, 0.90, 0.10)  # 页眉区域（章节标题）
TOP_CROP = (0.05, 0.02, 0.95, 0.65)     # 上半部分（章节标题+例题号）
EXAMPLE_RE = re.compile(r'【例\s*(\d+)】')

# 做题本章节 -> 答案 PDF 章节页码范围（含端点）
# 基于 OCR 扫描结果人工校验后的边界
ANSWER_RANGES = {
    # 高数
    '函数极限': (11, 20),
    '数列极限': (21, 39),
    '一元函数微分学': (40, 54),
    '方程根与零点问题': (55, 59),
    '中值定理': (60, 75),
    '泰勒公式': (76, 81),
    '凹凸性': (82, 93),
    '不定积分与定积分': (94, 118),
    '积分不等式': (119, 128),
    '多元微分学': (129, 143),
    '二重积分': (144, 165),
    '微分方程': (166, 176),
    '保号性': (177, 187),
    '微积分应用': (188, 204),
    '无穷级数': (205, 230),
    '三重积分': (231, 234),
    '曲线曲面积分': (235, 259),
    # 线代
    '线代 · 行列式和矩阵': (260, 286),
    '线代 · 向量组与方程组': (287, 309),
    '线代 · 相似理论': (310, 330),
    '线代 · 二次型理论': (331, 354),
}

# 已知章节标题（用于章节横幅 OCR 匹配）
KNOWN_CHAPTER_TITLES = [
    '函数极限', '数列极限', '一元函数微分学', '方程根与零点问题',
    '中值定理', '泰勒公式', '凹凸性', '不定积分与定积分',
    '积分不等式', '多元微分学', '二重积分', '微分方程',
    '保号性', '微积分应用', '无穷级数', '三重积分', '曲线曲面积分',
    '行列式和矩阵', '向量组与方程组', '相似理论', '二次型理论',
]

# 分部/部分首页大标题模式
PART_DIVIDER_PATTERNS = [
    re.compile(r'第[一二三四]部分'),
    re.compile(r'PART', re.I),
    re.compile(r'线性代数'),
    re.compile(r'高等数学'),
]

# 知识点总结/小节标题模式（用于在答案区域末尾截断）
SUMMARY_PATTERNS = [
    re.compile(r'知识(?:点|总结|小结)'),
    re.compile(r'总结'),
    re.compile(r'小结'),
    re.compile(r'技巧'),
    re.compile(r'易错点'),
    re.compile(r'注意事项'),
    re.compile(r'题型'),
    re.compile(r'方法总结'),
    re.compile(r'专题框架'),
    re.compile(r'框架'),
    re.compile(r'考点'),
]

# 模块级缓存
_RAPID_OCR = None
_CHAPTER_BANNER_MAP = None
_PART_DIVIDER_MAP = None
_SUMMARY_CACHE = {}


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
    print(f'答案 PDF 共 {doc.page_count} 页，渲染到 {PDF_IMAGES_DIR}')
    for i in tqdm(range(doc.page_count), desc='渲染答案页面'):
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
    result = engine.ocr(img)
    lines = []
    for r in result or []:
        text = r.get('text', '').strip() if isinstance(r, dict) else str(r).strip()
        if text:
            lines.append(text)
    return '\n'.join(lines)


def parse_header(text):
    """从页眉 OCR 文本解析章节名。"""
    # 典型页眉：函数极限 / 一元函数微分学 / 向量组与方程组 / 二次型理论
    # 也可能包含其他文字，只要匹配到已知章节名即可
    known_chapters = [
        '函数极限', '数列极限', '一元函数微分学', '方程根与零点问题',
        '中值定理', '泰勒公式', '凹凸性', '不定积分与定积分',
        '积分不等式', '多元微分学', '二重积分', '微分方程',
        '保号性', '微积分应用', '无穷级数', '三重积分', '曲线曲面积分',
        '行列式和矩阵', '向量组与方程组', '相似理论', '二次型理论',
    ]
    for ch in known_chapters:
        if ch in text:
            return ch
    return None


def scan_headers(engine):
    """OCR 所有页面页眉，返回 page -> chapter。"""
    paths = sorted(PDF_IMAGES_DIR.glob('page_*.png'))
    page_chapter = {}
    for p in tqdm(paths, desc='识别页眉章节'):
        page_num = int(p.stem.split('_')[1])
        img = np.array(Image.open(p))
        header_img = _rel_crop(img, HEADER_CROP)
        text = ocr_text(engine, header_img)
        ch = parse_header(text)
        page_chapter[page_num] = ch
    return page_chapter


def infer_chapter_ranges(page_chapter):
    """根据页眉识别结果推断每章的页码范围。"""
    ranges = []
    current_ch = None
    start = None
    max_page = max(page_chapter.keys())
    for page in sorted(page_chapter.keys()):
        ch = page_chapter[page]
        if ch != current_ch:
            if current_ch is not None and start is not None:
                ranges.append((current_ch, start, page - 1))
            current_ch = ch
            start = page
    if current_ch is not None and start is not None:
        ranges.append((current_ch, start, max_page))
    return ranges


def scan_top_regions(engine):
    """OCR 所有页面的上半部分，保存文本和检测到的例题号。"""
    paths = sorted(PDF_IMAGES_DIR.glob('page_*.png'))
    records = {}
    for p in tqdm(paths, desc='识别页面例题'):
        page_num = int(p.stem.split('_')[1])
        img = np.array(Image.open(p))
        top_img = _rel_crop(img, TOP_CROP)
        text = ocr_text(engine, top_img)
        examples = [int(m) for m in EXAMPLE_RE.findall(text)]
        records[page_num] = {
            'text': text,
            'examples': examples,
        }
    return records


def save_top_scan(records):
    out = ROOT / '大学深埋' / 'answer_page_texts.json'
    write_json_atomic(out, {
        'pages': {str(k): v for k, v in records.items()},
    })
    print(f'已保存 {out}')


def detect_colored_example_boxes(img):
    """检测彩色背景例题框，返回每个框的 (x, y, w, h)（像素坐标）。

    大学深埋答案册里部分例题号（如【例13】）印在淡紫/粉色底框上，
    常规 OCR 会漏检，用 HSV 颜色阈值把底框先框出来再单独识别。
    """
    hsv = cv2.cvtColor(img, cv2.COLOR_RGB2HSV)
    # 淡紫/粉色背景： hue 在紫-品红区间，饱和度低、亮度高
    lower = np.array([120, 10, 200])
    upper = np.array([180, 80, 255])
    mask = cv2.inRange(hsv, lower, upper)
    kernel = np.ones((5, 5), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    h, w = img.shape[:2]
    boxes = []
    for cnt in contours:
        x, y, bw, bh = cv2.boundingRect(cnt)
        # 过滤：例题框横向较长、高度适中，且不在页眉
        if bw > 150 and 30 < bh < 400 and y > h * 0.15:
            boxes.append((x, y, bw, bh))
    return boxes


def ocr_colored_box_marker(img, x, y, bw, bh):
    """对彩色例题框左上角做 OCR，返回识别到的例题数字或 None。"""
    crop = img[y:y + bh, x:min(x + 220, x + bw)]
    hsv = cv2.cvtColor(crop, cv2.COLOR_RGB2HSV)
    # 把紫/品红文字提取成黑字白底，提高 OCR 稳定性
    lower = np.array([120, 30, 30])
    upper = np.array([180, 255, 220])
    mask = cv2.inRange(hsv, lower, upper)
    proc = np.ones_like(crop) * 255
    proc[mask == 255] = [0, 0, 0]
    result = _rapid_ocr()(proc)
    if not result or not result[0]:
        return None
    text = ' '.join(r[1] for r in result[0])
    nums = re.findall(r'\d+', text)
    return int(nums[0]) if nums else None


def scan_colored_example_positions():
    """用颜色+OCR 扫描所有页面的彩色例题框，补充常规 OCR 漏检。"""
    paths = sorted(PDF_IMAGES_DIR.glob('page_*.png'))
    positions = []
    for p in tqdm(paths, desc='彩色例题框补检'):
        page_num = int(p.stem.split('_')[1])
        img = np.array(Image.open(p))
        h, w = img.shape[:2]
        for (x, y, bw, bh) in detect_colored_example_boxes(img):
            ex_num = ocr_colored_box_marker(img, x, y, bw, bh)
            if ex_num is not None and 1 <= ex_num <= 200:
                positions.append((page_num, ex_num, y / h))
    return positions


def scan_example_positions(engine):
    """扫描所有页面，返回每个【例 N】出现的页面和 y 坐标（相对值）。

    先用常规 OCR 识别；再对彩色背景例题框做补检，合并去重。
    """
    paths = sorted(PDF_IMAGES_DIR.glob('page_*.png'))
    seen = set()
    positions = []  # [(page, example_num, y_rel), ...]
    for p in tqdm(paths, desc='定位例题坐标'):
        page_num = int(p.stem.split('_')[1])
        img = np.array(Image.open(p))
        h, w = img.shape[:2]
        result = engine.ocr(img)
        for r in result or []:
            text = r.get('text', '').strip() if isinstance(r, dict) else str(r).strip()
            m = EXAMPLE_RE.search(text)
            if not m:
                continue
            ex_num = int(m.group(1))
            pos = r.get('position')
            if pos is None:
                continue
            y = int(pos[:, 1].min())  # 取文本块顶部 y
            key = (page_num, ex_num)
            if key not in seen:
                seen.add(key)
                positions.append((page_num, ex_num, y / h))

    # 补充彩色背景例题框
    for page_num, ex_num, y_rel in scan_colored_example_positions():
        key = (page_num, ex_num)
        if key not in seen:
            seen.add(key)
            positions.append((page_num, ex_num, y_rel))
    return positions


def save_example_positions(positions):
    out = ROOT / '大学深埋' / 'answer_example_positions.json'
    write_json_atomic(out, {
        'positions': [{'page': p, 'example': e, 'y': round(y, 4)} for p, e, y in positions],
    })
    print(f'已保存 {out}')


def main_example_positions():
    engine = ensure_cnocr()
    positions = scan_example_positions(engine)
    save_example_positions(positions)


def load_example_positions():
    path = ROOT / '大学深埋' / 'answer_example_positions.json'
    data = json.loads(path.read_text(encoding='utf-8'))
    return data['positions']


def load_page_text_blocks():
    """加载每页文本块 y 坐标，用于修正答案区域结束位置。"""
    path = ROOT / '大学深埋' / 'answer_page_text_blocks.json'
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding='utf-8'))
    return data.get('blocks')


PAGE_TEXT_BLOCKS = load_page_text_blocks()


def load_page_chapter_map():
    """加载 header OCR 得到的 page -> chapter 映射。"""
    path = ROOT / '大学深埋' / 'answer_page_chapters.json'
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding='utf-8'))
    return {int(k): v for k, v in data.get('page_chapter', {}).items()}


PAGE_CHAPTER_MAP = load_page_chapter_map()


def load_page_top_texts():
    """加载页面顶部区域 OCR 文本（answer_page_texts.json）。"""
    path = ROOT / '大学深埋' / 'answer_page_texts.json'
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding='utf-8'))
    return {int(k): v.get('text', '') for k, v in data.get('pages', {}).items()}


PAGE_TOP_TEXTS = load_page_top_texts()


def _simplified_chapter(ch_name):
    """把 questions.json 中的章节名转成 header OCR 里的简化名。"""
    return ch_name.replace('线代 · ', '')


def _top_text_contains_other_chapter(page, ch_name):
    """页面顶部 OCR 文本是否出现非当前章节的已知章节名。

    用于处理 header OCR 漏检的跨章过渡页（如函数极限末页顶部实际已
    是「数列极限·专题框架」内容，但页眉仍被识别为当前章）。
    """
    text = (PAGE_TOP_TEXTS or {}).get(page, '')
    if not text:
        return False
    simplified = _simplified_chapter(ch_name)
    for title in KNOWN_CHAPTER_TITLES:
        if title != simplified and title in text:
            return True
    return False


def _is_page_blank_by_image(page):
    """用图像像素判断页面是否基本空白（用于 text blocks 缺失时）。"""
    try:
        img = np.array(Image.open(PDF_IMAGES_DIR / f'page_{page:03d}.png'))
    except Exception:
        return False
    h, w = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
    # 只判断中间区域，避免边框噪声
    crop = gray[int(h * 0.12):int(h * 0.92), int(w * 0.12):int(w * 0.88)]
    non_white = np.sum(crop < 250)
    total = crop.size
    return non_white / total < 0.001


def content_end_y(page, start_y_rel):
    """根据页面文本块位置，找到从 start_y_rel 开始的内容实际结束 y 坐标。

    策略：找出页面中从 start_y_rel 开始最后一个"有意义"的文本块，
    若其下方存在大片空白（大于页面高度的 18%），则裁到该文本块底部；
    否则保留到原结束位置（由调用方取 min）。
    """
    blocks = (PAGE_TEXT_BLOCKS or {}).get(str(page))
    if not blocks:
        # 没有文本块数据时，用图像判断是否为空白页
        return 0.0 if _is_page_blank_by_image(page) else 1.0

    filtered = [b for b in blocks if b['y_min'] >= start_y_rel - 0.02]
    if not filtered:
        # start_y 之后没有文本块，页面剩余部分空白
        return start_y_rel

    filtered.sort(key=lambda b: b['y_min'])
    # 加入虚拟页底块，以便捕捉"内容到大片空白"的边界
    filtered.append({'y_min': 1.0, 'y_max': 1.0})

    max_gap = 0.0
    cut_y = 1.0
    for i in range(1, len(filtered)):
        prev_bottom = filtered[i - 1]['y_max']
        cur_top = filtered[i]['y_min']
        gap = cur_top - prev_bottom
        # 只考虑页面中下部之后的空白（避免误切页眉）
        if prev_bottom >= 0.30 and gap > max_gap:
            max_gap = gap
            cut_y = prev_bottom

    # 空白阈值：页面高度的 18% 左右
    if max_gap >= 0.18:
        return min(1.0, cut_y + 0.03)

    # 没有大空白：保留到最后一个真实文本块底部 + margin
    last_real = filtered[-2]
    return min(1.0, last_real['y_max'] + 0.03)


def _rapid_ocr():
    global _RAPID_OCR
    if _RAPID_OCR is None:
        _RAPID_OCR, _ = create_rapid_ocr()
    return _RAPID_OCR


def _detect_chapter_banner_on_page(page):
    """实际检测单页是否有章节大标题横幅，返回 (y_rel 或 None)。"""
    img = np.array(Image.open(PDF_IMAGES_DIR / f'page_{page:03d}.png'))
    h, w = img.shape[:2]
    hsv = cv2.cvtColor(img, cv2.COLOR_RGB2HSV)
    # 淡紫/粉色章节横幅，与例题框颜色相近但尺寸更大
    lower = np.array([120, 10, 200])
    upper = np.array([180, 80, 255])
    mask = cv2.inRange(hsv, lower, upper)
    kernel = np.ones((5, 5), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    best_y = None
    for cnt in contours:
        x, y, bw, bh = cv2.boundingRect(cnt)
        # 章节横幅：很宽（>0.65 页面宽度）、有一定高度、不在页眉
        if bw < w * 0.65 or bh < 50 or y < h * 0.12:
            continue
        crop = img[y:y + bh, x:x + bw]
        result = _rapid_ocr()(crop)
        if not result or not result[0]:
            continue
        text = ' '.join(r[1] for r in result[0])
        # 清洗常见 OCR 噪声
        clean = text.replace(' ', '').replace('·', '').replace('•', '')
        for title in KNOWN_CHAPTER_TITLES:
            if title in clean or title in text:
                rel_y = y / h
                if best_y is None or rel_y < best_y:
                    best_y = rel_y
                break
    return best_y


def _detect_part_divider_on_page(page):
    """检测单页是否有分部/部分大首页标题，返回其顶部 y_rel 或 None。

    这类页面没有淡紫章节横幅，而是直接出现「第二部分」「线性代数」等
    大字标题。这类标题只分布在上半页的两条窄带：
      - 顶部 0.05~0.20：PART / 第一部分 / 第二部分
      - 中部 0.35~0.55：线性代数 / 高等数学
    分两条窄带 OCR，避免扫描整页上半部分。
    """
    img = np.array(Image.open(PDF_IMAGES_DIR / f'page_{page:03d}.png'))
    h, w = img.shape[:2]
    best_y = None

    strips = [
        (0.05, 0.20),  # 顶部：PART / 第 N 部分
        (0.35, 0.55),  # 中部：线性代数 / 高等数学
    ]
    for y1, y2 in strips:
        crop = img[int(h * y1):int(h * y2), :]
        result = _rapid_ocr()(crop)
        if not result or not result[0]:
            continue
        for r in result[0]:
            box, text, score = r
            y_min = (min(p[1] for p in box) + int(h * y1)) / h
            clean = text.replace(' ', '').replace('·', '').replace('•', '')
            for pat in PART_DIVIDER_PATTERNS:
                if pat.search(clean) or pat.search(text):
                    if best_y is None or y_min < best_y:
                        best_y = y_min
                    break
    return best_y


def precompute_chapter_banners():
    """预计算章节边界附近的章节横幅位置，避免在 refine_span_end 中反复 OCR。"""
    global _CHAPTER_BANNER_MAP
    if _CHAPTER_BANNER_MAP is not None:
        return _CHAPTER_BANNER_MAP

    # 章节首页横幅只可能出现在章节交界处；按已知范围取每章末尾前后窗口
    max_page = max(int(p.stem.split('_')[1]) for p in PDF_IMAGES_DIR.glob('page_*.png'))
    pages_to_check = set()
    for ch, (start, end) in ANSWER_RANGES.items():
        # 上一章末尾可能跨页，下一章首页也可能被裁进来；
        # refine_span_end 会扫到 end+3，所以横幅预计算也要覆盖到。
        pages_to_check.update(range(max(1, end - 2), min(max_page, end + 5) + 1))
        pages_to_check.update(range(max(1, start - 1), min(max_page, start + 2) + 1))

    _CHAPTER_BANNER_MAP = {p: None for p in range(1, max_page + 1)}
    for page_num in tqdm(sorted(pages_to_check), desc='预检测章节横幅'):
        _CHAPTER_BANNER_MAP[page_num] = _detect_chapter_banner_on_page(page_num)
    return _CHAPTER_BANNER_MAP


def detect_chapter_banner(page, start_y_rel=0.0):
    """返回页面中 start_y_rel 以下最近的章节大标题横幅或分部首页顶部 y 坐标。"""
    global _PART_DIVIDER_MAP
    if _PART_DIVIDER_MAP is None:
        _PART_DIVIDER_MAP = {}

    banner_y = (_CHAPTER_BANNER_MAP or {}).get(page)
    if banner_y is not None and banner_y < start_y_rel + 0.02:
        banner_y = None

    # 分部首页只在跨章扫描时才可能出现，按需检测并缓存
    if page not in _PART_DIVIDER_MAP:
        _PART_DIVIDER_MAP[page] = _detect_part_divider_on_page(page)
    divider_y = _PART_DIVIDER_MAP[page]
    if divider_y is not None and divider_y < start_y_rel + 0.02:
        divider_y = None

    candidates = [y for y in (banner_y, divider_y) if y is not None]
    return min(candidates) if candidates else None


def find_summary_boundary(page, start_y_rel=0.0):
    """OCR 检测页面中是否出现知识点总结/小节标题，返回其顶部 y 坐标。"""
    cache_key = (page, round(start_y_rel, 3))
    if cache_key in _SUMMARY_CACHE:
        return _SUMMARY_CACHE[cache_key]

    img = np.array(Image.open(PDF_IMAGES_DIR / f'page_{page:03d}.png'))
    h, w = img.shape[:2]
    result = _rapid_ocr()(img)
    if not result or not result[0]:
        _SUMMARY_CACHE[cache_key] = None
        return None
    matches = []
    for r in result[0]:
        box, text, score = r
        y_min = min(p[1] for p in box) / h
        y_max = max(p[1] for p in box) / h
        if y_min < start_y_rel:
            continue
        # 排除答案自身的【解析】/【注】
        if text.startswith('【解析】') or text.startswith('【注'):
            continue
        for pat in SUMMARY_PATTERNS:
            if pat.search(text.strip()):
                matches.append((y_min, y_max, text))
                break
    if not matches:
        _SUMMARY_CACHE[cache_key] = None
        return None
    # 取最靠上的匹配
    matches.sort()
    _SUMMARY_CACHE[cache_key] = matches[0][0]
    return matches[0][0]


def build_answer_index(positions):
    """按章节分组例题位置，返回 {chapter: {example: [(page, y), ...]}}。"""
    index = defaultdict(lambda: defaultdict(list))
    for p in positions:
        page, ex, y = p['page'], p['example'], p['y']
        for ch, (start, end) in ANSWER_RANGES.items():
            if start <= page <= end:
                index[ch][ex].append((page, y))
                break
    return index


def crop_answer_image(start_page, start_y, end_page, end_y, out_path):
    """裁剪并拼接答案区域为一张长图。"""
    crops = []
    for page in range(start_page, end_page + 1):
        img = Image.open(PDF_IMAGES_DIR / f'page_{page:03d}.png')
        w, h = img.size
        if page == start_page and page == end_page:
            crop = img.crop((0, int(h * start_y), w, int(h * end_y)))
        elif page == start_page:
            crop = img.crop((0, int(h * start_y), w, h))
        elif page == end_page:
            crop = img.crop((0, 0, w, int(h * end_y)))
        else:
            crop = img
        crops.append(crop)

    if not crops:
        return False
    total_h = sum(c.height for c in crops)
    max_w = max(c.width for c in crops)
    canvas = Image.new('RGB', (max_w, total_h), (255, 255, 255))
    y_off = 0
    for c in crops:
        canvas.paste(c, (0, y_off))
        y_off += c.height
    canvas.save(out_path, 'PNG')
    return True


def build_example_spans(ex_index, rng, ch_name, expected_examples=None):
    """根据检测到的例题位置，为每个例题号生成答案区域（含插值填充缺失）。

    expected_examples: 该章节题目中实际出现的例题号集合，用于把未检测到的
    尾部例题也外延到章节末尾。

    注意：答案册中的例题顺序不一定与做题本中的例题号顺序一致（如例27
    之后可能是例15），因此按答案册中的实际出现位置（page, y）找下一道
    例题，而不是按例题号大小。
    """
    detected = sorted(ex_index.keys())
    if not detected:
        return {}
    start_page, end_page = rng

    # 所有检测到的例题位置按 (page, y) 排序
    sorted_positions = sorted(
        (page, y, ex) for ex in detected for page, y in ex_index[ex]
    )

    spans = {}
    # 先为检测到的例题号生成区域
    for ex in detected:
        sp, sy = min(ex_index[ex], key=lambda x: (x[0], x[1]))
        # 找在 (sp, sy) 之后的下一个不同例题的位置
        ep, ey = end_page, 1.0
        for page, y, other_ex in sorted_positions:
            if other_ex == ex:
                continue
            if page > sp or (page == sp and y > sy):
                ep, ey = page, y
                break
        spans[ex] = (sp, sy, ep, ey)

    # 再为缺失的例题号插值：按做题本中的例题号顺序，复用前后检测题的区域
    max_ex = max(detected + list(expected_examples or []) + [0])
    all_examples = set(range(1, max_ex + 1))
    for ex in sorted(all_examples):
        if ex in spans:
            continue
        prev = max((d for d in detected if d < ex), default=None)
        nxt = min((d for d in detected if d > ex), default=None)
        if prev is not None and nxt is not None:
            sp, sy, _, _ = spans[prev]
            ep, ey = min(ex_index[nxt], key=lambda x: (x[0], x[1]))
        elif prev is not None:
            sp, sy, _, _ = spans[prev]
            ep, ey = end_page, 1.0
        elif nxt is not None:
            sp, sy = start_page, 0.0
            ep, ey = min(ex_index[nxt], key=lambda x: (x[0], x[1]))
        else:
            continue
        spans[ex] = (sp, sy, ep, ey)

    # 用页面实际内容结束位置收紧结束边界，避免最后一题拖到章节末尾，
    # 也避免缺失例题号导致把无关的后续页面裁进来。
    if PAGE_TEXT_BLOCKS:
        adjusted = {}
        for ex, (sp, sy, ep, ey) in spans.items():
            nsp, nsy, nep, ney = refine_span_end(sp, sy, ep, ey, end_page, ch_name)
            adjusted[ex] = (nsp, nsy, nep, ney)
        spans = adjusted

    return spans


def refine_span_end(sp, sy, ep, ey, chapter_end_page, ch_name):
    """逐页扫描，找到内容实际结束的位置。

    策略：
    1. 从第二页开始，若某页的内容在页底之前明显结束（结束 y < 0.88），
       则认为答案在该页结束。
    2. 若页面被内容填满（结束 y >= 0.88），进一步 OCR 检测是否出现
       知识点总结/小节标题或下一章大标题横幅；若出现，在标题处截断。
    3. 若 header OCR 显示当前页已属于其他章节，直接回退到上一页内容末尾，
       避免把下一章内容包进来。
    4. 章节最后一题若拖到末尾空白页，回退到最后有实质内容的页面。

    这样能避免把章节末尾的空白页、下一章内容或章节总结裁进来。
    """
    scan_end = max(ep, chapter_end_page + 3)
    last_content_page = sp
    last_content_end = 1.0  # 第一页默认到页底，继续到下一页
    simplified = _simplified_chapter(ch_name)

    for page in range(sp, scan_end + 1):
        start_y = sy if page == sp else 0.0
        page_end = content_end_y(page, start_y)

        # 单页答案
        if page == sp and page == ep:
            return sp, sy, ep, max(sy + 0.05, min(ey, page_end))

        # 跨页答案的第一页：通常继续到下一页
        if page == sp:
            continue

        # header OCR 识别为其他章节：硬边界
        mapped = PAGE_CHAPTER_MAP.get(page)
        if mapped and mapped != simplified:
            # 若上一页顶部已出现其他章节名（header OCR 漏检的过渡页），
            # 继续回退一页，避免把过渡页包进来
            if _top_text_contains_other_chapter(page - 1, ch_name):
                return sp, sy, page - 2, content_end_y(page - 2, 0.0)
            return sp, sy, page - 1, content_end_y(page - 1, 0.0)

        # 检测知识点总结/小节标题，在其上方截断
        summary_y = find_summary_boundary(page, start_y)
        if summary_y is not None and start_y + 0.05 < summary_y < ey:
            if summary_y < 0.15:
                # 当前页是总结页/下一章首页，回到上一页内容末尾
                return sp, sy, page - 1, content_end_y(page - 1, 0.0)
            return sp, sy, page, summary_y

        # 检测下一章大标题横幅（章节首页），必须在横幅处截断
        banner_y = detect_chapter_banner(page, start_y)
        if banner_y is not None and start_y + 0.05 < banner_y < ey:
            if banner_y < 0.15:
                # 当前页是下一章首页，回到上一页内容末尾
                return sp, sy, page - 1, content_end_y(page - 1, 0.0)
            return sp, sy, page, banner_y

        # 更新最后有实质内容的页面（用于章节末尾空白页回退）
        if page_end > 0.05:
            last_content_page = page
            last_content_end = page_end

        # 已经超过章节末尾，且后续连续空白：回退到最后内容页
        if page > chapter_end_page and page_end <= 0.05:
            following_blank = True
            for next_page in range(page + 1, min(page + 4, scan_end + 1)):
                if content_end_y(next_page, 0.0) > 0.05:
                    following_blank = False
                    break
            if following_blank:
                return sp, sy, last_content_page, last_content_end

        # 到达原始结束页：用实际内容结束位置收紧
        if page == ep:
            if page_end < 0.88:
                # 原始结束页基本空白，回退到最后有内容的页面
                if page_end <= 0.05:
                    return sp, sy, last_content_page, last_content_end
                return sp, sy, page, page_end
            return sp, sy, ep, min(ey, page_end)

    # 兜底：回退到最后有内容的页面
    return sp, sy, last_content_page, last_content_end


def main_crop():
    positions = load_example_positions()
    index = build_answer_index(positions)
    ANSWER_IMAGES_DIR.mkdir(parents=True, exist_ok=True)

    # 预计算章节横幅，避免 refine_span_end 里逐页反复 OCR
    precompute_chapter_banners()

    with open(QUESTIONS_JSON, 'r', encoding='utf-8') as f:
        qdata = json.load(f)

    matched = 0
    missing = []
    for ch in qdata.get('chapters', []):
        ch_name = ch['name']
        rng = ANSWER_RANGES.get(ch_name)
        if not rng:
            print(f'[跳过] 未配置答案范围: {ch_name}')
            continue
        ex_index = index.get(ch_name, {})
        expected_examples = set()
        for q in ch['questions']:
            m = re.search(r'例\s*(\d+)', q['id'])
            if m:
                expected_examples.add(int(m.group(1)))
        spans = build_example_spans(ex_index, rng, ch_name, expected_examples)
        for q in tqdm(ch['questions'], desc=f'裁剪 {ch_name}'):
            m = re.search(r'例\s*(\d+)', q['id'])
            if not m:
                missing.append((q['uid'], '无法解析例题号'))
                continue
            ex_num = int(m.group(1))
            span = spans.get(ex_num)
            if not span:
                missing.append((q['uid'], f'未找到例{ex_num}'))
                continue
            start_page, start_y, end_page, end_y = span
            rel_path = f'images/answers/{ch_name.replace(" · ", "_")}_例{ex_num}.png'
            out_path = ROOT / '大学深埋' / 'math-bank' / rel_path
            if crop_answer_image(start_page, start_y, end_page, end_y, out_path):
                q['answer_ref'] = rel_path
                matched += 1
            else:
                missing.append((q['uid'], '裁剪失败'))

    write_json_atomic(QUESTIONS_JSON, qdata)
    print(f'\n匹配答案图: {matched}/{sum(len(ch["questions"]) for ch in qdata["chapters"])}')
    if missing:
        print(f'未匹配: {len(missing)} 道')
        for uid, reason in missing[:20]:
            print(f'  {uid}: {reason}')


def main_header_scan():
    render_pdf()
    engine = ensure_cnocr()
    page_chapter = scan_headers(engine)
    ranges = infer_chapter_ranges(page_chapter)
    print('\n推断章节范围：')
    for ch, start, end in ranges:
        print(f'  {ch}: {start}-{end} ({end - start + 1} 页)')
    out = ROOT / '大学深埋' / 'answer_page_chapters.json'
    write_json_atomic(out, {
        'page_chapter': {str(k): v for k, v in page_chapter.items()},
        'ranges': [{'chapter': ch, 'start': s, 'end': e} for ch, s, e in ranges],
    })
    print(f'已保存 {out}')


def main_top_scan():
    engine = ensure_cnocr()
    records = scan_top_regions(engine)
    save_top_scan(records)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('stage', choices=['header', 'top', 'pos', 'crop'], default='header', nargs='?')
    args = parser.parse_args()
    if args.stage == 'header':
        main_header_scan()
    elif args.stage == 'top':
        main_top_scan()
    elif args.stage == 'pos':
        main_example_positions()
    elif args.stage == 'crop':
        main_crop()


