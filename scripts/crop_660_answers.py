#!/usr/bin/env python3
"""
裁剪 660 题答案册，为每道题生成独立答案图片。

高数答案在《基础过关660》-高数篇 .pdf 的 p170-347（题号 1-460）
线代答案在《基础过关660》-线代篇.pdf 的 p74-144（题号 461-660）

用法：
  python scripts/crop_660_answers.py
"""
import glob
import json
import re
import shutil
import sys
import warnings
from pathlib import Path

import cv2
import numpy as np
from PIL import Image
from tqdm import tqdm

sys.path.insert(0, str(Path(__file__).resolve().parent))
from utils import write_json_atomic

warnings.filterwarnings('ignore')

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(line_buffering=True)

ROOT = Path(__file__).resolve().parent.parent
QUESTIONS_PATH = ROOT / '660题' / 'questions.json'
CROPS_DIR = ROOT / '660题' / 'math-bank' / 'answer_crops'

# 页面内容区域（去掉页眉页脚）
# 线代部分题号方块紧贴页眉，需把顶部阈值放低
CONTENT_TOP = 80
CONTENT_BOTTOM_MARGIN = 80
MARGIN_TOP = 10
NOTE_MARGIN = 300

# 答案区范围（硬编码，基于 PDF 实际排版）
ANSWER_RANGES = [
    {
        'name': 'gaoshu',
        'pdf_name': '《基础过关660》-高数篇 .pdf',
        'img_dir_pattern': 'pdf_images',
        'start_page': 170,
        'end_page': 347,
        'qnum_start': 1,
        'qnum_end': 460,
    },
    {
        'name': 'xiandai',
        'pdf_name': '《基础过关660》-线代篇.pdf',
        'img_dir_pattern': 'pdf_images*线代*',
        'start_page': 74,
        'end_page': 144,
        'qnum_start': 461,
        'qnum_end': 660,
    },
]


def ensure_cnocr():
    try:
        from cnocr import CnOcr
        import onnxruntime as ort
        if 'DmlExecutionProvider' in ort.get_available_providers():
            return CnOcr(
                det_more_configs={
                    'engine_cfg': {
                        'use_cuda': False,
                        'use_dml': True,
                        'dml_ep_cfg': {},
                    }
                }
            )
        return CnOcr()
    except Exception as e:
        print(f'[错误] 无法加载 CnOCR: {e}')
        sys.exit(1)


def _box_to_list(box):
    if box is None:
        return []
    if hasattr(box, 'tolist'):
        box = box.tolist()
    return box


def find_image_dir(pattern):
    """通过 glob 找到图片目录（兼容线代目录名编码异常的情况）。"""
    base = str(ROOT / '660题')
    candidates = glob.glob(str(Path(base) / pattern))
    # 如果 pattern 本身不带通配符，glob 也会返回自身（若存在）
    for c in candidates:
        if Path(c).is_dir():
            return Path(c)
    # 精确名称再试一次
    exact = Path(base) / pattern
    if exact.is_dir():
        return exact
    return None


def _box_center_y(box):
    ys = [p[1] for p in box]
    return (min(ys) + max(ys)) / 2


def _box_center_x(box):
    xs = [p[0] for p in box]
    return (min(xs) + max(xs)) / 2


def _detect_colored_blocks(img_np):
    """用颜色检测找页面左侧的彩色题号方块。

    返回 [(x, y, w, h), ...]，按 y 排序。
    """
    hsv = cv2.cvtColor(img_np, cv2.COLOR_RGB2HSV)
    masks = []
    # 蓝 / 青 / 绿
    masks.append(cv2.inRange(hsv, (35, 40, 40), (130, 255, 255)))
    # 粉 / 紫
    masks.append(cv2.inRange(hsv, (140, 40, 40), (180, 255, 255)))
    # 红
    masks.append(cv2.inRange(hsv, (0, 40, 40), (15, 255, 255)))
    mask = masks[0]
    for m in masks[1:]:
        mask = cv2.bitwise_or(mask, m)

    # 形态学闭运算，把实心方块连起来
    kernel = np.ones((5, 5), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    height, width = img_np.shape[:2]
    blocks = []
    for c in contours:
        x, y, w, h = cv2.boundingRect(c)
        # 题号方块的几何特征：左侧、不太大、实心
        if h < 30 or h > 80:
            continue
        if w < 40 or w > 140:
            continue
        if x > width * 0.30:
            continue
        if y < CONTENT_TOP:
            continue
        # 宽高比
        if w / h < 0.8 or w / h > 2.5:
            continue
        blocks.append((x, y, w, h))
    return sorted(blocks, key=lambda b: b[1])


def _ocr_left_numbers(engine, img_np):
    """对页面左侧条带 OCR，返回候选数字框列表。"""
    height, width = img_np.shape[:2]
    left = img_np[:, :int(width * 0.35), :]
    result = engine.ocr(left)
    nums = []
    num_pattern = re.compile(r'^(\d{1,3})$')
    for r in result or []:
        box = _box_to_list(r.get('position', []))
        if not box:
            continue
        text = r.get('text', '').strip().replace(' ', '')
        m = num_pattern.match(text)
        if not m:
            continue
        ys = [p[1] for p in box]
        xs = [p[0] for p in box]
        nums.append({
            'qnum': int(m.group(1)),
            'y_top': min(ys),
            'y_bottom': max(ys),
            'cy': (min(ys) + max(ys)) / 2,
            'cx': (min(xs) + max(xs)) / 2,
        })
    return nums


def _ocr_answer_boxes(engine, img_np):
    """对全图 OCR，返回所有【答案】/【评注】框的位置。"""
    result = engine.ocr(img_np)
    answer_pattern = re.compile(r'【答案】|答案')
    note_pattern = re.compile(r'【评注】')
    answers = []
    notes = []
    for r in result or []:
        box = _box_to_list(r.get('position', []))
        if not box:
            continue
        text = r.get('text', '').strip().replace(' ', '')
        ys = [p[1] for p in box]
        xs = [p[0] for p in box]
        item = {
            'y_top': min(ys),
            'y_bottom': max(ys),
            'cy': (min(ys) + max(ys)) / 2,
            'x_left': min(xs),
            'x_right': max(xs),
        }
        if answer_pattern.search(text):
            answers.append(item)
        if note_pattern.match(text):
            notes.append(item)
    return answers, notes


def detect_markers(engine, img_path, page_num):
    """识别单页中的题号标记和注记标记。

    660 答案册的题号被彩色方块包裹，采用颜色检测定位方块，
    再用 OCR 读取方块内数字；同时检测【答案】框作为验证。
    """
    if not img_path.exists():
        return [], [], [], None
    try:
        img = Image.open(img_path)
        img_np = np.array(img)
        width, height = img.size
    except Exception as e:
        print(f'    [警告] page {page_num} 图片打开失败: {e}')
        return [], [], [], None

    blocks = _detect_colored_blocks(img_np)
    if not blocks:
        return [], [], [], (width, height)

    answers, notes = _ocr_answer_boxes(engine, img_np)
    left_nums = _ocr_left_numbers(engine, img_np)

    # 给 note / answer 补充页码（后续按页裁剪需要）
    for a in answers:
        a['page'] = page_num
    for n in notes:
        n['page'] = page_num

    markers = []
    for x, y, w, h in blocks:
        cy = y + h / 2
        # 验证1：右侧同一水平线附近有【答案】框
        has_answer = False
        for a in answers:
            if a['x_left'] < x + w:
                continue
            if abs(a['cy'] - cy) > max(35, h * 0.8):
                continue
            if a['x_left'] - (x + w) > width * 0.45:
                continue
            has_answer = True
            break

        # 验证2：左侧条带 OCR 识别到数字落在方块内
        matched_num = None
        for n in left_nums:
            if n['cx'] > x + w + 20:
                continue
            if n['cx'] < x - 20:
                continue
            if abs(n['cy'] - cy) > h * 0.8:
                continue
            matched_num = n
            break

        if not has_answer and matched_num is None:
            continue

        marker = {
            'page': page_num,
            'y_top': y,
            'y_bottom': y + h,
            'x_left': x,
            'x_right': x + w,
            'height': height,
            'width': width,
            'qnum': matched_num['qnum'] if matched_num else None,
            'text': str(matched_num['qnum']) if matched_num else '',
        }
        markers.append(marker)

    return markers, [], notes, (width, height)


def assign_qnums(markers, qnum_start, qnum_end):
    """给按顺序排列的 marker 分配题号。

    优先使用 OCR 识别出的数字作为锚点，无锚点时按顺序分配；
    锚点之间出现漏检时会自动跳过缺失题号（后续用插值补齐）。
    """
    n = len(markers)
    if n == 0:
        return []
    Q = [None] * n
    anchors = sorted(
        [(i, m['qnum']) for i, m in enumerate(markers) if m['qnum'] is not None],
        key=lambda x: x[0]
    )
    if not anchors:
        return [qnum_start + i for i in range(n)]

    prev_idx, prev_q = -1, qnum_start - 1
    for idx, qnum in anchors:
        seg_count = idx - prev_idx
        num_count = qnum - prev_q
        if seg_count <= 0 or num_count <= 0:
            continue
        step = num_count / seg_count
        for j in range(seg_count):
            Q[prev_idx + 1 + j] = prev_q + 1 + round(j * step)
        # 强制锚点正确
        Q[idx] = qnum
        prev_idx, prev_q = idx, qnum

    # 最后一个锚点之后顺序分配
    for j in range(prev_idx + 1, n):
        Q[j] = prev_q + 1 + (j - prev_idx - 1)

    # 兜底：确保非递减
    for i in range(1, n):
        if Q[i] is None or Q[i] <= Q[i - 1]:
            Q[i] = Q[i - 1] + 1

    # 裁剪到范围
    return [max(qnum_start, min(qnum_end, q)) for q in Q]


def crop_pages(page_y_ranges, img_cache):
    """按 (page, y1, y2) 列表裁剪并拼接成一张长图。"""
    crops = []
    for page, y1, y2 in page_y_ranges:
        img = img_cache.get(page)
        if img is None:
            continue
        y1 = max(0, y1)
        y2 = min(img.height, y2)
        if y2 > y1:
            crops.append(img.crop((0, y1, img.width, y2)))
    if not crops:
        return None
    total_height = sum(c.height for c in crops)
    max_width = max(c.width for c in crops)
    combined = Image.new('RGB', (max_width, total_height), 'white')
    y_offset = 0
    for c in crops:
        combined.paste(c, (0, y_offset))
        y_offset += c.height
    return combined


def build_page_y_ranges(start_page, start_y, end_page, end_y, img_cache):
    ranges = []
    if start_page == end_page:
        ranges.append((start_page, start_y, end_y))
        return ranges
    ranges.append((start_page, start_y, img_cache[start_page].height - CONTENT_BOTTOM_MARGIN))
    for p in range(start_page + 1, end_page):
        ranges.append((p, CONTENT_TOP, img_cache[p].height - CONTENT_BOTTOM_MARGIN))
    ranges.append((end_page, CONTENT_TOP, end_y))
    return ranges


def _point_after(p1_page, p1_y, p2_page, p2_y):
    return p1_page > p2_page or (p1_page == p2_page and p1_y > p2_y)


def _point_before(p1_page, p1_y, p2_page, p2_y):
    return p1_page < p2_page or (p1_page == p2_page and p1_y < p2_y)


def _region_height(start_page, start_y, end_page, end_y, img_cache):
    if start_page == end_page:
        return max(0, end_y - start_y)
    h = img_cache[start_page].height - CONTENT_BOTTOM_MARGIN - start_y
    for p in range(start_page + 1, end_page):
        h += img_cache[p].height - CONTENT_TOP - CONTENT_BOTTOM_MARGIN
    h += end_y - CONTENT_TOP
    return max(0, h)


def _advance_by_height(start_page, start_y, delta, end_page, end_y, img_cache):
    if start_page == end_page:
        return (start_page, min(start_y + delta, end_y))
    remain = img_cache[start_page].height - CONTENT_BOTTOM_MARGIN - start_y
    if delta <= remain:
        return (start_page, start_y + delta)
    delta -= remain
    for p in range(start_page + 1, end_page):
        page_h = img_cache[p].height - CONTENT_TOP - CONTENT_BOTTOM_MARGIN
        if delta <= page_h:
            return (p, CONTENT_TOP + delta)
        delta -= page_h
    return (end_page, min(CONTENT_TOP + delta, end_y))


def build_breakpoints(expected_qnums, marker_by_qnum, note_markers, start_page, end_page, img_cache):
    bp = {}
    for qnum in expected_qnums:
        if qnum in marker_by_qnum:
            m = marker_by_qnum[qnum]
            bp[qnum] = (m['page'], max(CONTENT_TOP, int(m['y_top'] - MARGIN_TOP)))

    for idx, qnum in enumerate(expected_qnums):
        if qnum in bp:
            continue

        prev_q = None
        for j in range(idx - 1, -1, -1):
            if expected_qnums[j] in bp:
                prev_q = expected_qnums[j]
                break
        next_q = None
        for j in range(idx + 1, len(expected_qnums)):
            if expected_qnums[j] in bp:
                next_q = expected_qnums[j]
                break

        if prev_q is None and next_q is None:
            bp[qnum] = (start_page, CONTENT_TOP)
            continue

        if prev_q is None:
            first_q = next_q
            first_page, first_y = bp[first_q]
            missing_before = [q for q in expected_qnums if q < first_q]
            n = len(missing_before)
            total_h = _region_height(start_page, CONTENT_TOP, first_page, first_y, img_cache)
            pos = missing_before.index(qnum)
            delta = int(total_h * (pos + 1) / (n + 1))
            bp[qnum] = _advance_by_height(start_page, CONTENT_TOP, delta, first_page, first_y, img_cache)
            continue

        if next_q is None:
            prev_page, prev_y = bp[prev_q]
            missing_after = [q for q in expected_qnums if q > prev_q]
            n = len(missing_after)
            end_y = img_cache[end_page].height - CONTENT_BOTTOM_MARGIN
            total_h = _region_height(prev_page, prev_y, end_page, end_y, img_cache)
            pos = missing_after.index(qnum)
            delta = int(total_h * (pos + 1) / (n + 1))
            bp[qnum] = _advance_by_height(prev_page, prev_y, delta, end_page, end_y, img_cache)
            continue

        prev_page, prev_y = bp[prev_q]
        next_page, next_y = bp[next_q]
        missing_between = [q for q in expected_qnums if prev_q < q < next_q]
        n = len(missing_between)
        pos = missing_between.index(qnum)

        seg_notes = [
            nt for nt in note_markers
            if _point_after(nt['page'], nt['y_top'], prev_page, prev_y)
            and _point_before(nt['page'], nt['y_bottom'], next_page, next_y)
        ]
        if seg_notes and n == 1:
            last_note = max(seg_notes, key=lambda nt: (nt['page'], nt['y_bottom']))
            note_page = last_note['page']
            if note_page == next_page:
                max_y = next_y
            else:
                max_y = img_cache[note_page].height - CONTENT_BOTTOM_MARGIN
            y = min(last_note['y_bottom'] + NOTE_MARGIN, max_y)
            if y < next_y - 50:
                bp[qnum] = (note_page, y)
                continue

        total_h = _region_height(prev_page, prev_y, next_page, next_y, img_cache)
        delta = int(total_h * (pos + 1) / (n + 1))
        bp[qnum] = _advance_by_height(prev_page, prev_y, delta, next_page, next_y, img_cache)

    return bp


def process_answer_range(engine, arange, questions_by_qnum, img_cache, report):
    """处理一个答案范围（高数或线代）。"""
    name = arange['name']
    start_page = arange['start_page']
    end_page = arange['end_page']
    qnum_start = arange['qnum_start']
    qnum_end = arange['qnum_end']

    img_dir = find_image_dir(arange['img_dir_pattern'])
    if img_dir is None:
        report[name] = {'error': f'找不到图片目录: {arange["img_dir_pattern"]}'}
        return 0

    expected_qnums = list(range(qnum_start, qnum_end + 1))

    # 预加载图片
    for page_num in tqdm(range(start_page, end_page + 1), desc=f'  [{name}] 加载页面', leave=False):
        if page_num not in img_cache:
            img_path = img_dir / f'page_{page_num:03d}.png'
            if img_path.exists():
                img_cache[page_num] = Image.open(img_path)

    markers = []
    note_markers = []
    for page_num in tqdm(range(start_page, end_page + 1), desc=f'  [{name}] 检测题号', leave=False):
        img_path = img_dir / f'page_{page_num:03d}.png'
        s, _, n, _ = detect_markers(engine, img_path, page_num)
        markers.extend(s)
        note_markers.extend(n)

    # 按页码和 y 坐标排序，并分配题号
    markers.sort(key=lambda m: (m['page'], m['y_top']))
    assigned = assign_qnums(markers, qnum_start, qnum_end)
    marker_by_qnum = {}
    for i, m in enumerate(markers):
        qnum = assigned[i]
        # 同一题号只保留第一次出现的 marker（避免末尾广告页的假 marker 覆盖真题号）
        if qnum not in marker_by_qnum:
            marker_by_qnum[qnum] = m

    # 去掉答案区后面的广告页：以最后一个真实题号所在页为实际结束页
    effective_end_page = max((m['page'] for m in marker_by_qnum.values()), default=end_page)
    end_page = effective_end_page

    report[name] = {
        'expected': len(expected_qnums),
        'detected_markers': len(markers),
        'anchored': sum(1 for m in markers if m['qnum'] is not None),
        'generated': 0,
        'missing': [],
    }

    breakpoints = build_breakpoints(
        expected_qnums, marker_by_qnum, note_markers,
        start_page, end_page, img_cache
    )

    generated = 0
    for i, qnum in enumerate(expected_qnums):
        q = questions_by_qnum.get(qnum)
        out_path = CROPS_DIR / f'q{qnum}.png'
        expected_ref = f'answer_crops/q{qnum}.png'

        if out_path.exists() and q is not None and q.get('answer_ref') == expected_ref:
            generated += 1
            continue

        start_page_q, start_y = breakpoints[qnum]
        if i + 1 < len(expected_qnums):
            next_qnum = expected_qnums[i + 1]
            end_page_q, end_y = breakpoints[next_qnum]
        else:
            end_page_q = end_page
            end_y = img_cache[end_page].height - CONTENT_BOTTOM_MARGIN

        page_y_ranges = build_page_y_ranges(start_page_q, start_y, end_page_q, end_y, img_cache)
        crop = crop_pages(page_y_ranges, img_cache)
        if crop is None:
            report[name]['missing'].append(f'q{qnum}_crop_failed')
            continue
        crop.save(out_path, 'PNG')
        if q is not None:
            q['answer_ref'] = expected_ref
        generated += 1

    detected_qnums = set(marker_by_qnum.keys())
    for qnum in expected_qnums:
        if qnum not in detected_qnums:
            report[name]['missing'].append(f'q{qnum}_not_detected')

    report[name]['generated'] = generated
    return generated


def main():
    print('加载数据...')
    with open(QUESTIONS_PATH, 'r', encoding='utf-8') as f:
        data = json.load(f)

    # 备份
    backup_path = QUESTIONS_PATH.with_suffix('.json.bak')
    shutil.copy2(QUESTIONS_PATH, backup_path)
    print(f'已备份到 {backup_path}')

    # 扁平化所有题目
    questions_by_qnum = {}
    for ch in data.get('chapters', []):
        for q in ch.get('questions', []):
            questions_by_qnum[q['qnum']] = q

    CROPS_DIR.mkdir(parents=True, exist_ok=True)

    engine = ensure_cnocr()
    img_cache = {}
    report = {}

    total_generated = 0
    for arange in ANSWER_RANGES:
        count = process_answer_range(engine, arange, questions_by_qnum, img_cache, report)
        total_generated += count
        tqdm.write(f'[{arange["name"]}] {count}/{arange["qnum_end"] - arange["qnum_start"] + 1} 张答案图')

    write_json_atomic(QUESTIONS_PATH, data)
    print(f'\n已更新 {QUESTIONS_PATH}')

    report_path = ROOT / 'temp' / 'reports' / 'answer_crop_report_660.json'
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with open(report_path, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f'报告已保存到 {report_path}')

    total_questions = len(questions_by_qnum)
    print(f'\n总计：{total_generated}/{total_questions} 道题生成答案图')


if __name__ == '__main__':
    main()
