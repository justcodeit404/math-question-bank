#!/usr/bin/env python3
"""从 880 线代篇 PDF 中提取题目，输出为 questions.json 格式。

源 PDF：880题/【横版】李林880数二线代篇做题本.pdf
"""
import json
import re
import sys
from pathlib import Path

import fitz

sys.path.insert(0, str(Path(__file__).resolve().parent))
from utils import write_json_atomic

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

ROOT = Path(__file__).resolve().parent.parent
PDF_PATH = ROOT / '880题' / '【横版】李林880数二线代篇做题本.pdf'
OUT_JSON = ROOT / '880题' / 'questions_linear.json'

HEADER_KEYWORDS = {'一、选择题', '二、填空题', '三、解答题', '四、证明题',
                   '基础题', '综合题', '拓展题', '解答题', '选择题', '填空题', '证明题'}

QUESTION_RE = re.compile(r'(?:^|\n)\s*\(?\s*(\d+)\)\s*')
UNNUMBERED_Q_RE = re.compile(r'(?:^|\n)\s*(?:[一二三四五六七八九十]+[、.])?(?:设|已知|证明|求|计算|若|记|下列|当|对于|曲线|函数|微分方程)')

CHAPTER_PRINT_RANGES = [
    {'name': '第七章 行列式', 'print_start': 1, 'print_end': 39},
    {'name': '第八章 矩阵', 'print_start': 40, 'print_end': 95},
    {'name': '第九章 向量', 'print_start': 96, 'print_end': 132},
    {'name': '第十章 线性方程组', 'print_start': 133, 'print_end': 186},
    {'name': '第十一章 相似矩阵', 'print_start': 187, 'print_end': 248},
    {'name': '第十二章 二次型', 'print_start': 249, 'print_end': 311},
]


def is_section_header(text):
    t = text.strip()
    if len(t) > 30:
        return False
    return any(kw in t for kw in HEADER_KEYWORDS)


def guess_question_type(text):
    if re.search(r'\n\s*A[\.．、]', text) or '(A)' in text or '（A）' in text:
        return '选择题'
    if '____' in text or 'underline' in text.lower():
        return '填空题'
    if text.strip().startswith('证明') or '证明:' in text or '证明：' in text:
        return '证明题'
    return '计算题'


def extract_options(text):
    options = {}
    pattern = r'[\n\s]*([A-D])[\.．、]\s*(.*?)(?=[\n\s]*[A-D][\.．、]|$)'
    matches = re.findall(pattern, text, re.DOTALL)
    if matches:
        for key, value in matches:
            options[key] = value.strip()
        first_opt = re.search(r'[\n\s]*[A-D][\.．、]', text)
        if first_opt:
            text = text[:first_opt.start()].strip()
    return options if options else None, text


def extract_sub_questions(text):
    subs = []
    pattern = r'\(([IiVv]+)\)\s*(.*?)(?=\([IiVv]+\)|$)'
    matches = re.findall(pattern, text, re.DOTALL)
    for _, content in matches:
        if content.strip():
            subs.append(content.strip())
    return subs if subs else None


def clean_text(text):
    text = re.sub(r'[-]', '', text)
    text = re.sub(r'[-]', '', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    lines = [line.strip() for line in text.split('\n')]
    text = '\n'.join(lines)
    text = re.sub(r'  +', ' ', text)
    return text.strip()


def extract_chapter_questions(pdf, ch_name, print_start, print_end):
    SECTION_KWS = ['基础题', '综合题', '拓展题']
    TOPIC_KWS = ['选择题', '填空题', '解答题']

    all_markers = []
    page_texts = {}
    page_offsets = {}
    offset = 0

    for pn in range(print_start - 1, print_end):
        text = pdf[pn].get_text()
        page_texts[pn] = text
        page_offsets[pn] = offset

        for kw in SECTION_KWS:
            for m in re.finditer(re.escape(kw), text):
                all_markers.append((offset + m.start(), 'section', kw, pn))
        for kw in TOPIC_KWS:
            for m in re.finditer(re.escape(kw), text):
                all_markers.append((offset + m.start(), 'topic', kw, pn))
        for m in QUESTION_RE.finditer(text):
            if m.group(1).isdigit() and int(m.group(1)) >= 1:
                all_markers.append((offset + m.start(), 'question', int(m.group(1)), pn))

        offset += len(text)

    all_markers.sort()

    current_section = '基础题'
    current_topic = '选择题'
    questions = []

    for abs_pos, mtype, val, pn in all_markers:
        if mtype == 'section':
            current_section = val
            current_topic = '选择题'
        elif mtype == 'topic':
            current_topic = val
            if current_section == '拓展题':
                local_pos = abs_pos - page_offsets[pn]
                text = page_texts[pn]
                header_end = text.find('\n', local_pos)
                if header_end == -1:
                    header_end = local_pos + len(val)
                after_header = text[header_end:].strip()
                if after_header and len(after_header) > 20:
                    next_q_marker = QUESTION_RE.search(text, header_end)
                    next_topic = None
                    for kw in TOPIC_KWS:
                        pos = text.find(kw, header_end + 1)
                        if pos != -1 and (next_topic is None or pos < next_topic):
                            next_topic = pos
                    if not next_q_marker or (next_q_marker.start() - header_end > 100):
                        q_end = len(text)
                        if next_topic and next_topic < q_end:
                            q_end = next_topic
                        if next_q_marker and next_q_marker.start() < q_end:
                            q_end = next_q_marker.start()
                        qtext = text[header_end:q_end].strip()
                        for tkw in TOPIC_KWS:
                            if qtext.startswith(tkw):
                                qtext = qtext[len(tkw):].strip()
                                break
                        if qtext and len(qtext) > 10 and not is_section_header(qtext):
                            qtext = clean_text(qtext)
                            qtype = guess_question_type(qtext)
                            options = None
                            if qtype == '选择题':
                                options, qtext = extract_options(qtext)
                            sub_questions = extract_sub_questions(qtext)
                            has_image = '如图' in qtext or '图所示' in qtext
                            question = {
                                'id': str(len(questions) + 1),
                                'type': qtype,
                                'content': qtext,
                                'page': pn + 1,
                                'section': current_section,
                            }
                            if options:
                                question['options'] = options
                            if sub_questions:
                                question['sub_questions'] = sub_questions
                            if has_image:
                                question['has_image'] = True
                            questions.append(question)
        elif mtype == 'question':
            local_pos = abs_pos - page_offsets[pn]
            text = page_texts[pn]

            next_q = None
            for npn in range(pn, print_end):
                ntext = page_texts[npn]
                search_start = local_pos + 1 if npn == pn else 0
                nm = QUESTION_RE.search(ntext, search_start)
                if nm:
                    next_q = (npn, nm.start())
                    break

            stop_pos = None
            for stop_abs, stype, sval, spn in all_markers:
                if stop_abs <= abs_pos:
                    continue
                if stype in ('section', 'topic'):
                    if spn == pn:
                        candidate = stop_abs - page_offsets[pn]
                        if stop_pos is None or candidate < stop_pos:
                            stop_pos = candidate
                    elif spn > pn:
                        break

            if next_q:
                q_end_page, q_end_local = next_q
                q_end = q_end_local if q_end_page == pn else len(text)
            else:
                q_end = len(text)

            if stop_pos is not None and stop_pos < q_end:
                q_end = stop_pos

            qtext = text[local_pos:q_end].strip()
            qtext = re.sub(r'^\s*\(?\s*\d+\)\s*', '', qtext).strip()

            if not qtext or len(qtext) < 5:
                continue
            if is_section_header(qtext):
                continue

            png_page = pn + 1
            qtext = clean_text(qtext)
            qtype = guess_question_type(qtext)

            options = None
            if qtype == '选择题':
                options, qtext = extract_options(qtext)

            sub_questions = extract_sub_questions(qtext)
            has_image = '如图' in qtext or '图所示' in qtext or '图(a)' in qtext

            question = {
                'id': str(len(questions) + 1),
                'type': qtype,
                'content': qtext,
                'page': png_page,
                'section': current_section,
            }
            if options:
                question['options'] = options
            if sub_questions:
                question['sub_questions'] = sub_questions
            if has_image:
                question['has_image'] = True

            questions.append(question)

    return questions


def main():
    pdf = fitz.open(str(PDF_PATH))
    print(f'PDF: {pdf.page_count} pages')

    chapter_map = {}
    for ch_cfg in CHAPTER_PRINT_RANGES:
        ch_name = ch_cfg['name']
        questions = extract_chapter_questions(pdf, ch_name, ch_cfg['print_start'], ch_cfg['print_end'])
        for q in questions:
            q['chapter'] = ch_name
        chapter_map[ch_name] = questions
        print(f'  {ch_name}: {len(questions)} questions')

    final_questions = []
    for ch_cfg in CHAPTER_PRINT_RANGES:
        final_questions.extend(chapter_map.get(ch_cfg['name'], []))

    # re-number within each chapter
    ids = {}
    for q in final_questions:
        ch = q.get('chapter', '')
        ids[ch] = ids.get(ch, 0) + 1
        q['id'] = str(ids[ch])

    HEADER_KWS_CLEAN = ['一、选择题', '二、填空题', '三、解答题', '四、证明题',
                        '综合题', '拓展题', '基础题', '解答题']
    FOOTER_PAT = re.compile(r'·\s*第\d+\s*页，共\d+\s*页\s*·\s*$')
    MERGE_PAT = re.compile(r'(拓展题|基础题|综合题)\s*[一二三四]、')

    cleaned = []
    for q in final_questions:
        c = q['content']
        c = FOOTER_PAT.sub('', c).rstrip()
        m = MERGE_PAT.search(c)
        if m:
            c = c[:m.start()].rstrip()
        for kw in HEADER_KWS_CLEAN:
            if c.endswith(kw):
                c = c[:-len(kw)].rstrip()
        q['content'] = c
        if len(c) < 5 or any(c.strip() == kw for kw in HEADER_KWS_CLEAN):
            continue
        if q.get('sub_questions'):
            q['sub_questions'] = [FOOTER_PAT.sub('', s).rstrip() for s in q['sub_questions']]
        cleaned.append(q)

    final_questions = cleaned

    # re-number again after cleaning
    ids = {}
    for q in final_questions:
        ch = q.get('chapter', '')
        ids[ch] = ids.get(ch, 0) + 1
        q['id'] = str(ids[ch])

    total = len(final_questions)
    print(f'\nTotal: {total} questions')
    for ch_cfg in CHAPTER_PRINT_RANGES:
        ch_qs = [q for q in final_questions if q['chapter'] == ch_cfg['name']]
        sec_counts = {}
        for q in ch_qs:
            s = q.get('section', '?')
            sec_counts[s] = sec_counts.get(s, 0) + 1
        sec_str = ', '.join(f'{k}:{v}' for k, v in sorted(sec_counts.items()))
        print(f'  {ch_cfg["name"]}: {len(ch_qs)} questions ({sec_str})')

    data = {'questions': final_questions}
    write_json_atomic(OUT_JSON, data, indent=2)
    print(f'\nSaved: {OUT_JSON}')
    pdf.close()


if __name__ == '__main__':
    main()
