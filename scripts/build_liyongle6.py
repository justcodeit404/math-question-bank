#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
BOOK = ROOT / "李永乐六套卷"
WORK = ROOT.parent.parent / "temp" / "liyongle6"
QUESTION_OCR = WORK / "questions-ocr"
LAYOUT = WORK / "layout"
SET_NAMES = "一二三四五六"
ANSWER_STARTS = (3, 11, 19, 26, 34, 43)
QUESTION_RE = re.compile(r"(?m)^(?:#{1,6}\s*)?(\d{1,2})\s*[.．]\s*")
OPTION_RE = re.compile(r"(?m)(^|\s)([ABCD])\s*[.．、]\s*")
SUB_RE = re.compile(r"(?m)^\s*[（(](\d+)[）)]\s*")
MARKER_RE = re.compile(r"^\s*(\d{1,2})\s*[.．]")
MARKER_OVERRIDES = {
    ("questions", 2, 2): 479,
    ("questions", 3, 14): 1180,
    ("questions", 6, 5): 1325,
    ("questions", 6, 7): 1885,
    ("questions", 10, 1): 320,
    ("questions", 14, 1): 320,
    ("questions", 14, 3): 840,
    ("questions", 15, 16): 1635,
    ("questions", 23, 9): 525,
    ("answers", 8, 19): 610,
    ("answers", 18, 22): 718,
    ("answers", 31, 20): 1970,
    ("answers", 32, 22): 1920,
}


def normalize_math(text: str) -> str:
    text = text.replace(r"\(", "$").replace(r"\)", "$")
    text = text.replace(r"\[", "$$").replace(r"\]", "$$")
    text = re.sub(r"\\left\\\{\s*(?=\\begin\{array\})", lambda _: r"\left\lbrace", text)
    text = re.sub(r"(\\begin\{array\}\{)([lcr]{2,})(\})", lambda match: match[1] + " ".join(match[2]) + match[3], text)
    text = re.sub(r"[（(]本题满分\s*\d+\s*分[）)]", "", text)
    text = re.sub(r"(?m)^#{1,6}\s*[一二三]\s*[、,，].*$", "", text)
    text = text.replace("\u00a0", " ")
    return "\n".join(line.rstrip() for line in text.splitlines()).strip()


def parse_choice(text: str) -> tuple[str, dict[str, str]]:
    matches = [m for m in OPTION_RE.finditer(text) if m.group(2) in "ABCD"]
    labels = [m.group(2) for m in matches]
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
    if [int(m.group(1)) for m in matches] != list(range(1, len(matches) + 1)):
        return text, None
    content = text[: matches[0].start()].strip()
    subs = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        subs.append(text[match.end() : end].strip())
    return content, subs


def answer_keys(set_index: int) -> dict[int, str]:
    start = ANSWER_STARTS[set_index - 1]
    end = ANSWER_STARTS[set_index] if set_index < 6 else 53
    directory = WORK / "answers-ocr"
    text = "\n".join(
        (directory / f"李永乐六套卷（数二）答案解析-p{page:03d}.md").read_text(encoding="utf-8")
        for page in range(start, end)
    )
    pattern = re.compile(r"(?m)^(?:#{1,6}\s*)?(\d{1,2})\s*[.．]?\s*【答案】\s*([^\n]+)")
    matches = list(pattern.finditer(text))
    numbers = [int(match.group(1)) for match in matches]
    expected = [1, 2, 3] + list(range(11, 17)) if set_index == 3 else list(range(1, 17))
    if numbers != expected:
        raise ValueError(f"模拟{SET_NAMES[set_index - 1]}答案编号异常：{numbers}")
    keys = {int(match.group(1)): match.group(2).strip() for match in matches}
    if set_index == 3:
        keys[10] = "C"
    return keys


def parse_set(set_index: int) -> list[dict]:
    keys = answer_keys(set_index)
    questions = []
    for offset in range(1, 4):
        page = (set_index - 1) * 4 + offset + 1
        path = QUESTION_OCR / f"李永乐六套卷（数二）-p{page:03d}.md"
        text = normalize_math(path.read_text(encoding="utf-8"))
        matches = list(QUESTION_RE.finditer(text))
        for index, match in enumerate(matches):
            number = int(match.group(1))
            end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
            body = text[match.end() : end].strip()
            questions.append((number, page, body))
    if [item[0] for item in questions] != list(range(1, 23)):
        raise ValueError(f"模拟{SET_NAMES[set_index - 1]}题号异常：{[item[0] for item in questions]}")

    chapter = f"模拟{SET_NAMES[set_index - 1]}"
    result = []
    for number, page, body in questions:
        qtype = "选择题" if number <= 10 else "填空题" if number <= 16 else "计算题"
        options = None
        subs = None
        if qtype == "选择题":
            body, options = parse_choice(body)
        elif qtype == "计算题":
            body, subs = split_subquestions(body)
            if "证明" in body:
                qtype = "证明题"
        uid = f"李永乐六套卷-{chapter}-{number}"
        result.append({
            "uid": uid,
            "id": str(number),
            "qnum": number,
            "type": qtype,
            "content": body,
            "options": options,
            "sub_questions": subs,
            "page": page,
            "printed_page": (page - 2) % 4 + 1,
            "chapter": chapter,
            "section": qtype,
            "has_image": bool(re.search(r"如图|见图|图中|下图|上图", body + "\n" + "\n".join(subs or []))),
            "image_ref": {
                "page": page,
                "cropped": f"images/questions/s{set_index:02d}_q{number:02d}.png",
                "note": "原题逐题裁图",
                "original_page": None,
            },
            "source": "2027李永乐数学决胜冲刺6套卷·数学二",
            "answer_ref": None if set_index == 3 and 4 <= number <= 9 else f"answer_crops/s{set_index:02d}_q{number:02d}.png",
            "answer_incomplete": set_index == 3 and 4 <= number <= 10,
            "answer_structured": {
                "kind": "choice",
                "canonical": keys[number].rstrip("."),
                "judge_mode": "choice_exact",
            } if number <= 10 and number in keys and re.fullmatch(r"[A-D]\.?", keys[number]) else None,
        })
    return result


def build_questions() -> dict:
    chapters = []
    for set_index in range(1, 7):
        chapter = f"模拟{SET_NAMES[set_index - 1]}"
        questions = parse_set(set_index)
        chapters.append({"name": chapter, "question_count": len(questions), "questions": questions})
    data = {
        "schema_version": "1.0",
        "bank": "李永乐六套卷",
        "title": "2027李永乐数学决胜冲刺6套卷·数学二",
        "total_pages": 24,
        "content_pages": 18,
        "total_questions": sum(ch["question_count"] for ch in chapters),
        "chapters": chapters,
    }
    if data["total_questions"] != 132:
        raise ValueError(f"总题数异常：{data['total_questions']}")
    output = BOOK / "questions.json"
    temporary = output.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(output)
    print(f"Generated {output}: 132 questions, 6 chapters")
    return data


def load_layout(kind: str, page: int) -> list:
    return json.loads((LAYOUT / kind / f"p{page:03d}.json").read_text(encoding="utf-8"))


def markers(kind: str, page: int) -> list[tuple[int, float]]:
    found = []
    for box, text, score in load_layout(kind, page):
        if min(point[0] for point in box) > 300:
            continue
        match = MARKER_RE.match(text)
        if not match:
            continue
        number = int(match.group(1))
        if 1 <= number <= 22:
            found.append((number, min(point[1] for point in box)))
    return sorted(found, key=lambda item: item[1])


def set_markers(kind: str, set_index: int) -> list[tuple[int, int, float]]:
    if kind == "questions":
        pages = [(set_index - 1) * 4 + offset + 1 for offset in range(1, 4)]
    else:
        start = ANSWER_STARTS[set_index - 1]
        end = ANSWER_STARTS[set_index] if set_index < 6 else 53
        pages = list(range(start, end))
    found = []
    for page in pages:
        found.extend((number, page, y) for number, y in markers(kind, page))
    detected = {number for number, _, _ in found}
    for (marker_kind, page, number), y in MARKER_OVERRIDES.items():
        if marker_kind == kind and page in pages and number not in detected:
            found.append((number, page, y))
    found.sort(key=lambda item: (item[1], item[2]))
    sequence = [number for number, _, _ in found]
    expected = [1, 2, 3] + list(range(11, 23)) if kind == "answers" and set_index == 3 else list(range(1, 23))
    if sequence != expected:
        raise ValueError(f"{kind} 模拟{SET_NAMES[set_index - 1]}定位异常：{sequence}")
    return found


def content_bottom(kind: str, page: int, height: int) -> int:
    bottoms = []
    for box, text, _ in load_layout(kind, page):
        top = min(point[1] for point in box)
        bottom = max(point[1] for point in box)
        if top > height * 0.89 or re.search(r"第\s*\d+\s*页|配套课程|联系微信", text):
            continue
        bottoms.append(bottom)
    return min(height - 100, int(max(bottoms, default=height * 0.85) + 24))


def content_top(kind: str, page: int, height: int) -> int:
    rows = []
    for box, text, _ in load_layout(kind, page):
        top = min(point[1] for point in box)
        if top < height * 0.2:
            rows.append((top, text))
    for top, text in sorted(rows):
        if re.search(r"数学决胜冲刺|参考答案与解析", text):
            continue
        return max(80, int(top) - 10)
    return 120


def section_boundary(kind: str, page: int, start: float, end: float) -> float:
    for box, text, _ in load_layout(kind, page):
        top = min(point[1] for point in box)
        if start < top < end and re.match(r"^\s*[一二三]\s*[、,，]", text):
            return top - 12
    return end


def trim(image: Image.Image, padding: int = 18) -> Image.Image:
    mask = image.convert("L").point(lambda value: 255 if value < 215 else 0)
    box = mask.getbbox()
    if not box:
        return image
    left = max(0, box[0] - padding)
    top = max(0, box[1] - padding)
    right = min(image.width, box[2] + padding)
    bottom = min(image.height, box[3] + padding)
    return image.crop((left, top, right, bottom))


def save_crop(image: Image.Image, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    trim(image).save(output, optimize=True)


def crop_questions() -> None:
    for set_index in range(1, 7):
        found = set_markers("questions", set_index)
        for index, (number, page, y) in enumerate(found):
            with Image.open(BOOK / "pdf_images" / f"page_{page:03d}.png") as source:
                end = found[index + 1][2] - 14 if index + 1 < len(found) and found[index + 1][1] == page else content_bottom("questions", page, source.height)
                end = section_boundary("questions", page, y, end)
                image = source.crop((100, max(0, int(y) - 18), source.width - 90, int(end)))
                save_crop(image, BOOK / "math-bank" / "images" / "questions" / f"s{set_index:02d}_q{number:02d}.png")
        print(f"Cropped questions: 模拟{SET_NAMES[set_index - 1]}")


def crop_answers() -> None:
    for set_index in range(1, 7):
        found = set_markers("answers", set_index)
        last_page = ANSWER_STARTS[set_index] - 1 if set_index < 6 else 52
        spans = [(number, page, y, found[index + 1][1] if index + 1 < len(found) else last_page, found[index + 1][2] if index + 1 < len(found) else None) for index, (number, page, y) in enumerate(found)]
        for number, start_page, start_y, end_page, end_y in spans:
            crops = []
            for page in range(start_page, end_page + 1):
                with Image.open(BOOK / "answer_pdf_images" / f"page_{page:03d}.png") as source:
                    top = start_y if page == start_page else content_top("answers", page, source.height)
                    bottom = end_y if page == end_page and end_y is not None else content_bottom("answers", page, source.height)
                    bottom = section_boundary("answers", page, top, bottom)
                    if bottom - top > 30:
                        crops.append(trim(source.crop((100, max(0, int(top) - 16), source.width - 90, int(bottom)))))
            if not crops:
                raise ValueError(f"答案裁图为空：模拟{SET_NAMES[set_index - 1]}第{number}题")
            width = max(crop.width for crop in crops)
            combined = Image.new("RGB", (width, sum(crop.height for crop in crops) + 20 * (len(crops) - 1)), "white")
            y = 0
            for crop in crops:
                combined.paste(crop, (0, y))
                y += crop.height + 20
            output = BOOK / "math-bank" / "answer_crops" / f"s{set_index:02d}_q{number:02d}.png"
            output.parent.mkdir(parents=True, exist_ok=True)
            combined.save(output, optimize=True)
        if set_index == 3:
            next_y = next(y for number, page, y in found if number == 11)
            with Image.open(BOOK / "answer_pdf_images" / "page_020.png") as source:
                end = section_boundary("answers", 20, 120, next_y - 14)
                image = source.crop((100, 120, source.width - 90, int(end)))
                save_crop(image, BOOK / "math-bank" / "answer_crops" / "s03_q10.png")
        print(f"Cropped answers: 模拟{SET_NAMES[set_index - 1]}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--parse-only", action="store_true")
    parser.add_argument("--crop-only", action="store_true")
    args = parser.parse_args()
    if not args.crop_only:
        build_questions()
    if not args.parse_only:
        crop_questions()
        crop_answers()
    for kind, expected in (("questions", 132), ("answer_crops", 126)):
        directory = BOOK / "math-bank" / ("images/questions" if kind == "questions" else kind)
        if directory.exists():
            files = list(directory.glob("s*_q*.png"))
            if files and len(files) != expected:
                raise ValueError(f"{kind} 裁图数量异常：{len(files)}，应为 {expected}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
