#!/usr/bin/env python3
"""为 880 题从答案 PDF 中裁剪每道题的答案图。

答案 PDF：880题/【PDF】27版880参考答案.pdf (354页)
TOC 显示前 6 章（高等数学）在答案 PDF 第 1-217 页，qnum 1-616。
子节（基础/综合/拓展）题号在每个章节内从 (1) 重新开始编号。

策略：
1. 用 TOC 硬编码每章每子节的 PDF 页码范围（前 6 章共 18 个子节）。
2. 用 OCR（DirectML GPU 加速）扫描子节范围页面，识别题号标记
   (N)X./(N)解/(N)证 的 (page, y_top) 坐标。
3. 按子节内题号出现顺序分配 1..N，建立 sub_num -> qnum 映射。
4. 用 build_breakpoints 算法计算每道题答案的起止位置，拼接多页裁剪为
   一张长图，保存到 880题/math-bank/answer_crops/。
5. 把每题的裁剪路径写入 questions.json 的 answer_ref 字段。
"""
import json
import re
import shutil
import sys
import warnings
from pathlib import Path

from PIL import Image
from tqdm import tqdm

sys.path.insert(0, str(Path(__file__).resolve().parent))
from utils import write_json_atomic

warnings.filterwarnings('ignore')

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(line_buffering=True)

ROOT = Path(__file__).resolve().parent.parent
PDF_IMAGES_DIR = ROOT / '880题' / 'answer_pdf_images'
QUESTIONS_PATH = ROOT / '880题' / 'questions.json'
CROPS_DIR = ROOT / '880题' / 'math-bank' / 'answer_crops'

# 页面内容区域（去掉页眉页脚）
CONTENT_TOP = 200
CONTENT_BOTTOM_MARGIN = 120
MARGIN_TOP = 10

# 基于 TOC 硬编码的章节-子节-页码范围（PDF 页码，前 6 章 qnum 1-616）
# (章节名, 子节, start_page, end_page_inclusive)
SECTION_RANGES = [
    ('第一章 函数·极限·连续', '基础题', 3, 8),    # 答案 p1-6
    ('第一章 函数·极限·连续', '综合题', 9, 24),   # 答案 p7-22
    ('第一章 函数·极限·连续', '拓展题', 25, 28),  # 答案 p23-26
    ('第二章 一元函数微分学', '基础题', 29, 48),   # 答案 p27-46
    ('第二章 一元函数微分学', '综合题', 49, 69),   # 答案 p47-67
    ('第二章 一元函数微分学', '拓展题', 70, 72),   # 答案 p68-70
    ('第三章 一元函数积分学', '基础题', 73, 94),   # 答案 p71-92
    ('第三章 一元函数积分学', '综合题', 95, 128),  # 答案 p93-126
    ('第三章 一元函数积分学', '拓展题', 129, 131), # 答案 p127-129
    ('第四章 多元函数微分学', '基础题', 134, 143), # 答案 p132-141
    ('第四章 多元函数微分学', '综合题', 144, 157), # 答案 p142-155
    ('第四章 多元函数微分学', '拓展题', 158, 159), # 答案 p156-157
    ('第五章 二重积分', '基础题', 160, 171),       # 答案 p158-169
    ('第五章 二重积分', '综合题', 172, 187),       # 答案 p170-185
    ('第五章 二重积分', '拓展题', 188, 189),       # 答案 p186-187
    ('第六章 微分方程', '基础题', 193, 200),       # 答案 p191-198
    ('第六章 微分方程', '综合题', 201, 218),       # 答案 p199-216
    ('第六章 微分方程', '拓展题', 219, 220),       # 答案 p217-218
    # 线代部分（qnum 617-926）
    ('第七章 行列式', '基础题', 221, 224),
    ('第七章 行列式', '综合题', 225, 230),
    ('第七章 行列式', '拓展题', 231, 232),
    ('第八章 矩阵', '基础题', 233, 241),
    ('第八章 矩阵', '综合题', 242, 248),
    ('第八章 矩阵', '拓展题', 249, 249),
    ('第九章 向量', '基础题', 250, 254),
    ('第九章 向量', '综合题', 255, 261),
    ('第九章 向量', '拓展题', 262, 263),
    ('第十章 线性方程组', '基础题', 264, 270),
    ('第十章 线性方程组', '综合题', 271, 281),
    ('第十章 线性方程组', '拓展题', 282, 283),
    ('第十一章 相似矩阵', '基础题', 284, 295),
    ('第十一章 相似矩阵', '综合题', 296, 314),
    ('第十一章 相似矩阵', '拓展题', 315, 316),
    ('第十二章 二次型', '基础题', 317, 325),
    ('第十二章 二次型', '综合题', 326, 346),
    ('第十二章 二次型', '拓展题', 347, 354),
]

# 题号标记
STRICT_PATTERN = re.compile(r'^\s*\((\d{1,3})\)\s*([A-D]|解|证|填)\s*\.?\s*$')
WEAK_PATTERN = re.compile(r'^\s*\((\d{1,3})\)\s*$')
# 子节标题（用于回退，验证 OCR 找对了范围）
SECTION_TITLE_PATTERN = re.compile(r'^\s*(基础题|综合题|拓展题)\s*$')


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


def detect_markers(engine, page_num):
    """识别单页中的题号标记和子节标题。"""
    img_path = PDF_IMAGES_DIR / f'page_{page_num:03d}.png'
    if not img_path.exists():
        return [], [], []
    try:
        result = engine.ocr(str(img_path))
    except Exception as e:
        return [], [], []
    strict_markers = []
    weak_markers = []
    section_titles = []
    for r in result or []:
        box = _box_to_list(r.get('position', []))
        if not box:
            continue
        text = r.get('text', '').strip().replace(' ', '').replace('\n', '')
        if not text:
            continue
        ys = [p[1] for p in box]
        xs = [p[0] for p in box]
        m = STRICT_PATTERN.match(text)
        if m:
            strict_markers.append({
                'page': page_num,
                'qnum': int(m.group(1)),
                'y_top': min(ys),
                'y_bottom': max(ys),
                'x_left': min(xs),
            })
            continue
        m = WEAK_PATTERN.match(text)
        if m:
            weak_markers.append({
                'page': page_num,
                'qnum': int(m.group(1)),
                'y_top': min(ys),
            })
            continue
        m = SECTION_TITLE_PATTERN.match(text)
        if m:
            section_titles.append({
                'page': page_num,
                'name': m.group(1),
                'y_top': min(ys),
                'y_bottom': max(ys),
            })
    return strict_markers, weak_markers, section_titles


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


def assign_sub_nums(strict_markers, n):
    """按 (page, y_top) 排序的 markers 分配子节内题号 1..n。"""
    if n == 0:
        return {}
    if not strict_markers:
        return {}

    sorted_markers = sorted(strict_markers, key=lambda m: (m['page'], m['y_top']))
    # 同一题号只保留第一次（去重）
    seen = {}
    for m in sorted_markers:
        if m['qnum'] not in seen:
            seen[m['qnum']] = m
    unique_markers = sorted(seen.values(), key=lambda m: (m['page'], m['y_top']))

    if not unique_markers:
        return {}

    # 分配 sub_num 1..n
    L = len(unique_markers)
    assigned = [None] * L
    # 锚点：marker.qnum 落在 [1, n] 范围内
    anchors = sorted(
        [(i, m['qnum']) for i, m in enumerate(unique_markers) if 1 <= m['qnum'] <= n],
        key=lambda x: x[0]
    )
    if not anchors:
        # 全部按顺序分配
        for i in range(L):
            assigned[i] = i + 1
    else:
        prev_idx, prev_q = -1, 0
        for idx, qnum in anchors:
            seg_count = idx - prev_idx
            num_count = qnum - prev_q
            if seg_count > 0 and num_count > 0:
                step = num_count / seg_count
                for j in range(seg_count):
                    assigned[prev_idx + 1 + j] = prev_q + 1 + round(j * step)
            assigned[idx] = qnum
            prev_idx, prev_q = idx, qnum
        for j in range(prev_idx + 1, L):
            assigned[j] = prev_q + 1 + (j - prev_idx - 1)
        for i in range(1, L):
            if assigned[i] is None or assigned[i] <= assigned[i - 1]:
                assigned[i] = (assigned[i - 1] or 0) + 1

    # 截断到 [1, n] 范围
    assigned = [max(1, min(n, q)) for q in assigned]

    return {unique_markers[i]['qnum'] if False else assigned[i]: unique_markers[i] for i in range(L)}


def process_section(engine, ch_name, sec_name, start_page, end_page, questions_in_sec, img_cache, report):
    """处理单个子节，裁剪每道题答案。"""
    n = len(questions_in_sec)
    if n == 0:
        return 0

    # 预加载图片
    for p in range(start_page, end_page + 1):
        if p not in img_cache:
            img_path = PDF_IMAGES_DIR / f'page_{p:03d}.png'
            if img_path.exists():
                img_cache[p] = Image.open(img_path)

    # 扫描子节范围内的所有页
    all_strict = []
    all_weak = []
    for p in range(start_page, end_page + 1):
        strict, weak, _ = detect_markers(engine, p)
        all_strict.extend(strict)
        all_weak.extend(weak)

    # 过滤：只保留 qnum 在 [1, n+5] 范围内的（容忍一些误识）
    all_strict = [m for m in all_strict if 1 <= m['qnum'] <= n + 10]

    # 分配子节内题号
    marker_by_sub = assign_sub_nums(all_strict, n)

    # 起点：子节首页 CONTENT_TOP
    start_y = CONTENT_TOP
    if start_page in img_cache:
        # 跳过子节首页的"基础题/综合题/拓展题"大标题（如果存在）
        # 大标题通常 y < 600
        pass

    # 终点：子节末页底部
    end_y = img_cache[end_page].height - CONTENT_BOTTOM_MARGIN

    # 起点和终点 (page, y)
    sp, sy = start_page, start_y
    ep, ey = end_page, end_y

    # 建立题号 (sub_num) -> (page, y_top) 映射（用 marker）
    bp = {sn: None for sn in range(1, n + 1)}
    for sn, m in marker_by_sub.items():
        if 1 <= sn <= n:
            bp[sn] = (m['page'], max(CONTENT_TOP, int(m['y_top'] - MARGIN_TOP)))

    # 用 weak 补充（仅在子节范围内）
    for m in all_weak:
        sn = m['qnum']
        if 1 <= sn <= n and bp[sn] is None and start_page <= m['page'] <= end_page:
            bp[sn] = (m['page'], max(CONTENT_TOP, int(m['y_top'] - MARGIN_TOP)))

    # 插值补齐缺失的题号
    for idx, sn in enumerate(range(1, n + 1)):
        if bp[sn] is not None:
            continue
        prev = next_ = None
        for j in range(idx - 1, -1, -1):
            if bp[j + 1] is not None:
                prev = j + 1
                break
        for j in range(idx + 1, n + 1):
            if bp[j] is not None:
                next_ = j
                break

        if prev is None and next_ is None:
            bp[sn] = (sp, sy)
            continue
        if prev is None:
            first_p, first_y = bp[next_]
            total_h = _region_height(sp, sy, first_p, first_y, img_cache)
            missing = list(range(1, next_))
            pos = sn - 1
            delta = int(total_h * (pos + 1) / (len(missing) + 1))
            bp[sn] = _advance_by_height(sp, sy, delta, first_p, first_y, img_cache)
        elif next_ is None:
            prev_p, prev_y = bp[prev]
            total_h = _region_height(prev_p, prev_y, ep, ey, img_cache)
            missing = list(range(prev + 1, n + 1))
            pos = sn - prev - 1
            delta = int(total_h * (pos + 1) / (len(missing) + 1))
            bp[sn] = _advance_by_height(prev_p, prev_y, delta, ep, ey, img_cache)
        else:
            prev_p, prev_y = bp[prev]
            next_p, next_y = bp[next_]
            total_h = _region_height(prev_p, prev_y, next_p, next_y, img_cache)
            missing = list(range(prev + 1, next_))
            pos = sn - prev - 1
            delta = int(total_h * (pos + 1) / (len(missing) + 1))
            bp[sn] = _advance_by_height(prev_p, prev_y, delta, next_p, next_y, img_cache)

    # 裁剪每道题
    generated = 0
    detected = set()
    for i, sn in enumerate(range(1, n + 1)):
        q = questions_in_sec[i]
        if sn in marker_by_sub:
            detected.add(sn)

        start_page_q, start_y_q = bp[sn]
        if i + 1 < n:
            next_sn = sn + 1
            end_page_q, end_y_q = bp[next_sn]
        else:
            end_page_q = ep
            end_y_q = ey

        page_y_ranges = build_page_y_ranges(start_page_q, start_y_q, end_page_q, end_y_q, img_cache)
        crop = crop_pages(page_y_ranges, img_cache)
        if crop is None:
            continue
        out_path = CROPS_DIR / f'q{q["qnum"]}.png'
        crop.save(out_path, 'PNG')
        q['answer_ref'] = f'answer_crops/q{q["qnum"]}.png'
        generated += 1

    report[(ch_name, sec_name)] = {
        'expected': n,
        'detected': len(detected),
        'generated': generated,
        'missing': [sn for sn in range(1, n + 1) if sn not in detected],
    }
    return generated


def main():
    print('加载数据...')
    with open(QUESTIONS_PATH, 'r', encoding='utf-8') as f:
        data = json.load(f)

    # 备份
    backup_path = QUESTIONS_PATH.with_suffix('.json.bak')
    shutil.copy2(QUESTIONS_PATH, backup_path)
    print(f'已备份到 {backup_path}')

    CROPS_DIR.mkdir(parents=True, exist_ok=True)

    # 建立 (ch_name, sec_name) -> questions 列表
    ch_sec_questions = {}
    for ch in data['chapters']:
        for q in ch['questions']:
            key = (ch['name'], q['section'])
            ch_sec_questions.setdefault(key, []).append(q)
    # 按 qnum 排序
    for key in ch_sec_questions:
        ch_sec_questions[key].sort(key=lambda q: q['qnum'])

    print('加载 OCR（DirectML GPU 加速）...')
    engine = ensure_cnocr()
    img_cache = {}

    # 处理每个子节
    total_generated = 0
    total_expected = 0
    report = {}
    for ch_name, sec_name, start_page, end_page in tqdm(SECTION_RANGES, desc='处理子节'):
        questions = ch_sec_questions.get((ch_name, sec_name), [])
        if not questions:
            print(f'  [跳过] 无题目: {ch_name} / {sec_name}')
            continue
        n = len(questions)
        total_expected += n
        gen = process_section(engine, ch_name, sec_name, start_page, end_page, questions, img_cache, report)
        total_generated += gen
        tqdm.write(f'  {ch_name} / {sec_name}: {gen}/{n}')

    # 保存
    write_json_atomic(QUESTIONS_PATH, data)
    print(f'\n已更新 {QUESTIONS_PATH}')

    report_path = ROOT / 'temp' / 'reports' / 'answer_crop_report_880.json'
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with open(report_path, 'w', encoding='utf-8') as f:
        json.dump({f'{k[0]}|{k[1]}': v for k, v in report.items()}, f, ensure_ascii=False, indent=2)
    print(f'报告已保存到 {report_path}')

    print(f'\n总计：{total_generated}/{total_expected} 道题生成答案图')


if __name__ == '__main__':
    main()