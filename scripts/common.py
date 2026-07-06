"""Shared utilities for 880 question bank scripts."""
import json, os, re, sys, base64, time, urllib.request, io
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')

# --- Constants ---
BASE = Path(__file__).resolve().parent.parent / '880题'
PDF_PATH = BASE.parent / '【A4紧凑版】李林880数二高数篇做题本.pdf'
PDF_IMAGES = BASE / 'pdf_images'
QUESTIONS_JSON = BASE / 'questions.json'
DATAJS = BASE / 'math-bank' / 'data.js'
IMG_DIR = BASE / 'math-bank' / 'images'

API_KEY = os.environ.get('DASHSCOPE_API_KEY')
API_URL = 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions'

CHAPTER_NAMES = [
    '第一章 函数·极限·连续',
    '第二章 一元函数微分学',
    '第三章 一元函数积分学',
    '第四章 多元函数微分学',
    '第五章 二重积分',
    '第六章 微分方程',
]

# Printed page ranges (single source of truth)
CHAPTER_PRINT_RANGES = [
    {'name': '第一章 函数·极限·连续', 'print_start': 2, 'print_end': 13},
    {'name': '第二章 一元函数微分学', 'print_start': 14, 'print_end': 33},
    {'name': '第三章 一元函数积分学', 'print_start': 35, 'print_end': 58},
    {'name': '第四章 多元函数微分学', 'print_start': 59, 'print_end': 68},
    {'name': '第五章 二重积分', 'print_start': 69, 'print_end': 78},
    {'name': '第六章 微分方程', 'print_start': 79, 'print_end': 89},
]

# PNG page ranges derived from CHAPTER_PRINT_RANGES (png_page == printed_page)
CHAPTER_RANGES = {
    (ch['print_start'], ch['print_end']): ch['name']
    for ch in CHAPTER_PRINT_RANGES
}

BACKTICK = '`'

EXTRACTION_PROMPT_TEMPLATE = (
    '请从这张数学题库页面中提取所有题目。这是李林880数二高数篇的第{page}页。\n\n'
    '## 提取规则\n'
    '- 只提取顶层题号 (1), (2), (3)...，不要把子项 (I)(II)(III) 当成独立题目\n'
    '- 如果一道题有多个子问 (I)(II)(III)，将它们放在 sub_questions 数组中\n'
    '- sub_questions 中的元素必须是字符串，不要用对象\n\n'
    '## LaTeX 格式（严格遵守，否则渲染失败）\n'
    '所有数学内容必须用 $...$ 包裹。中文和数学公式之间不要加空格。\n\n'
    '必须用 LaTeX 命令，禁止 Unicode 数学符号：\n'
    '- 分式：$\\frac{a}{b}$，不要写 a/b\n'
    '- 上标：$x^{2}$, $e^{-x}$, $e^{\\frac{1}{x}}$（花括号不能省，不能用圆括号）\n'
    '- 下标：$a_{n}$, $x_{0}$, $f_{x}\'$（禁止 Unicode 下标 ₓ₀₁ 等）\n'
    '- 三角函数：$\\sin x$, $\\cos x$, $\\tan x$（禁止写 sinx, cosx）\n'
    '- 对数：$\\ln x$, $\\log_{2} x$（禁止写 lnx）\n'
    '- 极限：$\\lim_{x\\to 0}$, $\\lim_{n\\to\\infty}$\n'
    '- 求和/积分：$\\sum_{k=1}^{n}$, $\\int_{0}^{1}f(x)\\mathrm{d}x$（禁止 Σ ∫）\n'
    '- 根号：$\\sqrt{x}$, $\\sqrt[3]{x}$（禁止 √ 和 \\sqrt(x)）\n'
    '- 希腊字母：$\\alpha$, $\\pi$, $\\infty$, $\\partial$（禁止 α π ∞ ∂）\n'
    '- 符号：$\\leq$, $\\geq$, $\\to$, $\\cdot$（禁止 ≤ ≥ → ·）\n'
    '- 不等号：$\\leqslant$, $\\geqslant$（不要写 \\leqslant 时漏 slant）\n'
    '- 分段函数：$\\begin{cases} ... \\\\ ... \\end{cases}$\n'
    '- 填空题下划线：填空用 $\\underline{\\hspace{2cm}}$ 而非 _____\n\n'
    '## 输出格式\n'
    '每道题返回一个JSON对象，字段：\n'
    '- qnum: 顶层题号数字\n'
    '- type: "选择题"/"填空题"/"计算题"/"证明题"\n'
    '- content: 题目正文（数学内容用 $...$ 包裹，反斜杠双写为 \\\\）\n'
    '- options: 选择题返回 {"A":"...","B":"...","C":"...","D":"..."}，否则 null\n'
    '- sub_questions: 有子问时返回字符串数组，否则 null\n'
    '- has_image: 题目提到如图/图示/图(a) 等为 true，否则 false\n'
    '- section: "基础题"/"综合题"/"拓展题"\n\n'
    '请返回JSON数组，只返回JSON。'
)


VERIFICATION_PROMPT_TEMPLATE = (
    '你是数学题库校对员。检查下列 JSON 数组中每道题的 LaTeX 格式是否正确。\n\n'
    '## 检查项\n'
    '1. 数学公式必须用 $...$ 包裹（不能有裸公式）\n'
    '2. \\frac{...}{...} 花括号必须匹配\n'
    '3. 上标下标 ^{...} _{...} 花括号必须匹配\n'
    '4. \\begin{cases} 与 \\end{cases} 必须成对\n'
    '5. 子问题 (I)(II) 必须在 sub_questions 数组中\n'
    '6. 选择题必须有 options 对象（不是 list）\n\n'
    '## 返回\n'
    '若全部正确返回：{"ok": true}\n'
    '若有错误返回：{"ok": false, "fixes": [{"id": 题号, "content": "修正后的content", "options": {...}}]}\n\n'
    '原JSON：\n{payload}'
)


def get_chapter(png_page):
    """Map a page number to its chapter name."""
    for ch in CHAPTER_PRINT_RANGES:
        if ch['print_start'] <= png_page <= ch['print_end']:
            return ch['name']
    return '未知章节'


# Backward-compatible alias for rebuild_880.py
get_chapter_by_print = get_chapter


def fix_json_escapes(text):
    """Fix unescaped backslashes in JSON strings for LaTeX.
    Strategy: inside JSON strings, any \\X where X is a letter (a-z, A-Z)
    is treated as a LaTeX command and doubled to \\\\X."""
    result = []
    i = 0
    in_string = False
    while i < len(text):
        c = text[i]
        if c == '"' and (i == 0 or text[i - 1] != '\\'):
            in_string = not in_string
            result.append(c)
        elif c == '\\' and in_string and i + 1 < len(text):
            next_c = text[i + 1]
            if next_c in '"\\/':
                result.append(c)
            elif next_c == 'u' and i + 5 < len(text):
                hex_part = text[i + 2:i + 6]
                if all(h in '0123456789abcdefABCDEF' for h in hex_part):
                    result.append(c)
                else:
                    result.append('\\\\')
            elif next_c.isalpha():
                result.append('\\\\')
            else:
                result.append(c)
        else:
            result.append(c)
        i += 1
    return ''.join(result)


def strip_markdown_fences(text):
    """Remove ```json ... ``` fences from LLM response."""
    fence = BACKTICK * 3
    if text.startswith(fence):
        text = re.sub(r'^' + re.escape(fence) + r'\w*\n?', '', text)
        text = re.sub(r'\n?' + re.escape(fence) + r'$', '', text)
    return text.strip()


def parse_response(response_text):
    """Parse JSON array from API response, with fallback strategies."""
    if not response_text:
        return []

    text = strip_markdown_fences(response_text.strip())

    # Try strategies in order: direct, fix escapes, regex array, trailing commas
    strategies = [
        lambda t: json.loads(t),
        lambda t: json.loads(fix_json_escapes(t)),
        lambda t: json.loads(fix_json_escapes(
            m.group() if (m := re.search(r'\[.*\]', t, re.DOTALL)) else t)),
        lambda t: json.loads(re.sub(r',\s*([}\]])', r'\1', t)),
    ]

    data = None
    for strategy in strategies:
        try:
            data = strategy(text)
            if isinstance(data, list):
                break
            data = None
        except (json.JSONDecodeError, AttributeError):
            pass

    if not isinstance(data, list):
        return []

    # Normalize field names and sub_questions format
    normalized = []
    for q in data:
        nq = {
            'qnum': q.get('qnum') or q.get('num') or 0,
            'type': q.get('type') or '计算题',
            'content': q.get('content') or '',
            'options': q.get('options') or None,
            'has_image': bool(q.get('has_image', False)),
            'section': q.get('section') or '基础题',
        }
        subs = q.get('sub_questions')
        if subs and isinstance(subs, list):
            nq['sub_questions'] = [
                s if isinstance(s, str) else (s.get('content') or s.get('text') or str(s))
                for s in subs
            ] or None
        else:
            nq['sub_questions'] = None
        normalized.append(nq)

    return normalized


# Available models (sorted by capability):
# - qwen-vl-max       最强, 慢, 贵
# - qwen2.5-vl-72b    强, 中速
# - qwen-vl-plus      默认, 平衡
DEFAULT_VL_MODEL = 'qwen-vl-plus'


def call_vision_api(image_path, page_num, model=None):
    """Send page image to Qwen-VL and return parsed questions list."""
    if not API_KEY:
        raise RuntimeError(
            'DASHSCOPE_API_KEY environment variable is not set. '
            'Set it before running scripts that call the vision API.'
        )
    if model is None:
        model = DEFAULT_VL_MODEL
    with open(image_path, 'rb') as f:
        img_b64 = base64.b64encode(f.read()).decode()

    prompt = EXTRACTION_PROMPT_TEMPLATE.replace('{page}', str(page_num))

    payload = {
        'model': model,
        'messages': [{'role': 'user', 'content': [
            {'type': 'image_url', 'image_url': {'url': f'data:image/png;base64,{img_b64}'}},
            {'type': 'text', 'text': prompt},
        ]}],
        'max_tokens': 4096,
        'temperature': 0.1,
    }

    req = urllib.request.Request(API_URL, json.dumps(payload).encode(), {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {API_KEY}',
    })

    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            result = json.loads(resp.read().decode())
            content = result['choices'][0]['message']['content']
    except Exception as e:
        print(f'  API error: {e}')
        return []

    return parse_response(content)


def verify_extraction(questions, model=None):
    """第二轮验证：把抽取结果交给模型校对，返回修正后的题目。

    返回 (verified_questions, fix_count)。
    如果模型认为 ok，返回原 questions。
    否则把 fixes 应用到原 questions 并返回。
    """
    if model is None:
        model = DEFAULT_VL_MODEL

    # 只发题目内容，不要图
    minimal = []
    for q in questions:
        minimal.append({
            'id': q.get('id') or q.get('qnum'),
            'content': q.get('content', ''),
            'options': q.get('options'),
            'sub_questions': q.get('sub_questions'),
        })

    payload_text = json.dumps(minimal, ensure_ascii=False, indent=2)
    prompt = VERIFICATION_PROMPT_TEMPLATE.replace('{payload}', payload_text)

    payload = {
        'model': model,
        'messages': [{'role': 'user', 'content': prompt}],
        'max_tokens': 8000,
        'temperature': 0.0,
    }

    req = urllib.request.Request(API_URL, json.dumps(payload).encode(), {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {API_KEY}',
    })

    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            result = json.loads(resp.read().decode())
            content = result['choices'][0]['message']['content']
    except Exception as e:
        print(f'  Verify API error: {e}')
        return questions, 0

    data = parse_response(content)
    if not data or (isinstance(data, list) and len(data) == 0):
        return questions, 0
    if isinstance(data, dict):
        data = [data]

    # data[0] 是验证结果 {"ok": bool, "fixes": [...]}
    result_obj = data[0] if isinstance(data[0], dict) else data
    if not result_obj or result_obj.get('ok'):
        return questions, 0

    fixes = result_obj.get('fixes', [])
    if not fixes:
        return questions, 0

    # 应用 fixes
    fix_map = {str(f.get('id')): f for f in fixes}
    for q in questions:
        qid = str(q.get('id') or q.get('qnum'))
        if qid in fix_map:
            fix = fix_map[qid]
            if 'content' in fix and fix['content']:
                q['content'] = fix['content']
            if 'options' in fix and fix['options']:
                q['options'] = fix['options']

    return questions, len(fixes)


def generate_datajs(questions, output_path=DATAJS):
    """Generate data.js from questions list."""
    chapters = []
    for ch_name in CHAPTER_NAMES:
        ch_qs = [q for q in questions if q.get('chapter') == ch_name]
        if not ch_qs:
            continue
        chapters.append({
            'name': ch_name,
            'question_count': len(ch_qs),
            'questions': [
                {
                    'id': q['id'],
                    'type': q['type'],
                    'content': q['content'],
                    'page': q['page'],
                    **({'options': q['options']} if q.get('options') else {}),
                    'sub_questions': q.get('sub_questions'),
                    **({'has_image': True, 'image_ref': q['image_ref']}
                       if q.get('has_image') and q.get('image_ref') else {}),
                }
                for q in ch_qs
            ],
        })

    total = sum(len(ch['questions']) for ch in chapters)
    max_page = max(q['page'] for q in questions) if questions else 0
    bank = {
        'title': '李林880数二高数篇',
        'total_pages': max_page,
        'total_questions': total,
        'chapters': chapters,
    }

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write('const QUESTION_BANK = ')
        json.dump(bank, f, ensure_ascii=False, indent=2)
        f.write(';\n')
    print(f'Saved: {output_path} ({total} questions)')


def renumber_questions(questions):
    """Re-number questions sequentially within each chapter."""
    ids = {}
    for q in questions:
        ch = q.get('chapter', '')
        ids[ch] = ids.get(ch, 0) + 1
        q['id'] = str(ids[ch])


def clean_text(text):
    """Remove PUA characters and normalize whitespace."""
    text = re.sub(r'[-]', '', text)
    text = re.sub(r'[-]', '', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    lines = [line.strip() for line in text.split('\n')]
    text = '\n'.join(lines)
    text = re.sub(r'  +', ' ', text)
    return text.strip()


def extract_and_crop_figure(pdf, figure, question, padding=20):
    """Extract an embedded image from PDF, composite onto rendered page, crop, and save.
    Returns the image_ref dict on success, None on failure."""
    from PIL import Image

    IMG_DIR.mkdir(parents=True, exist_ok=True)
    scale = 200 / 72

    try:
        page = pdf[figure['printed_page'] - 1]
        # Reuse on-disk PNG if available, otherwise render from PDF
        page_png = PDF_IMAGES / f"page_{figure['png_page']:03d}.png"
        if page_png.exists():
            page_img = Image.open(page_png)
        else:
            pix = page.get_pixmap(dpi=200)
            page_img = Image.open(io.BytesIO(pix.tobytes('png')))

        # Extract and composite embedded image
        base = pdf.extract_image(figure['xref'])
        fig_img = Image.open(io.BytesIO(base['image']))
        r = figure['rect']
        px_left = int(r.x0 * scale)
        px_top = int(r.y0 * scale)
        px_right = int(r.x1 * scale)
        px_bottom = int(r.y1 * scale)
        fig_resized = fig_img.resize((px_right - px_left, px_bottom - px_top), Image.LANCZOS)
        page_img.paste(fig_resized, (px_left, px_top))

        # Crop with padding
        crop = page_img.crop((
            max(0, px_left - padding),
            max(0, px_top - padding),
            min(page_img.width, px_right + padding),
            min(page_img.height, px_bottom + padding),
        ))

        out_name = f"p{figure['png_page']:03d}_q{question['id']}.png"
        crop.save(IMG_DIR / out_name)

        return {
            'page': figure['png_page'],
            'cropped': f'images/{out_name}',
            'note': f'打印页{figure["printed_page"]}',
        }
    except Exception as e:
        print(f'  Q{question["id"]}: crop failed: {e}')
        return None


def scan_embedded_figures(pdf):
    """Scan all PDF pages for embedded images, return list of figure dicts."""
    figures = []
    for pn in range(pdf.page_count):
        for img_info in pdf[pn].get_images(full=True):
            xref = img_info[0]
            rects = pdf[pn].get_image_rects(xref)
            if rects:
                figures.append({
                    'printed_page': pn + 1,
                    'png_page': pn + 1,
                    'rect': rects[0],
                    'xref': xref,
                })
    return figures


def match_and_crop_figures(questions):
    """Match has_image questions to embedded PDF figures and crop them."""
    import fitz

    pdf = fitz.open(str(PDF_PATH))
    figures = scan_embedded_figures(pdf)
    print(f'Found {len(figures)} embedded images')

    img_questions = [q for q in questions if q.get('has_image')]
    print(f'Questions with has_image: {len(img_questions)}')

    # Pre-sort figures by page for efficient lookup
    figures_by_page = sorted(figures, key=lambda f: f['printed_page'])

    for q in img_questions:
        q_printed = q['page']  # page IS the printed page now

        # Find closest figure by page distance
        best = None
        best_dist = 999
        for fig in figures_by_page:
            dist = abs(fig['printed_page'] - q_printed)
            if dist < best_dist:
                best_dist = dist
                best = fig

        if best and best_dist <= 3:
            ref = extract_and_crop_figure(pdf, best, q)
            if ref:
                q['image_ref'] = ref
                print(f'  Q{q["id"]} page={q["page"]}: 图→{ref["cropped"]}')
            else:
                q['has_image'] = False

    pdf.close()
