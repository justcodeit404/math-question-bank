#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = ROOT.parent.parent
BOOK = ROOT / "李林六套卷"
WORK = REPO_ROOT / "temp" / "linliu6"
QUESTION_OCR = WORK / "questions-ocr"
ANSWER_OCR = WORK / "answers-ocr"
LAYOUT = WORK / "layout"
SET_NAMES = "一二三四五六"
QUESTION_RE = re.compile(r"(?m)^(?:#{1,6}\s*)?(\d{1,2})\s*[.．]\s*")
OPTION_RE = re.compile(r"(?m)(^|\s)([ABCD])\s*[.．、]\s*")
SUB_RE = re.compile(r"(?m)^\s*[（(]([ⅠⅡ一二三四五六\d]+)[）)]\s*")
SET_TITLE_RE = re.compile(r"第([一二三四五六])套")
ANSWER_TITLE_RE = re.compile(r"第([一二三四五六])套.*答案")
DUPLICATE_PAGES = {38}


def page_file(kind: str, page: int) -> Path:
    directory = QUESTION_OCR if kind == "questions" else ANSWER_OCR
    prefix = "李林六套卷（数二）" if kind == "questions" else "李林六套卷（数二）解析"
    return directory / f"{prefix}-p{page:03d}.md"


def discover_sets(kind: str) -> dict[int, int]:
    directory = QUESTION_OCR if kind == "questions" else ANSWER_OCR
    prefix = "李林六套卷（数二）" if kind == "questions" else "李林六套卷（数二）解析"
    pattern = SET_TITLE_RE if kind == "questions" else ANSWER_TITLE_RE
    found = {}
    for path in sorted(directory.glob(f"{prefix}-p*.md")):
        page = int(re.search(r"-p(\d+)\.md$", path.name).group(1))
        for match in pattern.finditer(path.read_text(encoding="utf-8")):
            found.setdefault(SET_NAMES.index(match.group(1)) + 1, page)
    expected = set(range(1, 7))
    if set(found) != expected or len(set(found.values())) != 6:
        raise ValueError(f"{kind} 套标题异常：{found}")
    if list(found.values()) != sorted(found.values()):
        raise ValueError(f"{kind} 套标题页未按顺序出现：{found}")
    return found


def normalize_math(text: str) -> str:
    text = text.replace(r"\(", "$").replace(r"\)", "$")
    text = text.replace(r"\[", "$$").replace(r"\]", "$$")
    text = re.sub(r"\\left\\\{\s*(?=\\begin\{array\})", lambda _: r"\left\lbrace", text)
    text = re.sub(r"(\\begin\{array\}\{)([lcr]{2,})(\})", lambda match: match[1] + " ".join(match[2]) + match[3], text)
    text = re.sub(r"[（(]本题满分\s*\d+\s*分[）)]", "", text)
    text = re.sub(r"(?m)^#{1,6}\s*[一二三]\s*[、,，].*$", "", text)
    text = re.sub(r"(?m)^2027\s*考研数学冲刺预测.*$", "", text)
    return "\n".join(line.rstrip() for line in text.splitlines()).strip()


def parse_choice(text: str) -> tuple[str, dict[str, str]]:
    matches = [m for m in OPTION_RE.finditer(text) if m.group(2) in "ABCD"]
    labels = [match.group(2) for match in matches]
    if labels != list("ABCD"):
        raise ValueError(f"选项不是连续 A-D：{labels}；{text[:160]}")
    content = text[: matches[0].start()].strip()
    options = {}
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        options[match.group(2)] = text[match.end() : end].strip()
    return content, options


def split_subquestions(text: str) -> tuple[str, list[str] | None]:
    matches = list(SUB_RE.finditer(text))
    if not matches:
        return text, None
    expected = ["Ⅰ", "Ⅱ", "Ⅲ", "Ⅳ", "Ⅴ", "Ⅵ"][: len(matches)] if matches[0].group(1) in "ⅠⅡⅢⅣⅤⅥ" else [str(i) for i in range(1, len(matches) + 1)]
    if [match.group(1) for match in matches] != expected:
        return text, None
    content = text[: matches[0].start()].strip()
    subs = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        subs.append(text[match.end() : end].strip())
    return content, subs


def question_ranges() -> dict[int, tuple[int, int]]:
    starts = discover_sets("questions")
    result = {}
    for set_index in range(1, 7):
        end = starts[set_index + 1] - 1 if set_index < 6 else 31
        result[set_index] = (starts[set_index], end)
    return result


def answer_ranges() -> dict[int, tuple[int, int]]:
    starts = discover_sets("answers")
    return {
        set_index: (starts[set_index], starts[set_index + 1] - 1 if set_index < 6 else 74)
        for set_index in range(1, 7)
    }


def answer_keys(set_index: int, start: int, end: int) -> dict[int, str]:
    text = "\n".join(
        page_file("answers", page).read_text(encoding="utf-8")
        for page in range(start, end + 1)
    )
    pattern = re.compile(r"(?m)^(?:#{1,6}\s*)?(\d{1,2})\s*[.．、]?\s*答\s*案\s*([A-D])\b")
    keys = {}
    for match in pattern.finditer(text):
        number = int(match.group(1))
        if 1 <= number <= 10:
            keys.setdefault(number, match.group(2))
    if sorted(keys) != list(range(1, 11)):
        raise ValueError(f"第{SET_NAMES[set_index - 1]}套选择题答案异常：{sorted(keys)}")
    return keys


def parse_set(set_index: int, start: int, end: int) -> list[dict]:
    texts = []
    page_offsets = []
    cursor = 0
    for page in range(start, end + 1):
        text = normalize_math(page_file("questions", page).read_text(encoding="utf-8"))
        page_offsets.append((cursor, page))
        texts.append(text)
        cursor += len(text) + 2
    text = "\n\n".join(texts)
    matches = list(QUESTION_RE.finditer(text))

    def page_at(position: int) -> int:
        current = page_offsets[0][1]
        for offset, page in page_offsets:
            if offset > position:
                break
            current = page
        return current

    questions = []
    for index, match in enumerate(matches):
        number = int(match.group(1))
        chunk_end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        questions.append((number, page_at(match.start()), text[match.end() : chunk_end].strip()))
    if [item[0] for item in questions] != list(range(1, 23)):
        raise ValueError(f"第{SET_NAMES[set_index - 1]}套题号异常：{[item[0] for item in questions]}")

    chapter = f"第{SET_NAMES[set_index - 1]}套"
    result = []
    for number, page, body in questions:
        qtype = "选择题" if number <= 10 else "填空题" if number <= 16 else "计算题"
        options = None
        subs = None
        if qtype == "选择题":
            body, options = parse_choice(body)
        elif qtype == "计算题":
            body, subs = split_subquestions(body)
            if "证明" in body + "\n" + "\n".join(subs or []):
                qtype = "证明题"
        has_image = bool(re.search(r"如图|见图|图中|下图|上图", body + "\n" + "\n".join(subs or [])))
        uid = f"李林六套卷-{chapter}-{number}"
        result.append({
            "uid": uid,
            "id": str(number),
            "qnum": number,
            "type": qtype,
            "content": body,
            "options": options,
            "sub_questions": subs,
            "page": page,
            "printed_page": page - 1,
            "chapter": chapter,
            "section": qtype,
            "has_image": has_image,
            "image_ref": {
                "page": page,
                "cropped": f"images/questions/s{set_index:02d}_q{number:02d}.png",
                "note": "原题图",
                "original_page": None,
            } if has_image else None,
            "source": "2027李林数学冲刺预测6套卷·数学二",
            "answer_ref": f"answer_crops/s{set_index:02d}_q{number:02d}.png",
            "answer_incomplete": False,
            "answer_structured": None,
        })
    return result


def build_questions(with_answers: bool = True) -> dict:
    chapters = []
    answer_starts = answer_ranges() if with_answers else {}
    for set_index, (start, end) in question_ranges().items():
        questions = parse_set(set_index, start, end)
        if with_answers:
            keys = answer_keys(set_index, *answer_starts[set_index])
            for question in questions:
                if question["qnum"] <= 10:
                    question["answer_structured"] = {
                        "kind": "choice",
                        "canonical": keys[question["qnum"]],
                        "judge_mode": "choice_exact",
                    }
        chapters.append({"name": f"第{SET_NAMES[set_index - 1]}套", "question_count": len(questions), "questions": questions})
    data = {
        "schema_version": "1.0",
        "bank": "李林六套卷",
        "title": "2027李林数学冲刺预测6套卷·数学二",
        "total_pages": 31,
        "content_pages": 30,
        "total_questions": sum(ch["question_count"] for ch in chapters),
        "chapters": chapters,
    }
    if data["total_questions"] != 132:
        raise ValueError(f"总题数异常：{data['total_questions']}")
    output = BOOK / "questions.json"
    temporary = output.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(output)
    image_count = sum(q["has_image"] for chapter in chapters for q in chapter["questions"])
    print(f"Generated {output}: 132 questions, 6 chapters, {image_count} figure questions")
    return data


def load_layout(page: int) -> list:
    return json.loads((LAYOUT / "answers" / f"p{page:03d}.json").read_text(encoding="utf-8"))


def answer_markers(page: int) -> list[tuple[int, float]]:
    found = []
    for box, text, _ in load_layout(page):
        if min(point[0] for point in box) > 350:
            continue
        match = re.match(r"^\s*(\d{1,2})\s*[.．]", text)
        if match and 1 <= int(match.group(1)) <= 22:
            found.append((int(match.group(1)), min(point[1] for point in box)))
    return sorted(found, key=lambda item: item[1])


def bare_answer_markers(page: int) -> list[tuple[int, float]]:
    found = []
    for box, text, _ in load_layout(page):
        if min(point[0] for point in box) > 350:
            continue
        if re.fullmatch(r"\s*答\s*案\s*", text):
            found.append((page, min(point[1] for point in box)))
    return found


def choose_markers(set_index: int, start: int) -> list[tuple[int, int, float]]:
    next_start = answer_ranges()[set_index + 1][0] if set_index < 6 else None
    last_page = next_start if next_start else 74
    pool = {}
    bare = []
    for page in range(start, last_page + 1):
        if page in DUPLICATE_PAGES:
            continue
        for number, y in answer_markers(page):
            pool.setdefault(number, []).append((page, y))
        bare.extend(bare_answer_markers(page))
    chosen = []
    previous = (0, 0.0)
    for number in range(1, 23):
        options = [item for item in pool.get(number, []) if item > previous]
        if not options:
            later = [
                item
                for later_number in range(number + 1, 23)
                for item in pool.get(later_number, [])
            ]
            bound = min(later) if later else (last_page + 1, 0.0)
            options = [item for item in bare if previous < item < bound]
            if options:
                chosen_bare = options[0]
                bare.remove(chosen_bare)
                options = [(chosen_bare[0], chosen_bare[1])]
        if not options:
            raise ValueError(f"第{SET_NAMES[set_index - 1]}套第{number}题答案定位缺失")
        page, y = options[0]
        chosen.append((number, page, y))
        previous = (page, y)
    if [page for _, page, _ in chosen] != sorted(page for _, page, _ in chosen):
        raise ValueError(f"第{SET_NAMES[set_index - 1]}套答案顺序异常：{chosen}")
    return chosen


def answer_title_y(set_index: int) -> tuple[int, float]:
    start = answer_ranges()[set_index][0]
    pattern = re.compile(rf"第{SET_NAMES[set_index - 1]}套.*答案")
    for page in range(start, min(start + 2, 75)):
        for box, text, _ in load_layout(page):
            if pattern.search(text):
                return page, min(point[1] for point in box)
    raise ValueError(f"找不到第{SET_NAMES[set_index - 1]}套答案标题坐标")


def content_top(page: int, height: int) -> int:
    rows = []
    for box, text, _ in load_layout(page):
        top = min(point[1] for point in box)
        if top < height * 0.2 and not re.search(r"李林全家桶|考研数学冲刺预测|第[一二三四五六]套.*答案", text):
            rows.append(top)
    return max(80, int(min(rows)) - 10) if rows else 120


def content_bottom(page: int, height: int) -> int:
    bottoms = []
    for box, text, _ in load_layout(page):
        top = min(point[1] for point in box)
        bottom = max(point[1] for point in box)
        if top > height * 0.89 or re.search(r"第\s*\d+\s*页|公众号|免费分享", text):
            continue
        bottoms.append(bottom)
    return min(height - 80, int(max(bottoms, default=height * 0.85) + 20))


def section_boundary(page: int, start: float, end: float) -> float:
    for box, text, _ in load_layout(page):
        top = min(point[1] for point in box)
        if start < top < end and re.match(r"^\s*[一二三]\s*[、,，]", text):
            return top - 12
    return end


def trim(image: Image.Image, padding: int = 16) -> Image.Image:
    mask = image.convert("L").point(lambda value: 255 if value < 215 else 0)
    box = mask.getbbox()
    if not box:
        return image
    return image.crop((
        max(0, box[0] - padding),
        max(0, box[1] - padding),
        min(image.width, box[2] + padding),
        min(image.height, box[3] + padding),
    ))


def crop_answers() -> None:
    ranges = answer_ranges()
    generated = 0
    for set_index in range(1, 7):
        start = ranges[set_index][0]
        chosen = choose_markers(set_index, start)
        next_title = answer_title_y(set_index + 1) if set_index < 6 else None
        for index, (number, start_page, start_y) in enumerate(chosen):
            if index + 1 < len(chosen):
                end_page = chosen[index + 1][1]
                end_y = chosen[index + 1][2] - 14
            elif next_title:
                end_page, end_y = next_title
                end_y -= 100
            else:
                end_page, end_y = 74, None
            pieces = []
            for page in range(start_page, end_page + 1):
                if page in DUPLICATE_PAGES:
                    continue
                with Image.open(BOOK / "answer_pdf_images" / f"page_{page:03d}.png") as source:
                    top = start_y if page == start_page else content_top(page, source.height)
                    bottom = end_y if page == end_page and end_y is not None else content_bottom(page, source.height)
                    bottom = section_boundary(page, top, bottom)
                    if bottom - top > 30:
                        pieces.append(trim(source.crop((80, max(0, int(top) - 14), source.width - 70, int(bottom)))))
            if not pieces:
                raise ValueError(f"第{SET_NAMES[set_index - 1]}套第{number}题答案裁图为空")
            width = max(piece.width for piece in pieces)
            combined = Image.new("RGB", (width, sum(piece.height for piece in pieces) + 20 * (len(pieces) - 1)), "white")
            y = 0
            for piece in pieces:
                combined.paste(piece, (0, y))
                y += piece.height + 20
            output = BOOK / "math-bank" / "answer_crops" / f"s{set_index:02d}_q{number:02d}.png"
            output.parent.mkdir(parents=True, exist_ok=True)
            combined.save(output, optimize=True)
            generated += 1
        print(f"Cropped answers: 第{SET_NAMES[set_index - 1]}套")
    if generated != 132:
        raise ValueError(f"答案裁图数量异常：{generated}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--questions-only", action="store_true")
    parser.add_argument("--crop-only", action="store_true")
    args = parser.parse_args()
    if not args.crop_only:
        build_questions(with_answers=not args.questions_only)
        print("question ranges", question_ranges())
        if not args.questions_only:
            print("answer ranges", answer_ranges())
    if not args.questions_only:
        crop_answers()


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
