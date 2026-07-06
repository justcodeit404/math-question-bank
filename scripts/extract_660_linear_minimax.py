"""Extract 660 linear algebra questions using MiniMax-M3 vision model."""
import base64
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')

API_KEY = os.environ.get('MINIMAX_API_KEY')
BASE_URL = os.environ.get('MINIMAX_BASE_URL', 'https://mimimax.cn/v1')
MODEL = 'MiniMax-M3'

META_PATH = Path('temp/660_linear_question_boxes.json')
RESULTS_PATH = Path('temp/660_linear_extracted_minimax.json')

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


def strip_think(text):
    """Remove <think>...</think> reasoning blocks."""
    while '<think>' in text and '</think>' in text:
        start = text.find('<think>')
        end = text.find('</think>', start) + len('</think>')
        text = text[:start] + text[end:]
    return text.strip()


_VALID_JSON_ESCAPES = {'"', '\\', '/', 'b', 'f', 'n', 'r', 't'}


def fix_json_escapes(s):
    """Double backslashes that are not valid JSON escapes.

    Models sometimes return LaTeX commands like \\xi inside JSON strings
    without escaping the backslash. JSON only allows a fixed set of escapes,
    so we normalize the rest before parsing.
    """
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
    # Try to find JSON block
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
    # Fallback: treat entire text as content
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


def save_results(results):
    with open(RESULTS_PATH, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)


def main():
    if not API_KEY:
        print('Error: set MINIMAX_API_KEY environment variable')
        return

    meta = json.loads(META_PATH.read_text(encoding='utf-8'))
    print(f'Loaded {len(meta)} crops from {META_PATH}')

    # Resume from existing results
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
                save_results(results)
                print(f'  Progress: {i}/{len(todo)}')

    save_results(results)
    print(f'Results saved to {RESULTS_PATH}')


if __name__ == '__main__':
    main()
