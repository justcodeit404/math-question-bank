"""Extract 660 questions (高数/线代) using MiniMax-M3 vision model."""
import argparse
import base64
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common_660 import SubjectContext
from utils import write_json_atomic

API_KEY = os.environ.get('MINIMAX_API_KEY')
BASE_URL = os.environ.get('MINIMAX_BASE_URL', 'https://mimimax.cn/v1')
MODEL = 'MiniMax-M3'

CONFIG = {
    'math': {
        'meta_path': Path('temp/660_question_boxes_v2.json'),
        'results_path': Path('temp/660_extracted_minimax.json'),
        'build_questions': True,
        'questions_json': Path('660题/questions.json'),
    },
    'linear': {
        'meta_path': Path('temp/660_linear_question_boxes.json'),
        'results_path': Path('temp/660_linear_extracted_minimax.json'),
        'build_questions': False,
        'questions_json': Path('660题/questions_线代.json'),
    },
}

EXTRACTION_PROMPT = (
    '请从这张数学题目截图中提取题目。\n'
    '要求：\n'
    '1. 只返回 JSON，不要任何解释，不要输出思考过程\n'
    '2. 数学公式用 LaTeX 表示，用 $...$ 包裹\n'
    '3. 中文和数学公式之间不要加空格\n'
    '4. 填空题的空白处用 ____ 表示\n'
    '5. JSON 格式如下：{"qnum": 题号数字, "content": "题干文本", '
    '"options": {"A": "选项A文本", "B": "...", "C": "...", "D": "..."}}\n'
    '6. 如果是填空题没有选项，options 的四个值都留空字符串\n'
    '7. 如果截图不是题目，返回 {"qnum": null, "content": "", "options": {}}'
)

_VALID_JSON_ESCAPES = {'"', '\\', '/', 'b', 'f', 'n', 'r', 't'}


def strip_think(text):
    """Remove <think>...</think> reasoning blocks."""
    while '<think>' in text and '</think>' in text:
        start = text.find('<think>')
        end = text.find('</think>', start) + len('</think>')
        text = text[:start] + text[end:]
    return text.strip()


def fix_json_escapes(s):
    """Double backslashes that are not valid JSON escapes."""
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


def encode_image(image_path):
    with open(image_path, 'rb') as f:
        return base64.b64encode(f.read()).decode()


def call_minimax(image_path, retries=2):
    if not API_KEY:
        raise RuntimeError('MINIMAX_API_KEY environment variable not set')

    img_b64 = encode_image(image_path)
    payload = {
        'model': MODEL,
        'messages': [{
            'role': 'user',
            'content': [
                {'type': 'text', 'text': EXTRACTION_PROMPT},
                {
                    'type': 'image_url',
                    'image_url': {
                        'url': f'data:image/png;base64,{img_b64}',
                        'detail': 'high',
                    },
                },
            ],
        }],
        'max_tokens': 1500,
        'temperature': 0.1,
    }

    last_err = None
    for attempt in range(retries + 1):
        try:
            import urllib.request
            req = urllib.request.Request(
                f'{BASE_URL}/chat/completions',
                json.dumps(payload).encode(),
                {
                    'Content-Type': 'application/json',
                    'Authorization': f'Bearer {API_KEY}',
                },
            )
            with urllib.request.urlopen(req, timeout=120) as resp:
                result = json.loads(resp.read().decode())
            return result['choices'][0]['message']['content']
        except Exception as e:
            last_err = e
            if attempt < retries:
                time.sleep(2 ** attempt)
    raise last_err


def parse_result(text):
    text = strip_think(text)
    m = re.search(r'\{.*\}', text, re.DOTALL)
    if m:
        raw_json = m.group(0)
        for candidate in (raw_json, fix_json_escapes(raw_json)):
            try:
                data = json.loads(candidate)
                if isinstance(data, dict):
                    return {
                        'qnum': data.get('qnum'),
                        'content': str(data.get('content', '')).strip(),
                        'options': data.get('options') or {},
                    }
            except json.JSONDecodeError:
                pass
    return {'qnum': None, 'content': text, 'options': {}}


def process_one(item):
    crop_path = Path(item['crop'])
    try:
        raw = call_minimax(crop_path)
        parsed = parse_result(raw)
        return {
            'page': item['page'],
            'index': item['index'],
            'crop': str(crop_path),
            'raw': raw,
            **parsed,
        }
    except Exception as e:
        return {
            'page': item['page'],
            'index': item['index'],
            'crop': str(crop_path),
            'error': str(e),
        }


def save_results(path, results):
    write_json_atomic(path, results, indent=2)


def build_questions(results, ctx, out_path):
    questions = []
    for r in sorted(results, key=lambda x: (x['page'], x['index'])):
        if 'error' in r or not r.get('content'):
            continue
        qnum = r.get('qnum')
        if qnum is None:
            qnum = r['index']
        options = r.get('options') or {}
        normalized = {k: str(options.get(k, '')).strip() for k in ['A', 'B', 'C', 'D']}
        has_options = any(normalized.values())
        questions.append({
            'qnum': qnum,
            'content': r['content'],
            'options': normalized if has_options else None,
            'page': r['page'],
            'printed_page': ctx.pdf_to_printed(r['page']),
            'chapter': ctx.get_chapter(r['page']),
            'type': ctx.get_question_type(r['page']),
        })

    for idx, q in enumerate(questions, start=1):
        q['id'] = idx

    out_path.parent.mkdir(parents=True, exist_ok=True)
    write_json_atomic(out_path, questions, indent=2)
    print(f'Saved {out_path} ({len(questions)} questions)')
    ctx.generate_datajs(questions)


def main():
    parser = argparse.ArgumentParser(description='Extract 660 questions with MiniMax')
    parser.add_argument('--subject', choices=list(CONFIG.keys()), default='math',
                        help='高数 (math) 或 线代 (linear)')
    parser.add_argument('--build-questions', action='store_true',
                        help='Also build questions.json/data.js (math default)')
    args = parser.parse_args()

    cfg = CONFIG[args.subject]
    ctx = SubjectContext(args.subject)
    META_PATH = cfg['meta_path']
    RESULTS_PATH = cfg['results_path']
    should_build = cfg['build_questions'] or args.build_questions

    if not API_KEY:
        print('Error: set MINIMAX_API_KEY environment variable')
        return

    meta = json.loads(META_PATH.read_text(encoding='utf-8'))
    print(f'Loaded {len(meta)} crops from {META_PATH}')

    if RESULTS_PATH.exists():
        results = json.loads(RESULTS_PATH.read_text(encoding='utf-8'))
    else:
        results = []

    done_keys = {(r['page'], r['index']) for r in results if 'error' not in r or r.get('content')}
    todo = [item for item in meta if (item['page'], item['index']) not in done_keys]
    print(f'Already done: {len(done_keys)}, remaining: {len(todo)}')

    workers = int(os.environ.get('MINIMAX_WORKERS', '5'))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(process_one, item): item for item in todo}
        for i, future in enumerate(as_completed(futures), start=1):
            item = futures[future]
            try:
                res = future.result()
                results.append(res)
            except Exception as e:
                results.append({
                    'page': item['page'],
                    'index': item['index'],
                    'crop': item['crop'],
                    'error': str(e),
                })

            if i % 10 == 0:
                save_results(RESULTS_PATH, results)
                print(f'  Progress: {i}/{len(todo)}')

    save_results(RESULTS_PATH, results)
    print(f'Results saved to {RESULTS_PATH}')

    if should_build:
        build_questions(results, ctx, cfg['questions_json'])


if __name__ == '__main__':
    main()
