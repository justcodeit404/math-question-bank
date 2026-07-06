"""Rebuild 880 questions.json from PDF using PyMuPDF text extraction."""
import fitz, json, re, sys, io
from pathlib import Path
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (
    BASE, PDF_PATH, PDF_IMAGES, QUESTIONS_JSON, DATAJS, IMG_DIR,
    CHAPTER_PRINT_RANGES, get_chapter_by_print, clean_text,
    generate_datajs, renumber_questions, match_and_crop_figures,
)
from utils import write_json_atomic


HEADER_KEYWORDS = {'一、选择题', '二、填空题', '三、解答题', '四、证明题',
                   '基础题', '综合题', '拓展题', '解答题', '选择题', '填空题', '证明题'}

# Match (N) or N) format question markers (some PDFs have missing opening paren)
QUESTION_RE = re.compile(r'(?:^|\n)\s*\(?\s*(\d+)\)\s*')
# Match unnumbered questions after topic headers in 拓展题 sections
UNNUMBERED_Q_RE = re.compile(r'(?:^|\n)\s*(?:[一二三四五六七八九十]+[、.]\s*)?(?:设|已知|证明|求|计算|若|记|下列|当|对于|曲线|函数|微分方程)')


def is_section_header(text):
    """Check if text is a section header, not a real question."""
    t = text.strip()
    if len(t) > 30:
        return False
    return any(kw in t for kw in HEADER_KEYWORDS)


def guess_question_type(text):
    if re.search(r'\n\s*A[\.\．、]', text) or '(A)' in text or '（A）' in text:
        return '选择题'
    if '____' in text or 'underline' in text.lower():
        return '填空题'
    if text.strip().startswith('证明') or '证明:' in text or '证明：' in text:
        return '证明题'
    return '计算题'


def extract_options(text):
    options = {}
    pattern = r'[\n\s]*([A-D])[\.\．、]\s*(.*?)(?=[\n\s]*[A-D][\.\．、]|$)'
    matches = re.findall(pattern, text, re.DOTALL)
    if matches:
        for key, value in matches:
            options[key] = value.strip()
        first_opt = re.search(r'[\n\s]*[A-D][\.\．、]', text)
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


def extract_chapter_questions(pdf, ch_name, print_start, print_end):
    """Extract all questions for a chapter with position-aware section tracking."""
    SECTION_KWS = ['基础题', '综合题', '拓展题']
    TOPIC_KWS = ['选择题', '填空题', '解答题']

    # Collect all pages' text and build a unified marker list
    all_markers = []  # (abs_pos, type, value, page_num)
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

    # Process markers in order
    current_section = '基础题'
    current_topic = '选择题'
    questions = []
    last_q_end = {}  # pn -> local_pos of last question end

    for abs_pos, mtype, val, pn in all_markers:
        if mtype == 'section':
            current_section = val
            current_topic = '选择题'
        elif mtype == 'topic':
            current_topic = val
            # Check for unnumbered questions after topic headers in 拓展题
            if current_section == '拓展题':
                local_pos = abs_pos - page_offsets[pn]
                text = page_texts[pn]
                # Find the end of the topic header line
                header_end = text.find('\n', local_pos)
                if header_end == -1:
                    header_end = local_pos + len(val)
                # Check if there's content after the header that looks like a question
                after_header = text[header_end:].strip()
                if after_header and len(after_header) > 20:
                    # Check if the next marker is NOT a (N) question
                    next_q_marker = QUESTION_RE.search(text, header_end)
                    next_topic = None
                    for kw in TOPIC_KWS:
                        pos = text.find(kw, header_end + 1)
                        if pos != -1 and (next_topic is None or pos < next_topic):
                            next_topic = pos
                    # If there's substantial content before the next numbered question
                    # or topic header, treat it as an unnumbered question
                    if not next_q_marker or (next_q_marker.start() - header_end > 100):
                        # Determine end of unnumbered question
                        q_end = len(text)
                        if next_topic and next_topic < q_end:
                            q_end = next_topic
                        if next_q_marker and next_q_marker.start() < q_end:
                            q_end = next_q_marker.start()

                        qtext = text[header_end:q_end].strip()
                        # Remove the topic header prefix
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

            # Find end of this question's text
            next_q = None
            for npn in range(pn, print_end):
                ntext = page_texts[npn]
                if npn == pn:
                    search_start = local_pos + 1
                else:
                    search_start = 0
                nm = QUESTION_RE.search(ntext, search_start)
                if nm:
                    next_q = (npn, nm.start())
                    break

            # Stop at section/topic headers
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
                if q_end_page == pn:
                    q_end = q_end_local
                else:
                    q_end = len(text)
            else:
                q_end = len(text)

            if stop_pos is not None and stop_pos < q_end:
                q_end = stop_pos

            qtext = text[local_pos:q_end].strip()

            # Clean the question number prefix (both (N) and N) formats)
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
        print_start = ch_cfg['print_start']
        print_end = ch_cfg['print_end']

        questions = extract_chapter_questions(pdf, ch_name, print_start, print_end)
        for q in questions:
            q['chapter'] = ch_name

        chapter_map[ch_name] = questions
        print(f'  {ch_name}: {len(questions)} questions')

    # Flatten and re-number
    final_questions = []
    for ch_cfg in CHAPTER_PRINT_RANGES:
        ch_qs = chapter_map.get(ch_cfg['name'], [])
        final_questions.extend(ch_qs)
    renumber_questions(final_questions)

    # Clean up
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

    renumber_questions(final_questions)
    match_and_crop_figures(final_questions)

    # Stats
    total = len(final_questions)
    img_count = sum(1 for q in final_questions if q.get('has_image'))
    print(f'\nTotal: {total} questions, {img_count} with figures')
    for ch_cfg in CHAPTER_PRINT_RANGES:
        ch_qs = [q for q in final_questions if q['chapter'] == ch_cfg['name']]
        ch_img = sum(1 for q in ch_qs if q.get('has_image'))
        sec_counts = {}
        for q in ch_qs:
            s = q.get('section', '?')
            sec_counts[s] = sec_counts.get(s, 0) + 1
        sec_str = ', '.join(f'{k}:{v}' for k, v in sorted(sec_counts.items()))
        print(f'  {ch_cfg["name"]}: {len(ch_qs)} questions ({sec_str}), {ch_img} figures')

    write_json_atomic(QUESTIONS_JSON, final_questions, indent=2)
    print(f'\nSaved: {QUESTIONS_JSON}')

    generate_datajs(final_questions)


if __name__ == '__main__':
    main()
