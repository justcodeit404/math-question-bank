"""Re-process failed/empty 660 extractions and drop answer-page false positives."""
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')

sys.path.insert(0, str(Path(__file__).resolve().parent))
from extract_660_minimax import call_minimax, parse_result, RESULTS_PATH, QUESTIONS_JSON
from common_660 import get_chapter, get_question_type, pdf_to_printed, generate_datajs

RETRY_PROMPT = (
    '请只从图片中提取题目文本，不要解答、不要分析、不要思考。\n'
    '只返回 JSON，不要任何解释。格式：'
    '{"qnum": 题号数字, "content": "题干文本", '
    '"options": {"A": "", "B": "", "C": "", "D": ""}}\n'
    '填空题没有选项时，options 全部为空字符串。'
)


def call_retry(image_path):
    import base64, json, os, urllib.request

    key = os.environ.get('MINIMAX_API_KEY')
    base = os.environ.get('MINIMAX_BASE_URL', 'https://mimimax.cn/v1')
    with open(image_path, 'rb') as f:
        b64 = base64.b64encode(f.read()).decode()
    payload = {
        'model': 'MiniMax-M3',
        'messages': [{
            'role': 'user',
            'content': [
                {'type': 'text', 'text': RETRY_PROMPT},
                {
                    'type': 'image_url',
                    'image_url': {
                        'url': f'data:image/png;base64,{b64}',
                        'detail': 'high',
                    },
                },
            ],
        }],
        'max_tokens': 1500,
        'temperature': 0.0,
    }
    req = urllib.request.Request(
        f'{base}/chat/completions',
        json.dumps(payload).encode(),
        {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {key}',
        },
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        result = json.loads(resp.read().decode())
    return result['choices'][0]['message']['content']


def main():
    results = json.loads(RESULTS_PATH.read_text(encoding='utf-8'))
    print(f'Loaded {len(results)} results')

    # Drop answer-page false positives (page 332 is the only known outlier)
    before = len(results)
    results = [r for r in results if r.get('page') != 332]
    if len(results) < before:
        print(f'Dropped {before - len(results)} answer-page item(s)')

    # Retry errors and empty content
    retry_items = [r for r in results if 'error' in r or not r.get('content')]
    print(f'Retrying {len(retry_items)} item(s)')

    for r in retry_items:
        try:
            raw = call_retry(r['crop'])
            parsed = parse_result(raw)
            r['raw'] = raw
            r['qnum'] = parsed.get('qnum')
            r['content'] = parsed.get('content', '')
            r['options'] = parsed.get('options') or {}
            if 'error' in r:
                del r['error']
            print(f"  OK page {r['page']} q{r['index']}: {r['content'][:60]}")
        except Exception as e:
            r['error'] = str(e)
            print(f"  FAIL page {r['page']} q{r['index']}: {e}")

    RESULTS_PATH.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')

    # Rebuild questions.json
    questions = []
    for r in sorted(results, key=lambda x: (x['page'], x['index'])):
        if 'error' in r or not r.get('content'):
            continue
        qnum = r.get('qnum') or r['index']
        options = r.get('options') or {}
        normalized = {k: str(options.get(k, '')).strip() for k in ['A', 'B', 'C', 'D']}
        has_options = any(normalized.values())
        questions.append({
            'qnum': qnum,
            'content': r['content'],
            'options': normalized if has_options else None,
            'page': r['page'],
            'printed_page': pdf_to_printed(r['page']),
            'chapter': get_chapter(r['page']),
            'type': get_question_type(r['page']),
        })

    for idx, q in enumerate(questions, start=1):
        q['id'] = idx

    QUESTIONS_JSON.write_text(json.dumps(questions, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'Saved {QUESTIONS_JSON} ({len(questions)} questions)')
    generate_datajs(questions)


if __name__ == '__main__':
    main()
