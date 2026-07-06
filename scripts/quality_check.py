#!/usr/bin/env python3
"""
题库质量检查器：自动扫描提取错误并生成可视化报告。

用法：
  python scripts/quality_check.py --book 880题
  python scripts/quality_check.py --book 1000题
  python scripts/quality_check.py --book 大学深埋
  python scripts/quality_check.py --book 880题 --fix-safe
"""

import argparse
import json
import re
import sys
from pathlib import Path
from urllib.parse import quote


def _brace_depth(s):
    depth = 0
    for ch in s:
        if ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth < 0:
                return -1
    return depth


def _split_math(text):
    """把文本拆成 (is_math, segment) 列表，按 $...$、$$...$$、\\(...\\)、\\[...\\] 分隔。"""
    segs = []
    i = 0
    while i < len(text):
        if text.startswith('$$', i):
            j = text.find('$$', i + 2)
            if j == -1:
                segs.append((False, text[i:]))
                break
            segs.append((False, text[i:i + 2]))
            segs.append((True, text[i + 2:j]))
            segs.append((False, text[j:j + 2]))
            i = j + 2
        elif text.startswith(r'\(', i):
            j = text.find(r'\)', i + 2)
            if j == -1:
                segs.append((False, text[i:]))
                break
            segs.append((False, text[i:i + 2]))
            segs.append((True, text[i + 2:j]))
            segs.append((False, text[j:j + 2]))
            i = j + 2
        elif text.startswith(r'\[', i):
            j = text.find(r'\]', i + 2)
            if j == -1:
                segs.append((False, text[i:]))
                break
            segs.append((False, text[i:i + 2]))
            segs.append((True, text[i + 2:j]))
            segs.append((False, text[j:j + 2]))
            i = j + 2
        elif text[i] == '$':
            j = text.find('$', i + 1)
            if j == -1:
                segs.append((False, text[i:]))
                break
            segs.append((False, text[i:i + 1]))
            segs.append((True, text[i + 1:j]))
            segs.append((False, text[j:j + 1]))
            i = j + 1
        else:
            start = i
            while i < len(text) and not (text.startswith('$$', i) or text.startswith(r'\(', i) or text.startswith(r'\[', i) or text[i] == '$'):
                i += 1
            segs.append((False, text[start:i]))
    return segs


def _non_math_segments(text):
    return [seg for is_math, seg in _split_math(text) if not is_math]


def _math_segments(text):
    return [seg for is_math, seg in _split_math(text) if is_math]


def _has_unbalanced_math_braces(text):
    """检查数学段内花括号是否配对。"""
    for seg in _math_segments(text):
        d = _brace_depth(seg)
        if d != 0:
            return True
    return False


def _check_missing_dollar(text):
    """检查是否有裸 LaTeX 命令出现在 $ 外部。"""
    commands = r'(?:sin|cos|tan|ln|log|arcsin|arccos|arctan|frac|sqrt|int|sum|lim|alpha|beta|gamma|pi|infty|leq|geq|neq|to|cdot|partial|infty)'
    pat = re.compile(r'(?<![\\])\\' + commands + r'\b')
    for seg in _non_math_segments(text):
        if seg.strip() and pat.search(seg):
            return True
    return False


def _check_malformed_frac(text):
    """检查 $...$ 内的 \frac 是否有两个参数。"""
    frac_re = re.compile(r'\\frac\s*\{')
    for seg in _math_segments(text):
        for m in frac_re.finditer(seg):
            start = m.end()
            depth = 1
            i = start
            while i < len(seg) and depth > 0:
                if seg[i] == '{':
                    depth += 1
                elif seg[i] == '}':
                    depth -= 1
                i += 1
            if depth != 0:
                return True
            # 第一个参数结束后必须是 {
            if i >= len(seg) or seg[i] != '{':
                return True
    return False


def _check_malformed_subscript(text):
    """检查 _{(_{0},_{1})} 这种错误下标。"""
    return bool(re.search(r'_\{\(_\{\d+\},_\{\d+\}\)\}', text))


def _fix_malformed_subscript(text):
    return re.sub(r'_\{\(_\{(\d+)\},_\{(\d+)\}\)\}', r'_{(\1,\2)}', text)


def _check_empty_subscript(text):
    """检查空下标 _{} 或 _{ }。"""
    return bool(re.search(r'_\{\s*\}', text))


def _check_dup_var(text):
    """检查 f(xx) 或 x x 这种明显重复（限定小写字母，排除二阶偏导下标 xx/yy、yy' 类导数）。"""
    for seg in _math_segments(text):
        # 跳过二阶偏导下标：_{xx}, _{yy}
        cleaned = re.sub(r'_\{?([a-z])\1\}?', '', seg)
        # 跳过 y y'、y y'' 这类导数写法（重复字母后紧跟 '）
        if re.search(r'(?<![a-z])([a-z])\1(?![a-z\'])', cleaned):
            return True
    return False


def _check_unicode_math_outside(text):
    """检查 $ 外部是否含 Unicode 数学符号。"""
    unicode_math = re.compile(r'[∫∑∏√∞≤≥≠→←⇒⇔αβγδεθλμπσφωΩ∂∆]')
    for seg in _non_math_segments(text):
        if unicode_math.search(seg):
            return True
    return False


def _check_pua(text):
    return bool(re.search(r'[\ue000-\uf8ff]', text))


def _strip_text_commands(seg):
    """去掉 \\text{...} 块，避免其中的中文被误报。"""
    return re.sub(r'\\text\{[^}]*\}', '', seg)


def _check_chinese_punct_in_math(text):
    """检查数学段内是否混入中文标点（$ 未闭合或提取错乱）。"""
    punct = re.compile(r'[，。；：？！“”‘’（）【】《》]')
    for seg in _math_segments(text):
        if punct.search(_strip_text_commands(seg)):
            return True
    return False


def _check_relation_at_group_start(text):
    """检查 \frac{...}{...} 或 {...} 内是否以关系运算符开头（提取错误信号）。"""
    # 用 \b 确保不会把 \left 里的 \le 误判成关系运算符 \le
    rel_ops = r'(?:\\leq\\b|\\geq\\b|\\le\\b|\\ge\\b|=|<|>|\\neq\\b|\\equiv\\b|\\approx\\b)'
    # 任何 { 后直接跟关系运算符
    pat = re.compile(r'\{\s*' + rel_ops)
    for seg in _math_segments(text):
        if pat.search(seg):
            return True
    return False


def _check_chinese_in_math(text):
    """检查数学段内是否混入中文字符（通常是 $ 未闭合导致）。"""
    chinese = re.compile(r'[\u4e00-\u9fff]')
    for seg in _math_segments(text):
        if chinese.search(_strip_text_commands(seg)):
            return True
    return False


def check_text(text):
    """返回 [(code, severity, desc, fix_fn), ...]"""
    text = str(text) if text is not None else ''
    issues = []
    if text.count('$') % 2 != 0:
        issues.append(('unbalanced_dollars', 'critical', '$ 数量为奇数，数学模式不闭合', None))
    if _has_unbalanced_math_braces(text):
        issues.append(('unbalanced_braces', 'critical', 'LaTeX 花括号不配对', None))
    if _check_missing_dollar(text):
        issues.append(('missing_dollar', 'critical', 'LaTeX 命令出现在 $ 外部', None))
    if _check_malformed_frac(text):
        issues.append(('malformed_frac', 'critical', '\\frac 结构不完整', None))
    if _check_malformed_subscript(text):
        issues.append(('malformed_subscript', 'critical', '下标被错误拆分成 _{(_{0},_{1})}', _fix_malformed_subscript))
    if _check_empty_subscript(text):
        issues.append(('empty_subscript', 'warning', '存在空下标 _{}', None))
    if _check_dup_var(text):
        issues.append(('duplicated_var', 'warning', '疑似重复变量，如 f(xx) 或 x x', None))
    if _check_unicode_math_outside(text):
        issues.append(('unicode_math', 'warning', '$ 外部含 Unicode 数学符号', None))
    if _check_pua(text):
        issues.append(('pua_chars', 'critical', '含 PUA/私有区字符', None))
    if _check_chinese_in_math(text):
        issues.append(('chinese_in_math', 'critical', '数学段内混入中文（$ 可能未闭合）', None))
    if _check_chinese_punct_in_math(text):
        issues.append(('chinese_punct_in_math', 'critical', '数学段内混入中文标点', None))
    if _check_relation_at_group_start(text):
        issues.append(('relation_at_start', 'critical', '分组/分式以关系运算符开头', None))
    return issues


def load_questions(path):
    data = json.loads(path.read_text(encoding='utf-8'))
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and 'chapters' in data:
        flat = []
        for ch in data['chapters']:
            for q in ch.get('questions', []):
                q['_chapter'] = ch.get('name', '')
                flat.append(q)
        return flat
    raise ValueError('questions.json must be a list or {chapters: [...]}')


def check_question(q):
    all_issues = []
    texts = [('content', q.get('content', ''))]
    opts = q.get('options') or {}
    if isinstance(opts, dict):
        for k, v in opts.items():
            texts.append((f'option:{k}', v))
    elif isinstance(opts, list):
        all_issues.append(('options_type', 'critical', '选择题 options 是 list 而非 dict', None, None, None))

    for field, text in texts:
        for code, sev, desc, fix in check_text(text):
            all_issues.append((code, sev, desc, field, text, fix))

    if q.get('type') == '选择题':
        if not opts:
            all_issues.append(('missing_options', 'critical', '选择题缺少选项', None, None, None))
        elif isinstance(opts, dict) and set(opts.keys()) != {'A', 'B', 'C', 'D'}:
            all_issues.append(('wrong_options', 'warning', f'选择题选项键为 {list(opts.keys())}', None, None, None))

    if q.get('type') == '填空题':
        content = q.get('content', '')
        blank_markers = [
            r'___+',          # ___ 或 ____
            r'\\_\\_+',       # \_\_ 或 \_\_\_\_
            r'\\underline\{', # \underline{...}
            r'\\quad',        # \quad / \qquad
            r'（\s*）',        # （  ）
            r'\(\s*\)',        # (  )
            r'□',             # 方框
        ]
        if not any(re.search(m, content) for m in blank_markers):
            all_issues.append(('missing_blank', 'warning', '填空题没有明显空格标记', None, None, None))

    return all_issues


def build_report(questions, book_dir):
    report = []
    for q in questions:
        issues = check_question(q)
        if not issues:
            continue
        img_ref = q.get('image_ref') or {}
        crop = img_ref.get('cropped', '')
        crop_path = book_dir / 'math-bank' / crop if crop else None
        page = q.get('page')
        report.append({
            'id': q.get('id'),
            'page': page,
            'chapter': q.get('chapter') or q.get('_chapter', ''),
            'type': q.get('type'),
            'content': q.get('content', ''),
            'options': q.get('options'),
            'image_ref': img_ref,
            'crop_exists': crop_path.exists() if crop_path else False,
            'issues': [
                {
                    'code': iss[0],
                    'severity': iss[1],
                    'desc': iss[2],
                    'field': iss[3] if len(iss) > 3 else None,
                    'text': iss[4] if len(iss) > 4 else None,
                    'has_fix': iss[5] is not None if len(iss) > 5 else False,
                }
                for iss in issues
            ]
        })
    return report


def apply_safe_fixes(questions):
    fixed = 0
    for q in questions:
        for field in ['content']:
            text = q.get(field, '')
            new_text = _fix_malformed_subscript(text)
            if new_text != text:
                q[field] = new_text
                fixed += 1
        opts = q.get('options')
        if isinstance(opts, dict):
            for k, v in opts.items():
                if not isinstance(v, str):
                    continue
                new_v = _fix_malformed_subscript(v)
                if new_v != v:
                    opts[k] = new_v
                    fixed += 1
    return fixed


def generate_html(report, book_dir, output_path, book_name):
    total = len(report)
    by_sev = {'critical': 0, 'warning': 0, 'info': 0}
    by_code = {}
    for item in report:
        for iss in item['issues']:
            by_sev[iss['severity']] = by_sev.get(iss['severity'], 0) + 1
            by_code[iss['code']] = by_code.get(iss['code'], 0) + 1

    rows = []
    for item in report:
        issues_html = ''.join(
            f'<span class="badge {iss["severity"]}" data-code="{iss["code"]}">{iss["severity"]}: {iss["desc"]}</span>'
            for iss in item['issues']
        )
        crop = item['image_ref'].get('cropped', '')
        img_url = f'{quote(book_name)}/math-bank/{quote(crop)}' if crop else ''
        img_tag = f'<img src="{img_url}" loading="lazy" onclick="zoom(this)" title="点击查看原图">' if img_url else '<span class="muted">无裁剪图</span>'

        opts = item.get('options') or {}
        options_html = ''
        if isinstance(opts, dict):
            options_html = '<div class="options">' + ''.join(
                f'<div class="opt"><b>{k}:</b> <span class="latex">{_escape(v)}</span></div>'
                for k, v in opts.items()
            ) + '</div>'

        rows.append(f'''
        <tr data-codes="{' '.join(iss['code'] for iss in item['issues'])}">
          <td class="qid">#{item["id"]}<br><small>P{item["page"]}</small></td>
          <td class="preview">
            <div class="latex">{_escape(item["content"])}</div>
            {options_html}
            <div class="issues">{issues_html}</div>
            <details><summary>原始文本</summary><pre>{_escape(item["content"])}</pre></details>
          </td>
          <td class="crop">{img_tag}</td>
        </tr>
        ''')

    code_filters = ''.join(
        f'<button onclick="filterCode(\'{code}\')">{code} ({cnt})</button>'
        for code, cnt in sorted(by_code.items(), key=lambda x: -x[1])
    )

    html = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>题库质量报告 - {book_name}</title>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/katex.min.css">
<script src="https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/katex.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/contrib/auto-render.min.js"></script>
<style>
:root {{ --bg:#f8f9fa; --surface:#fff; --text:#1f2937; --muted:#6b7280; --border:#e5e7eb; --accent:#2563eb; --accent-light:#3b82f6; --danger:#dc2626; --warning:#d97706; --success:#16a34a; }}
body {{ font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif; background:var(--bg); color:var(--text); margin:0; }}
header {{ background:var(--surface); border-bottom:1px solid var(--border); padding:20px 32px; display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:12px; }}
h1 {{ font-size:1.3rem; margin:0; }}
.summary {{ display:flex; gap:16px; flex-wrap:wrap; }}
.stat {{ background:var(--surface); border:1px solid var(--border); border-radius:8px; padding:12px 18px; min-width:100px; }}
.stat b {{ display:block; font-size:1.3rem; }}
.stat small {{ color:var(--muted); }}
main {{ padding:24px 32px; max-width:1600px; margin:0 auto; }}
.filters {{ display:flex; gap:10px; margin-bottom:16px; flex-wrap:wrap; align-items:center; }}
.filters button {{ padding:6px 14px; border:1px solid var(--border); background:var(--surface); border-radius:6px; cursor:pointer; font-size:.85rem; }}
.filters button.active {{ background:var(--accent); color:#fff; border-color:var(--accent); }}
table {{ width:100%; border-collapse:collapse; background:var(--surface); border-radius:8px; overflow:hidden; box-shadow:0 1px 3px rgba(0,0,0,.05); }}
th, td {{ padding:14px; border-bottom:1px solid var(--border); vertical-align:top; text-align:left; }}
th {{ background:#f3f4f6; font-weight:600; }}
.qid {{ width:70px; white-space:nowrap; }}
.preview {{ min-width:300px; }}
.crop {{ width:320px; }}
.crop img {{ max-width:300px; max-height:220px; border:1px solid var(--border); border-radius:6px; cursor:zoom-in; object-fit:contain; }}
.badge {{ display:inline-block; padding:3px 8px; border-radius:4px; font-size:.75rem; margin:2px 4px 2px 0; cursor:pointer; }}
.badge.critical {{ background:#fee2e2; color:#991b1b; }}
.badge.warning {{ background:#fef3c7; color:#92400e; }}
.badge.info {{ background:#dbeafe; color:#1e40af; }}
.options {{ margin-top:8px; padding-left:8px; border-left:3px solid var(--border); }}
.opt {{ margin:4px 0; }}
.muted {{ color:var(--muted); }}
pre {{ background:#f3f4f6; padding:8px; border-radius:6px; overflow:auto; font-size:.8rem; margin-top:8px; }}
#lightbox {{ display:none; position:fixed; inset:0; background:rgba(0,0,0,.85); z-index:1000; justify-content:center; align-items:center; }}
#lightbox img {{ max-width:90vw; max-height:90vh; }}
#lightbox .close {{ position:absolute; top:20px; right:30px; color:#fff; font-size:2rem; cursor:pointer; }}
</style>
</head>
<body>
<header>
  <div><h1>题库质量报告：{book_name}</h1><p>共 {total} 道题疑似存在问题</p></div>
  <div class="summary">
    <div class="stat"><b>{by_sev.get('critical',0)}</b><small>严重</small></div>
    <div class="stat"><b>{by_sev.get('warning',0)}</b><small>警告</small></div>
    <div class="stat"><b>{by_sev.get('info',0)}</b><small>提示</small></div>
  </div>
</header>
<main>
  <div class="filters">
    <button class="active" onclick="filter('all')">全部</button>
    <button onclick="filter('critical')">严重</button>
    <button onclick="filter('warning')">警告</button>
    {code_filters}
  </div>
  <table>
    <thead><tr><th>题号</th><th>提取文本（KaTeX 渲染）</th><th>裁剪原图</th></tr></thead>
    <tbody>
      {''.join(rows)}
    </tbody>
  </table>
</main>
<div id="lightbox" onclick="this.style.display='none'"><span class="close">&times;</span><img id="lb-img"></div>
<script>
function filter(sev) {{
  document.querySelectorAll('.filters button').forEach(b=>b.classList.remove('active'));
  event.target.classList.add('active');
  document.querySelectorAll('tbody tr').forEach(tr=>{{
    if (sev==='all') {{ tr.style.display=''; return; }}
    const issues = tr.getAttribute('data-codes');
    tr.style.display = issues && issues.includes(sev) ? '' : 'none';
  }});
  renderMathInElement(document.body, {{delimiters:[{{left:'$$',right:'$$',display:true}},{{left:'$',right:'$',display:false}}],throwOnError:false}});
}}
function filterCode(code) {{ filter(code); }}
function zoom(img) {{
  document.getElementById('lb-img').src = img.src;
  document.getElementById('lightbox').style.display = 'flex';
}}
document.addEventListener("DOMContentLoaded", function() {{
  renderMathInElement(document.body, {{delimiters:[{{left:'$$',right:'$$',display:true}},{{left:'$',right:'$',display:false}}],throwOnError:false}});
}});
</script>
</body>
</html>
'''
    output_path.write_text(html, encoding='utf-8')


def _escape(s):
    if s is None:
        return ''
    s = str(s)
    return (s
            .replace('&', '&amp;')
            .replace('<', '&lt;')
            .replace('>', '&gt;'))


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--book', default='880题', help='题库目录名')
    p.add_argument('--fix-safe', action='store_true', help='自动修复有安全 fix 规则的问题')
    p.add_argument('--output', default='temp/quality_report.html', help='HTML 报告输出路径')
    args = p.parse_args()

    root = Path(__file__).resolve().parent.parent
    book_dir = root / args.book
    questions_path = book_dir / 'questions.json'
    if not questions_path.exists():
        # 兼容非标准命名
        for alt in book_dir.glob('*.json'):
            if '题目' in alt.name or 'questions' in alt.name.lower():
                questions_path = alt
                break
    if not questions_path.exists():
        print(f'[错误] 在 {book_dir} 找不到题目 JSON 文件', file=sys.stderr)
        sys.exit(1)

    original_data = json.loads(questions_path.read_text(encoding='utf-8'))
    questions = load_questions(questions_path)

    if args.fix_safe:
        fixed = apply_safe_fixes(questions)
        print(f'[自动修复] {fixed} 处')
        backup = questions_path.with_suffix('.json.bak.quality_fix')
        import shutil
        shutil.copy2(questions_path, backup)
        if isinstance(original_data, list):
            questions_path.write_text(json.dumps(questions, ensure_ascii=False, indent=2), encoding='utf-8')
        else:
            from crop_question_regions import save_questions
            save_questions(questions_path, questions, original_data)
        print(f'[备份] {backup}')

    report = build_report(questions, book_dir)
    output_path = root / args.output
    output_path.parent.mkdir(parents=True, exist_ok=True)
    generate_html(report, book_dir, output_path, args.book)

    print(f'[完成] 扫描 {len(questions)} 道题，发现 {len(report)} 道疑似问题')
    print(f'[报告] {output_path}')


if __name__ == '__main__':
    main()
