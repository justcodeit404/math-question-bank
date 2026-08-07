#!/usr/bin/env python3
"""用 MiniMax-M3 视觉模型重提 880/大学深埋 线代题目，支持多页一次调用。

用法：
    export MINIMAX_API_KEY='...'
    export MINIMAX_BASE_URL='https://mimimax.cn/v1'
    python scripts/extract_linear_minimax.py --bank 880-linear
    python scripts/extract_linear_minimax.py --bank 大学深埋线代
"""
import argparse
import base64
import json
import os
import re
import sys
import time
import urllib.request
from pathlib import Path

import fitz
from PIL import Image
from tqdm import tqdm

sys.path.insert(0, str(Path(__file__).resolve().parent))
from utils import write_json_atomic

sys.stdout.reconfigure(encoding='utf-8')

ROOT = Path(__file__).resolve().parent.parent

API_KEY = os.environ.get('MINIMAX_API_KEY')
BASE_URL = os.environ.get('MINIMAX_BASE_URL', 'https://mimimax.cn/v1')
MODEL = 'MiniMax-M3'

BANK_CONFIG = {
    '880-linear': {
        'pdf': ROOT / '880题' / '【横版】李林880数二线代篇做题本.pdf',
        'img_dir': ROOT / 'temp' / '880_linear_minimax_images',
        'results': ROOT / 'temp' / '880_linear_minimax_results.json',
        'first_qnum': 617,
        'source': '李林880数二线代篇',
        'title': '李林880数二（高数+线代）',
        'bank_id': '880',
        'chapter_ranges': [
            {'name': '第七章 行列式', 'start': 1, 'end': 39},
            {'name': '第八章 矩阵', 'start': 40, 'end': 95},
            {'name': '第九章 向量', 'start': 96, 'end': 132},
            {'name': '第十章 线性方程组', 'start': 133, 'end': 186},
            {'name': '第十一章 相似矩阵', 'start': 187, 'end': 248},
            {'name': '第十二章 二次型', 'start': 249, 'end': 311},
        ],
        'sections': ['基础题', '综合题', '拓展题'],
        'out_json': ROOT / '880题' / 'questions_linear_minimax.json',
        'crop_out_dir': ROOT / '880题' / 'math-bank' / 'images' / '线代',
    },
    '大学深埋线代': {
        'pdf': ROOT / '大学深埋' / '【横版】27ep线代讲义例题做题本.pdf',
        'img_dir': ROOT / '大学深埋' / 'pdf_images_线代',
        'results': ROOT / 'temp' / '大学深埋_linear_minimax_results.json',
        'source': '【横版】27ep线代讲义例题做题本.pdf',
        'title': '大学深埋（高数+线代）',
        'bank_id': '大学深埋',
        'out_json': ROOT / '大学深埋' / 'questions_linear_minimax.json',
        # 复用已有的题目截图
        'existing_questions': ROOT / '大学深埋' / 'questions.json',
    },
}

PROMPT_TEMPLATE = (
    '下面有 {n} 张数学题库页面截图，每张图对应一道题。'
    '请分别提取，返回一个 JSON 数组，数组长度为 {n}，每个元素格式如下：\n'
    '{"qnum": 题号数字（没有则 null）, '
    '"type": "选择题/填空题/计算题/证明题", '
    '"content": "题干文本（所有数学公式、矩阵、向量、上下标必须用 $...$ 包裹）", '
    '"options": {"A":"...","B":"...","C":"...","D":"..."}（没有则 null）, '
    '"sub_questions": ["(I)...", "(II)..."]（没有则 null）}\n\n'
    '要求：\n'
    '1. 只返回 JSON 数组，不要任何解释、不要 markdown 代码块\n'
    '2. 矩阵/行列式用 LaTeX：\\begin{vmatrix}（行列式）、\\begin{pmatrix}（圆括号矩阵）、\\begin{bmatrix}（方括号矩阵），元素间用 & 分隔，行间用 \\\\ 分隔\n'
    '3. 上标用 ^{}，下标用 _{}，分式用 \\frac{a}{b}\n'
    '4. 希腊字母用 \\alpha, \\beta, \\gamma, \\lambda, \\mu 等命令\n'
    '5. 向量转置写成 ^{}，例如 $\\alpha^{T}$\n'
    '6. 填空题空白用 ____ 表示\n'
    '7. 如果某张图不是题目（如纯标题页），对应元素填 null\n'
)

FOOTER_PAT = re.compile(r'[·\s]*第\s*\d+\s*页，共\s*\d+\s*页\s*[·\s]*$')
WATERMARK_PATS = [
    re.compile(r'公众号[:：]做题本集结地'),
    re.compile(r'27\s*版880'),
    re.compile(r'ep强化讲义例题[^\n]*'),
    re.compile(r'这是一条为了防止被小坏蛋拿去转卖[^\n]*'),
]


_VALID_JSON_ESCAPES = {'"', '\\', '/', 'b', 'f', 'n', 'r', 't'}


def fix_json_escapes(s):
    r"""把 JSON 中非法的 \X 转义补成 \\X，修复模型漏写的反斜杠。"""
    result = []
    i = 0
    while i < len(s):
        if s[i] == '\\' and i + 1 < len(s):
            nxt = s[i + 1]
            is_unicode = nxt == 'u' and i + 5 < len(s) and all(
                c in '0123456789abcdefABCDEF' for c in s[i + 2:i + 6]
            )
            if nxt in _VALID_JSON_ESCAPES or is_unicode:
                result.append(s[i:i + 2])
                i += 2
                continue
            result.append('\\\\')
            i += 1
            continue
        result.append(s[i])
        i += 1
    return ''.join(result)


def strip_think(text):
    while '<think>' in text and '</think>' in text:
        start = text.find('<think>')
        end = text.find('</think>', start) + len('</think>')
        text = text[:start] + text[end:]
    return text.strip()


def clean_text(text):
    if not text:
        return text
    text = text.replace('\r', '\n')
    # remove footer/watermark lines
    lines = []
    for line in text.split('\n'):
        line = line.strip()
        if not line:
            continue
        if FOOTER_PAT.search(line):
            continue
        if any(p.search(line) for p in WATERMARK_PATS):
            continue
        lines.append(line)
    text = '\n'.join(lines)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def encode_image(image_path):
    with open(image_path, 'rb') as f:
        return base64.b64encode(f.read()).decode()


def render_pdf_pages(pdf_path, img_dir, pages=None, dpi=200):
    img_dir.mkdir(parents=True, exist_ok=True)
    doc = fitz.open(str(pdf_path))
    if pages is None:
        pages = list(range(1, doc.page_count + 1))
    paths = []
    for pn in tqdm(pages, desc='渲染页面'):
        out = img_dir / f'page_{pn:03d}.png'
        if not out.exists():
            pix = doc[pn - 1].get_pixmap(dpi=dpi)
            pix.save(str(out))
        paths.append(out)
    doc.close()
    return paths


def call_minimax(image_paths, batch_size):
    prompt = PROMPT_TEMPLATE.replace('{n}', str(batch_size))
    content = [{'type': 'text', 'text': prompt}]
    for p in image_paths:
        content.append({
            'type': 'image_url',
            'image_url': {'url': f'data:image/png;base64,{encode_image(p)}', 'detail': 'high'},
        })
    payload = {
        'model': MODEL,
        'messages': [{'role': 'user', 'content': content}],
        'max_tokens': 4000,
        'temperature': 0.1,
    }
    req = urllib.request.Request(
        f'{BASE_URL}/chat/completions',
        json.dumps(payload).encode(),
        {'Content-Type': 'application/json', 'Authorization': f'Bearer {API_KEY}'},
    )
    with urllib.request.urlopen(req, timeout=240) as resp:
        data = json.loads(resp.read().decode())
    text = data['choices'][0]['message']['content']
    text = strip_think(text)
    # try to find JSON array
    m = re.search(r'\[[\s\S]*\]', text)
    if m:
        raw = m.group(0)
        for candidate in (raw, fix_json_escapes(raw)):
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                pass
    # fallback: find all JSON objects
    objs = []
    for m in re.finditer(r'\{[\s\S]*?\}', text):
        raw = m.group(0)
        for candidate in (raw, fix_json_escapes(raw)):
            try:
                objs.append(json.loads(candidate))
                break
            except json.JSONDecodeError:
                pass
    return objs


def normalize_result(raw):
    """Normalize one parsed question dict."""
    if raw is None:
        return None
    qnum = raw.get('qnum')
    if qnum is not None:
        try:
            qnum = int(qnum)
        except Exception:
            qnum = None
    qtype = raw.get('type') or '计算题'
    content = clean_text(raw.get('content', ''))
    options = raw.get('options')
    sub_questions = raw.get('sub_questions')
    if isinstance(options, dict):
        opts = {k: clean_text(str(v)) for k, v in options.items() if k in 'ABCD'}
        options = opts if any(opts.values()) else None
    else:
        options = None
    if isinstance(sub_questions, list):
        sub_questions = [clean_text(str(s)) for s in sub_questions if s]
        if not sub_questions:
            sub_questions = None
    else:
        sub_questions = None
    return {
        'qnum': qnum,
        'type': qtype,
        'content': content,
        'options': options,
        'sub_questions': sub_questions,
    }


def build_880_section_map(cfg):
    """返回 page -> section 映射（按章节内出现的基础题/综合题/拓展题）."""
    doc = fitz.open(str(cfg['pdf']))
    section_map = {}
    section_kws = cfg['sections']
    for ch in cfg['chapter_ranges']:
        current = '基础题'
        for pn in range(ch['start'], ch['end'] + 1):
            text = doc[pn - 1].get_text()
            # 找到本页所有 section 关键字，取最后一个作为当前页所属 section
            found = []
            for kw in section_kws:
                for m in re.finditer(re.escape(kw), text):
                    found.append((m.start(), kw))
            if found:
                found.sort()
                current = found[-1][1]
            section_map[pn] = current
    doc.close()
    return section_map


def chapter_for_880_page(cfg, page):
    for ch in cfg['chapter_ranges']:
        if ch['start'] <= page <= ch['end']:
            return ch['name']
    return '未知章节'


def get_大学深埋_page_meta(cfg):
    """从现有 questions.json 读取大学深埋线代的每页元数据."""
    path = cfg.get('existing_questions')
    if not path or not path.exists():
        return {}
    data = json.loads(path.read_text(encoding='utf-8'))
    meta = {}
    for ch in data.get('chapters', []):
        for q in ch.get('questions', []):
            page = q.get('page')
            if page is not None and '线代' in ch.get('name', ''):
                meta[page] = {
                    'chapter': ch['name'],
                    'id': q.get('id'),
                    'uid': q.get('uid'),
                    'image_ref': q.get('image_ref'),
                    'answer_ref': q.get('answer_ref'),
                    'qnum': q.get('qnum'),
                }
    return meta


def crop_880_page_image(img_path, out_path):
    """去掉页眉页脚，按内容包围盒裁剪."""
    from PIL import Image
    import numpy as np
    import cv2
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img = Image.open(img_path)
    w, h = img.size
    # 先相对裁剪正文区域 0.10-0.90
    content = img.crop((0, int(h * 0.10), w, int(h * 0.90)))
    np_img = np.array(content)
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
    content.crop((x, y, x2, y2)).save(out_path, 'PNG')


def extract_bank(bank, batch_size=2, max_pages=None):
    cfg = BANK_CONFIG[bank]
    if not API_KEY:
        print('错误：未设置 MINIMAX_API_KEY', file=sys.stderr)
        sys.exit(1)

    # 确定要处理的页面
    if bank == '880-linear':
        doc = fitz.open(str(cfg['pdf']))
        total_pages = doc.page_count
        doc.close()
        pages = list(range(1, total_pages + 1))
        if max_pages:
            pages = pages[:max_pages]
        section_map = build_880_section_map(cfg)
        img_paths = render_pdf_pages(cfg['pdf'], cfg['img_dir'], pages)
    elif bank == '大学深埋线代':
        doc = fitz.open(str(cfg['pdf']))
        total_pages = doc.page_count
        doc.close()
        pages = list(range(1, total_pages + 1))
        if max_pages:
            pages = pages[:max_pages]
        page_meta = get_大学深埋_page_meta(cfg)
        img_paths = render_pdf_pages(cfg['pdf'], cfg['img_dir'], pages)
    else:
        raise ValueError(f'未知题库: {bank}')

    results_path = cfg['results']
    if results_path.exists():
        done = json.loads(results_path.read_text(encoding='utf-8'))
    else:
        done = []
    done_pages = {r['page'] for r in done if 'page' in r}

    # 分批处理
    batches = [pages[i:i + batch_size] for i in range(0, len(pages), batch_size)]
    for batch in tqdm(batches, desc=f'{bank} API 调用'):
        if all(p in done_pages for p in batch):
            continue
        batch_paths = [img_paths[p - 1] for p in batch]
        try:
            raw_items = call_minimax(batch_paths, len(batch))
            if not isinstance(raw_items, list):
                raw_items = [raw_items]
            # 补齐长度
            while len(raw_items) < len(batch):
                raw_items.append(None)
            for page, raw in zip(batch, raw_items):
                if page in done_pages:
                    continue
                normalized = normalize_result(raw)
                record = {'page': page, 'raw': raw, 'result': normalized}
                if normalized is None:
                    record['error'] = 'not a question'
                done.append(record)
                done_pages.add(page)
        except Exception as e:
            print(f'\n  batch {batch} failed: {e}', file=sys.stderr)
            # 单页重试
            for page in batch:
                if page in done_pages:
                    continue
                try:
                    raw_items = call_minimax([img_paths[page - 1]], 1)
                    raw = raw_items[0] if isinstance(raw_items, list) else raw_items
                    normalized = normalize_result(raw)
                    record = {'page': page, 'raw': raw, 'result': normalized}
                    done.append(record)
                    done_pages.add(page)
                    time.sleep(0.5)
                except Exception as e2:
                    print(f'    page {page} retry failed: {e2}', file=sys.stderr)
                    done.append({'page': page, 'error': str(e2)})
                    done_pages.add(page)
        # 增量保存
        write_json_atomic(results_path, done, indent=2)
        time.sleep(0.3)

    # 生成结构化 questions
    questions = []
    if bank == '880-linear':
        chapter_ids = {}
        for r in sorted(done, key=lambda x: x.get('page', 0)):
            page = r.get('page')
            res = r.get('result')
            if not res:
                continue
            ch = chapter_for_880_page(cfg, page)
            chapter_ids[ch] = chapter_ids.get(ch, 0) + 1
            qnum = cfg['first_qnum'] + page - 1
            # 生成裁剪图
            crop_rel = f'images/线代/page_{page:03d}.png'
            crop_path = cfg['crop_out_dir'] / f'page_{page:03d}.png'
            crop_880_page_image(img_paths[page - 1], crop_path)
            q = {
                'uid': f"880-{qnum}",
                'id': str(chapter_ids[ch]),
                'qnum': qnum,
                'type': res['type'],
                'content': res['content'],
                'options': res['options'],
                'sub_questions': res['sub_questions'],
                'page': page,
                'printed_page': None,
                'chapter': ch,
                'section': section_map.get(page, '基础题'),
                'has_image': True,
                'image_ref': {
                    'page': page,
                    'cropped': crop_rel,
                    'note': f'线代第{page}页题目截图',
                    'original_page': None,
                },
                'source': cfg['source'],
                'answer_ref': f'answer_crops/q{qnum}.png',
            }
            questions.append(q)
    elif bank == '大学深埋线代':
        for r in sorted(done, key=lambda x: x.get('page', 0)):
            page = r.get('page')
            res = r.get('result')
            if not res:
                continue
            meta = page_meta.get(page, {})
            qid = meta.get('id') or f'例{page}'
            ch = meta.get('chapter') or '线代 · 未知章节'
            img_ref = meta.get('image_ref')
            q = {
                'uid': meta.get('uid') or f'大学深埋-{ch}-{qid}-p{page}',
                'id': qid,
                'qnum': meta.get('qnum'),
                'type': res['type'],
                'content': res['content'],
                'options': res['options'],
                'sub_questions': res['sub_questions'],
                'page': page,
                'printed_page': None,
                'chapter': ch,
                'section': None,
                'has_image': bool(img_ref),
                'image_ref': img_ref,
                'source': cfg['source'],
                'answer_ref': meta.get('answer_ref'),
            }
            questions.append(q)

    write_json_atomic(cfg['out_json'], questions, indent=2)
    print(f'\n{bank}: 提取 {len(questions)} 题，保存到 {cfg["out_json"]}')
    return questions


def merge_into_full(bank):
    """把新提的线代题目合并回完整的 questions.json。"""
    if bank == '880-linear':
        full_path = ROOT / '880题' / 'questions.json'
        linear_path = BANK_CONFIG[bank]['out_json']
        linear_chapters = {ch['name'] for ch in BANK_CONFIG[bank]['chapter_ranges']}
    elif bank == '大学深埋线代':
        full_path = ROOT / '大学深埋' / 'questions.json'
        linear_path = BANK_CONFIG[bank]['out_json']
        linear_chapters = set()
        data = json.loads(full_path.read_text(encoding='utf-8'))
        for ch in data.get('chapters', []):
            if '线代' in ch.get('name', ''):
                linear_chapters.add(ch['name'])
    else:
        raise ValueError(f'未知题库: {bank}')

    full_data = json.loads(full_path.read_text(encoding='utf-8'))
    linear_qs = json.loads(linear_path.read_text(encoding='utf-8'))

    new_chapters = []
    kept_linear = set()
    for ch in full_data.get('chapters', []):
        if ch['name'] in linear_chapters:
            # 只取属于本章的新题
            qs = [q for q in linear_qs if q.get('chapter') == ch['name']]
            new_chapters.append({
                'name': ch['name'],
                'question_count': len(qs),
                'questions': qs,
            })
            kept_linear.add(ch['name'])
        else:
            new_chapters.append(ch)
    # 如果有未覆盖到的线代章节（理论上不应发生），直接追加
    if bank == '880-linear' and kept_linear != linear_chapters:
        for ch_name in linear_chapters - kept_linear:
            qs = [q for q in linear_qs if q.get('chapter') == ch_name]
            new_chapters.append({'name': ch_name, 'question_count': len(qs), 'questions': qs})

    full_data['chapters'] = new_chapters
    full_data['total_questions'] = sum(len(ch['questions']) for ch in new_chapters)
    write_json_atomic(full_path, full_data, indent=2)
    print(f'已合并回 {full_path}，总题数 {full_data["total_questions"]}')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--bank', choices=list(BANK_CONFIG.keys()), required=True)
    parser.add_argument('--batch-size', type=int, default=2)
    parser.add_argument('--max-pages', type=int, default=0, help='仅测试前 N 页')
    parser.add_argument('--merge', action='store_true', help='提取后合并到 questions.json')
    args = parser.parse_args()

    extract_bank(args.bank, batch_size=args.batch_size, max_pages=args.max_pages or None)
    if args.merge:
        merge_into_full(args.bank)


if __name__ == '__main__':
    main()
