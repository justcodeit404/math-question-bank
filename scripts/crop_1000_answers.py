#!/usr/bin/env python3
"""
裁剪 1000 题答案册，为每道题生成独立答案图片。

用法：
  python scripts/crop_1000_answers.py
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

# 让后台任务能实时看到进度
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(line_buffering=True)

ROOT = Path(__file__).resolve().parent.parent
QUESTIONS_PATH = ROOT / '1000题' / 'questions.json'
ANSWER_PAGES_PATH = ROOT / '1000题' / 'answer_pages.json'
ANSWER_IMAGES_DIR = ROOT / '1000题' / 'answer_images'
CROPS_DIR = ROOT / '1000题' / 'math-bank' / 'answer_crops'

# 页面内容区域（去掉页眉页脚）
CONTENT_TOP = 150
CONTENT_BOTTOM_MARGIN = 80
MARGIN_TOP = 10
NOTE_MARGIN = 300  # 注记块一般跨几行，给一个较大余量避免切到下一题


def ensure_cnocr():
    try:
        from cnocr import CnOcr
        import onnxruntime as ort
        # Windows 上优先用 DirectML（不需要 CUDA/cuDNN，支持所有 DX12 显卡）
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
    """把 CnOCR 返回的 box（numpy array 或 list）统一转成 list。"""
    if box is None:
        return []
    if hasattr(box, 'tolist'):
        box = box.tolist()
    return box


def detect_markers(engine, page_num):
    """识别单页中的题号标记、弱标记（仅数字）和注记标记。

    返回 (strict_markers, weak_markers, note_markers, size)。
    strict:  匹配 "1.【答案】/【解析】/【分析】/解/答案/证明" 等完整标记。
    weak:    只匹配开头的题号数字（如 "22"、"22."），用于补救 OCR 拆行。
    notes:   匹配 "【注】/（注/注：" 等注记块，用来把注记归到上一题。
    """
    img_path = ANSWER_IMAGES_DIR / f'page_{page_num:03d}.png'
    if not img_path.exists():
        return [], [], [], None
    try:
        result = engine.ocr(str(img_path))
        if result is None:
            return [], [], [], None
    except Exception as e:
        print(f'    [警告] page {page_num} OCR 失败: {e}')
        return [], [], [], None
    try:
        img = Image.open(img_path)
        width, height = img.size
    except Exception as e:
        print(f'    [警告] page {page_num} 图片打开失败: {e}')
        return [], [], [], None

    strict_markers = []
    weak_markers = []
    note_markers = []

    strict_pattern = re.compile(r'^(\d{1,2})[\.．]\s*(?:【答案】|【解析】|【分析】|解|答案|证明)')
    weak_pattern = re.compile(r'^(\d{1,2})(?:[\.．])?$')
    note_pattern = re.compile(r'^[（(【]?注(?:[】】]|[：:]|$)')

    for r in result:
        box = _box_to_list(r.get('position', []))
        if not box:
            continue
        text = r.get('text', '')
        text_stripped = text.strip().replace(' ', '')
        ys = [p[1] for p in box]
        xs = [p[0] for p in box]
        base = {
            'page': page_num,
            'y_top': min(ys),
            'y_bottom': max(ys),
            'x_left': min(xs),
            'x_right': max(xs),
            'height': height,
            'width': width,
            'text': text_stripped[:60],
        }

        m = strict_pattern.match(text_stripped)
        if m:
            item = dict(base, qnum=int(m.group(1)))
            strict_markers.append(item)
            continue

        m = weak_pattern.match(text_stripped)
        if m:
            item = dict(base, qnum=int(m.group(1)))
            weak_markers.append(item)
            continue

        if note_pattern.match(text_stripped):
            note_markers.append(base)

    return strict_markers, weak_markers, note_markers, (width, height)


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
    """构建从 start 到 end 的页面裁剪范围。"""
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
    """计算从 (start_page, start_y) 到 (end_page, end_y) 的累计像素高度。"""
    if start_page == end_page:
        return max(0, end_y - start_y)
    h = img_cache[start_page].height - CONTENT_BOTTOM_MARGIN - start_y
    for p in range(start_page + 1, end_page):
        h += img_cache[p].height - CONTENT_TOP - CONTENT_BOTTOM_MARGIN
    h += end_y - CONTENT_TOP
    return max(0, h)


def _advance_by_height(start_page, start_y, delta, end_page, end_y, img_cache):
    """从起点沿页面往下移动 delta 像素，返回落点 (page, y)。"""
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
    """为每道题估计起始位置 (page, y_top)。

    已有严格/弱标记的用真实位置；缺失的用注记边界、页边界或线性插值估计。
    """
    bp = {}

    # 1. 已知位置
    for qnum in expected_qnums:
        if qnum in marker_by_qnum:
            m = marker_by_qnum[qnum]
            bp[qnum] = (m['page'], max(CONTENT_TOP, int(m['y_top'] - MARGIN_TOP)))

    # 2. 缺失题号估计
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

        # 整章无标记
        if prev_q is None and next_q is None:
            bp[qnum] = (start_page, CONTENT_TOP)
            continue

        # 在第一个已知标记之前：从章节开头均分
        if prev_q is None:
            first_q = next_q
            first_page, first_y = bp[first_q]
            missing_before = [q for q in expected_qnums if q < first_q]
            n = len(missing_before)
            total_h = _region_height(start_page, CONTENT_TOP, first_page, first_y, img_cache)
            pos = missing_before.index(qnum)
            # n 个缺失题把区域分成 n+1 份，第 pos 个断点在 (pos+1)/(n+1)
            delta = int(total_h * (pos + 1) / (n + 1))
            bp[qnum] = _advance_by_height(start_page, CONTENT_TOP, delta, first_page, first_y, img_cache)
            continue

        # 在最后一个已知标记之后：到最后均分
        if next_q is None:
            prev_page, prev_y = bp[prev_q]
            missing_after = [q for q in expected_qnums if q > prev_q]
            n = len(missing_after)
            end_y = img_cache[end_page].height - CONTENT_BOTTOM_MARGIN
            total_h = _region_height(prev_page, prev_y, end_page, end_y, img_cache)
            pos = missing_after.index(qnum)
            # n 个缺失题 + prev_q 共 n+1 段，第 pos 个缺失题断点在 (pos+1)/(n+1)
            delta = int(total_h * (pos + 1) / (n + 1))
            bp[qnum] = _advance_by_height(prev_page, prev_y, delta, end_page, end_y, img_cache)
            continue

        # 在 prev 与 next 之间
        prev_page, prev_y = bp[prev_q]
        next_page, next_y = bp[next_q]
        missing_between = [q for q in expected_qnums if prev_q < q < next_q]
        n = len(missing_between)
        pos = missing_between.index(qnum)

        # 找 prev 与 next 之间的注记，单个缺失时用它作为边界
        seg_notes = [
            nt for nt in note_markers
            if _point_after(nt['page'], nt['y_top'], prev_page, prev_y)
            and _point_before(nt['page'], nt['y_bottom'], next_page, next_y)
        ]
        if seg_notes and n == 1:
            last_note = max(seg_notes, key=lambda nt: (nt['page'], nt['y_bottom']))
            note_page = last_note['page']
            # 注记块往下延伸 NOTE_MARGIN，但不能超过下一题标记或当前页内容底部
            if note_page == next_page:
                max_y = next_y
            else:
                max_y = img_cache[note_page].height - CONTENT_BOTTOM_MARGIN
            y = min(last_note['y_bottom'] + NOTE_MARGIN, max_y)
            # 如果注记边界把缺失题压到和下一题标记重合（零高度），回退到插值
            if y < next_y - 50:
                bp[qnum] = (note_page, y)
                continue

        total_h = _region_height(prev_page, prev_y, next_page, next_y, img_cache)
        delta = int(total_h * (pos + 1) / (n + 1))
        bp[qnum] = _advance_by_height(prev_page, prev_y, delta, next_page, next_y, img_cache)

    return bp


def process_chapter(engine, chapter_idx, chapter, answer_pages, img_cache, report):
    """处理单个章节，返回该章节生成的裁剪图数量。"""
    ch_name = chapter['name']
    page_range = answer_pages.get(ch_name)
    if not page_range:
        report['missing_page_range'].append(ch_name)
        return 0

    # 支持单范围或 sub_ranges（用于一个章节跨多个答案章节的情况）
    sub_ranges = page_range.get('sub_ranges')
    if sub_ranges:
        ranges = [(r['start'], r['end'], r.get('qnum_offset', 0)) for r in sub_ranges]
    else:
        ranges = [(page_range['start'], page_range['end'], 0)]

    start_page = min(r[0] for r in ranges)
    end_page = max(r[1] for r in ranges)

    # 预加载章节内所有页面（答案册最后一页可能只有页脚，也要能取到尺寸）
    for start_p, end_p, _ in ranges:
        for page_num in tqdm(range(start_p, end_p + 1), desc=f'  [{chapter_idx}] 加载页面', leave=False):
            if page_num not in img_cache:
                img_path = ANSWER_IMAGES_DIR / f'page_{page_num:03d}.png'
                if img_path.exists():
                    img_cache[page_num] = Image.open(img_path)

    # 收集该章节所有页面的严格标记、弱标记和注记标记
    strict_markers = []
    weak_markers = []
    note_markers = []
    for start_p, end_p, qnum_offset in ranges:
        for page_num in tqdm(range(start_p, end_p + 1), desc=f'  [{chapter_idx}] OCR 题号', leave=False):
            s, w, n, _ = detect_markers(engine, page_num)
            for lst, target in [(s, strict_markers), (w, weak_markers), (n, note_markers)]:
                for m in lst:
                    if qnum_offset and 'qnum' in m:
                        m = dict(m)
                        m['qnum'] += qnum_offset
                    target.append(m)

    def dedup_by_qnum(markers):
        seen = {}
        for m in markers:
            key = (m['page'], m['qnum'])
            if key not in seen or m['y_top'] < seen[key]['y_top']:
                seen[key] = m
        return sorted(seen.values(), key=lambda x: (x['page'], x['y_top']))

    strict_markers = dedup_by_qnum(strict_markers)
    weak_markers = dedup_by_qnum(weak_markers)

    questions = chapter.get('questions', [])
    qnum_to_question = {q['qnum']: q for q in questions}
    expected_qnums = sorted(q['qnum'] for q in questions)

    # marker_by_qnum: 只用严格标记；弱标记误报率高（如把上一题末尾的 "2 2" 当成下一题题号），
    # 暂时不用于边界，留到报告里作为 detected_markers 的辅助参考。
    marker_by_qnum = {m['qnum']: m for m in strict_markers}

    report['chapters'][ch_name] = {
        'expected': len(questions),
        'detected_markers': len(strict_markers),
        'generated': 0,
        'missing': [],
    }

    breakpoints = build_breakpoints(
        expected_qnums, marker_by_qnum, note_markers,
        start_page, end_page, img_cache
    )

    generated = 0
    for i, qnum in enumerate(expected_qnums):
        q = qnum_to_question.get(qnum)
        out_path = CROPS_DIR / f'chapter_{chapter_idx}_q{qnum}.png'
        expected_ref = f'answer_crops/chapter_{chapter_idx}_q{qnum}.png'

        # 增量跳过：文件已存在且 questions.json 已指向它
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
            report['chapters'][ch_name]['missing'].append(f'q{qnum}_crop_failed')
            continue
        crop.save(out_path, 'PNG')
        if q is not None:
            q['answer_ref'] = expected_ref
        generated += 1

    # 记录真正的 OCR 漏识别（只算严格标记）
    detected_qnums = {m['qnum'] for m in strict_markers}
    for q in questions:
        if q['qnum'] not in detected_qnums:
            report['chapters'][ch_name]['missing'].append(f'q{q["qnum"]}_not_detected')

    report['chapters'][ch_name]['generated'] = generated
    return generated


def main():
    print('加载数据...')
    with open(QUESTIONS_PATH, 'r', encoding='utf-8') as f:
        data = json.load(f)
    with open(ANSWER_PAGES_PATH, 'r', encoding='utf-8') as f:
        answer_pages = json.load(f)

    # 备份 questions.json
    backup_path = QUESTIONS_PATH.with_suffix('.json.bak')
    shutil.copy2(QUESTIONS_PATH, backup_path)
    print(f'已备份到 {backup_path}')

    # 保留已有裁剪图，支持增量续跑
    CROPS_DIR.mkdir(parents=True, exist_ok=True)

    engine = ensure_cnocr()
    img_cache = {}
    report = {
        'missing_page_range': [],
        'chapters': {},
    }

    total_generated = 0
    chapters = data['chapters']
    for idx, ch in enumerate(tqdm(chapters, desc='裁剪章节', unit='章')):
        count = process_chapter(engine, idx, ch, answer_pages, img_cache, report)
        total_generated += count
        tqdm.write(f'[{idx}] {ch["name"]}: {count}/{len(ch.get("questions", []))} 张答案图')

    # 保存 questions.json
    write_json_atomic(QUESTIONS_PATH, data)
    print(f'\n已更新 {QUESTIONS_PATH}')

    # 保存报告
    report_path = ROOT / 'temp' / 'reports' / 'answer_crop_report.json'
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with open(report_path, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f'报告已保存到 {report_path}')

    total_questions = sum(len(ch.get('questions', [])) for ch in data['chapters'])
    print(f'\n总计：{total_generated}/{total_questions} 道题生成答案图')


if __name__ == '__main__':
    main()
