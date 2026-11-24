#!/usr/bin/env python3
"""数学二历年真题（2010–2026）入库：OCR markdown → questions.json + 答案裁图。

源文件：资料/数学2/电子资料/数学二历年真题2010-2026/
- 真题 OCR：temp/zhenti-math2/questions-ocr/<真题PDF名>-pNNN.md
- 详解 OCR：temp/zhenti-math2/answers-ocr/<详解PDF名>-pNNN.md（仅扫描版详解）
- 页面图：temp/zhenti-math2/pages/<PDF名>/pages/page_NNN.png
- 行框：  temp/zhenti-math2/layout/<PDF名>/pNNN.json（ocr_layout.py 产物）

题型结构：2010–2020 为 8 选择 + 6 填空 + 9 解答（23 题）；
2021 起为 10 选择 + 6 填空 + 6 解答（22 题）。

2024 为「真题及解析」合册、2026 为 iqihang「真题及答案」合册，题目与解析同册，
按 【答案】 标记切分；2023 答案为速查表，选择题答案键由 builder 直接写入
（extract_structured_answers 需用 --skip-existing，避免共享裁图被误读）。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = ROOT.parent.parent
BOOK = ROOT / "历年真题"
WORK = REPO_ROOT / "temp" / "zhenti-math2"
QUESTION_OCR = WORK / "questions-ocr"
ANSWER_OCR = WORK / "answers-ocr"
PAGES = WORK / "pages"
LAYOUT = WORK / "layout"

YEARS = list(range(2010, 2027))
SOURCE = "数学二历年真题（2010–2026）"

# 2024/2026 为题目+解析合册，其余年份真题、详解各自成册
COMBINED = {2024: "2024数学二真题及解析", 2026: "2026数学二真题及答案-iqihang"}


def question_book(year: int) -> str:
    return COMBINED.get(year, f"{year}数学二真题")


def answer_book(year: int) -> str:
    return COMBINED.get(year, f"{year}数学二详解")


def spec(year: int) -> dict:
    if year <= 2020:
        return {"choice_end": 8, "blank_end": 14, "total": 23}
    return {"choice_end": 10, "blank_end": 16, "total": 22}


# ---------------------------------------------------------------- 题目解析

QUESTION_RE = re.compile(r"(?m)^\s*(?:#{1,6}\s*)?[（(]\s*(\d{1,2})\s*[）)]")
# 2020/2023/2024/2025/2026 题号为「N.」格式（2020 另有考生须知页需跳过）
QUESTION_RE_DOTTED = re.compile(r"(?m)^\s*(?:#{1,6}\s*)?(\d{1,2})\s*[.．](?!\d)")
DOTTED_YEARS = {2020, 2023, 2024, 2025, 2026}
QUESTION_SKIP_PAGES = {2020: 1}
OPTION_RE = re.compile(r"(?<![A-Za-z0-9$\\])[（(]\s*([ABCD])\s*[）)]\s*[.．、]?")
# dotted 年份（2020/2023–2026）选项为「A. 」格式（可同行连排）
OPTION_RE_DOTTED = re.compile(r"(?<![A-Za-z0-9$\\])([ABCD])\s*[.．]\s*")
SUB_RE = re.compile(r"(?m)^\s*[（(]([ⅠⅡⅢⅣⅤⅥ]+)[）)]\s*")
ANSWER_MARK_RE = re.compile(r"【(?:答案|解析|解)】|^\s*解\s*[:：]|^\s*\d{1,2}\s*[.．]\s*【?证明", re.M)
FOOTER_RE = re.compile(
    r"(?m)^\s*(—\s*\d+\s*—|第\s*\d+\s*页.*|数学解析|数学试题.*|\d{4}\s*年全国硕士研究生招生考试.*)$"
)


def normalize_math(text: str) -> str:
    text = text.replace(r"\(", "$").replace(r"\)", "$")
    text = text.replace(r"\[", "$$").replace(r"\]", "$$")
    text = re.sub(r"\\left\\\{\s*(?=\\begin\{array\})", lambda _: r"\left\lbrace", text)
    text = re.sub(
        r"(\\begin\{array\}\{)([lcr]{2,})(\})",
        lambda m: m[1] + " ".join(m[2]) + m[3],
        text,
    )
    text = re.sub(r"[（(]本题满分\s*\d+\s*分[）)]", "", text)
    text = FOOTER_RE.sub("", text)
    text = re.sub(r"(?m)^#{1,6}\s*[一二三]\s*[、,，].*$", "", text)
    return "\n".join(line.rstrip() for line in text.splitlines()).strip()


def parse_choice(text: str, year: int) -> tuple[str, dict[str, str]]:
    option_re = OPTION_RE_DOTTED if year in DOTTED_YEARS else OPTION_RE
    matches = [m for m in option_re.finditer(text)]
    labels = [m.group(1) for m in matches]
    if labels[:4] != list("ABCD"):
        raise ValueError(f"选项不是连续 A-D：{labels}；{text[:160]}")
    matches = matches[:4]
    content = text[: matches[0].start()].strip()
    options = {}
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        options[match.group(1)] = text[match.end() : end].strip()
    return content, options


def split_subquestions(text: str) -> tuple[str, list[str] | None]:
    matches = list(SUB_RE.finditer(text))
    if not matches:
        return text, None
    expected = ["Ⅰ", "Ⅱ", "Ⅲ", "Ⅳ", "Ⅴ", "Ⅵ"][: len(matches)]
    if [m.group(1) for m in matches] != expected:
        return text, None
    content = text[: matches[0].start()].strip()
    subs = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        subs.append(text[match.end() : end].strip())
    return content, subs


def year_pages(year: int) -> list[tuple[int, str]]:
    """返回 [(物理页, 规范化文本)]；合册只取题目部分之前先全量，切分在 parse_year 内做。"""
    prefix = question_book(year)
    skip = QUESTION_SKIP_PAGES.get(year, 0)
    pages = []
    for path in sorted(QUESTION_OCR.glob(f"{prefix}-p*.md")):
        page = int(re.search(r"-p(\d+)\.md$", path.name).group(1))
        if page <= skip:
            continue
        pages.append((page, path.read_text(encoding="utf-8")))
    if not pages:
        raise ValueError(f"{year} 真题 OCR 缺失：{QUESTION_OCR}/{prefix}-p*.md")
    return pages


def parse_year(year: int) -> list[dict]:
    sp = spec(year)
    pages = year_pages(year)
    texts, page_offsets = [], []
    cursor = 0
    for page, raw in pages:
        text = normalize_math(raw)
        page_offsets.append((cursor, page))
        texts.append(text)
        cursor += len(text) + 2
    full = "\n\n".join(texts)

    # 合册（2024/2026）：题目与解析同册，题 N 题干止于其 【答案】 标记
    combined = year in COMBINED

    def page_at(position: int) -> int:
        current = page_offsets[0][1]
        for offset, page in page_offsets:
            if offset > position:
                break
            current = page
        return current

    # 预期题号序列过滤：防止解答题内部 (1)(2) 子问被误当新题
    qre = QUESTION_RE_DOTTED if year in DOTTED_YEARS else QUESTION_RE
    matches = []
    expected = 1
    for m in qre.finditer(full):
        num_str = next((g for g in m.groups() if g is not None), None)
        if num_str and int(num_str) == expected:
            matches.append(m)
            expected += 1
            if expected > sp["total"]:
                break
    numbers = [int(m.group(1)) for m in matches]
    if numbers != list(range(1, sp["total"] + 1)):
        raise ValueError(f"{year} 题号序列异常：{numbers}")

    chapter = f"{year}年"
    result = []
    for index, match in enumerate(matches):
        number = int(next(g for g in match.groups() if g is not None))
        chunk_end = matches[index + 1].start() if index + 1 < len(matches) else len(full)
        body = full[match.end() : chunk_end]
        if combined:
            cut = ANSWER_MARK_RE.search(body)
            if not cut:
                raise ValueError(f"{year} 第{number}题缺少 【答案】 切分点")
            body = body[: cut.start()]
            # 去掉答案行残留的题号前缀（如「1. 【答案】」切分后剩下的「1.」）
            body = re.sub(r"(?:\n\s*\d{1,2}\s*[.．]?)+[\s.．]*$", "", body)
        body = body.strip()
        subs = None
        if number <= sp["choice_end"]:
            qtype = "选择题"
            body, options = parse_choice(body, year)
        elif number <= sp["blank_end"]:
            qtype, options = "填空题", None
        else:
            qtype, options = "计算题", None
            body, subs = split_subquestions(body)
            if "证明" in body + "\n" + "\n".join(subs or []):
                qtype = "证明题"
        if not body.strip() and subs:
            body = "（本题无主题干，见子问）"
        has_image = bool(re.search(r"如图|见图|图中|下图|上图", body + "\n" + "\n".join(subs or [])))
        result.append({
            "uid": f"历年真题-{year}-{number}",
            "id": str(number),
            "qnum": number,
            "type": qtype,
            "content": body,
            "options": options,
            "sub_questions": subs,
            "page": page_at(match.start()),
            "printed_page": page_at(match.start()),
            "chapter": chapter,
            "section": qtype,
            "has_image": has_image,
            "image_ref": {
                "page": page_at(match.start()),
                "cropped": f"images/questions/y{year}_q{number:02d}.png",
                "note": "原题图",
                "original_page": None,
            } if has_image else None,
            "source": SOURCE,
            "answer_ref": None if number in ISOLATED.get(year, set()) else f"answer_crops/y{year}_q{number:02d}.png",
            "answer_incomplete": number in ISOLATED.get(year, set()),
            "answer_structured": None,
        })
    return result


def build_questions(years: list[int]) -> dict:
    chapters = []
    for year in years:
        questions = parse_year(year)
        chapters.append({"name": f"{year}年", "question_count": len(questions), "questions": questions})
        print(f"parsed {year}: {len(questions)} questions")
    data = {
        "schema_version": "1.0",
        "bank": "历年真题",
        "title": SOURCE,
        "total_pages": None,
        "content_pages": None,
        "total_questions": sum(ch["question_count"] for ch in chapters),
        "chapters": chapters,
    }
    output = BOOK / "questions.json"
    if output.exists() and len(years) < len(YEARS):
        old = json.loads(output.read_text(encoding="utf-8"))
        merged = {ch["name"]: ch for ch in old["chapters"]}
        for ch in chapters:
            merged[ch["name"]] = ch
        data["chapters"] = [merged[f"{y}年"] for y in YEARS if f"{y}年" in merged]
        data["total_questions"] = sum(ch["question_count"] for ch in data["chapters"])
    BOOK.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(output)
    print(f"Generated {output}: {data['total_questions']} questions, {len(data['chapters'])} chapters")
    return data


# ---------------------------------------------------------------- 答案键

def answer_keys(year: int) -> dict[int, str]:
    """builder 直接写入的选择题答案键，仅限文字层干净的年份。

    2023 速查为紧凑区间（1~5.BDBCC.），2024 合册为 N.【答案】X，
    2026 iqihang 为题内 【答案】X 顺序出现。其余年份由
    extract_structured_answers 从答案裁图 OCR 提取（03 详解文字层字体损坏，不可用）。
    """
    sp = spec(year)
    keys: dict[int, str] = {}
    src = REPO_ROOT / "资料" / "数学2" / "电子资料" / "数学二历年真题2010-2026"
    if year == 2023:
        import pymupdf

        with pymupdf.open(src / "2023数学二详解.pdf") as doc:
            text = "".join(page.get_text() for page in doc)
        for m in re.finditer(r"(\d{1,2})\s*~\s*(\d{1,2})\s*[.．]\s*([A-D]{2,5})", text):
            a, b, letters = int(m.group(1)), int(m.group(2)), m.group(3)
            for offset, letter in enumerate(letters):
                keys[a + offset] = letter
    elif year in COMBINED:
        import pymupdf

        with pymupdf.open(src / f"{COMBINED[year]}.pdf") as doc:
            text = "".join(page.get_text() for page in doc)
        # 选择题答案按文档顺序取前 choice_end 个 【答案】 字母（题号与【答案】可能跨行）
        seq = re.findall(r"【答案】\s*([A-D])", text)
        keys = {i + 1: letter for i, letter in enumerate(seq[: sp["choice_end"]])}
    else:
        raise ValueError(f"{year} 无 builder 答案键来源，交给 extract_structured_answers")
    expected = set(range(1, sp["choice_end"] + 1))
    if set(keys) != expected:
        raise ValueError(f"{year} 选择题答案键异常：{sorted(keys)}")
    return keys


def apply_answer_keys(years: list[int]) -> None:
    path = BOOK / "questions.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    for chapter in data["chapters"]:
        year = int(chapter["name"].rstrip("年"))
        if year not in years or year not in (2023, 2024, 2026):
            continue
        keys = answer_keys(year)
        for q in chapter["questions"]:
            if q["qnum"] in keys:
                q["answer_structured"] = {
                    "kind": "choice",
                    "canonical": keys[q["qnum"]],
                    "judge_mode": "choice_exact",
                }
        print(f"keys {year}: {len(keys)} choice answers")
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


# ---------------------------------------------------------------- 答案裁图

SCAN_LAYOUT_YEARS = {2015, 2016, 2018, 2019, 2020, 2021, 2022, 2025}  # jingwei 扫描详解，走行框
SRC_DIR = REPO_ROOT / "资料" / "数学2" / "电子资料" / "数学二历年真题2010-2026"

PAGENO_RE = re.compile(r"^\s*(—\s*\d+\s*—|第\s*\d+\s*页.*|\d{1,2})\s*$")
HEADER_RE = re.compile(r"考研数学|数学[（(]二[）)]|真题解析|参考答案|答案解析|试题解析|答案速查|^\d{4}\s*年")
AD_RE = re.compile(r"淘宝|店铺|公众号|微信|QQ|光速|考研工作室|免费分享|扫码")
CIRCLED = {chr(0x2460 + i): i + 1 for i in range(20)}  # ①-⑳
CIRCLED.update({chr(0x3251 + i): i + 21 for i in range(15)})  # ㉑-㉟
CIRCLED.update({chr(0x2474 + i): i + 1 for i in range(20)})  # ⑴-⑳（单个字形）
CIRCLED_RE = re.compile("^\\s*([\u2460-\u2473\u3251-\u325f\u2474-\u2487])")


def normalize_circled(text: str) -> str:
    """03 详解文字层把部分题号渲染成圈号（⑸），统一转回 (N) 形式。"""
    m = CIRCLED_RE.match(text)
    if m:
        return f"({CIRCLED[m.group(1)]})" + text[m.end():]
    return text


def page_image(book: str, page: int) -> Path:
    return PAGES / book / "pages" / f"page_{page:03d}.png"


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


def layout_lines_for(book: str) -> dict[int, list[tuple[float, float, str]]]:
    result = {}
    for path in sorted((LAYOUT / book).glob("p*.json")):
        page = int(re.search(r"p(\d+)\.json$", path.name).group(1))
        rows = json.loads(path.read_text(encoding="utf-8"))
        lines = [(min(p[1] for p in box), max(p[1] for p in box), text) for box, text, _ in rows]
        result[page] = sorted(lines)
    return result


def answer_lines(year: int) -> dict[int, list[tuple[float, float, str]]]:
    """{物理页: [(y_top, y_bottom, text)]}，坐标统一为页面图像像素。"""
    book = answer_book(year)
    if year in SCAN_LAYOUT_YEARS:
        result = layout_lines_for(book)
        if not result:
            raise ValueError(f"{year} 详解行框缺失：{LAYOUT / book}")
        return result
    import pymupdf

    result = {}
    with pymupdf.open(SRC_DIR / f"{book}.pdf") as doc:
        for pno, page in enumerate(doc, 1):
            with Image.open(page_image(book, pno)) as im:
                scale = im.height / page.rect.height
            lines = []
            for block in page.get_text("dict")["blocks"]:
                for line in block.get("lines", []):
                    text = normalize_circled("".join(span["text"] for span in line["spans"]).strip())
                    if text:
                        lines.append((line["bbox"][1] * scale, line["bbox"][3] * scale, text))
            result[pno] = sorted(lines)
    return result


def content_top(lines: list[tuple[float, float, str]], height: int) -> int:
    tops = [
        y0 for y0, _, text in lines
        if y0 < height * 0.2 and not PAGENO_RE.match(text) and not HEADER_RE.search(text) and not AD_RE.search(text)
    ]
    return max(70, int(min(tops)) - 12) if tops else 110


def content_bottom(lines: list[tuple[float, float, str]], height: int) -> int:
    bottoms = [
        y1 for y0, y1, text in lines
        if y0 < height * 0.92 and not PAGENO_RE.match(text) and not AD_RE.search(text)
    ]
    return min(height - 60, int(max(bottoms, default=height * 0.88)) + 18)


GARBLE_MARK_RE = re.compile(
    r"^\s*[（(][^【\[［〔】\]］]{0,6}[【\[［〔]?\s*(?:答案|解|证明)\s*[】\]］]"
)
STANDALONE_MARK_RE = re.compile(r"^\s*[【\[［〔]\s*(?:答案|解|证明)\s*[】\]］]")


def snap_up(book: str, page: int, y_lo: float, y_hi: float) -> float:
    """文字层丢行时，在 (y_lo, y_hi) 像素区间找最后一个文字行带的顶部作为边界。"""
    if y_hi - y_lo < 20:
        return y_hi
    try:
        import numpy as np
    except ImportError:
        return y_hi
    with Image.open(page_image(book, page)) as im:
        region = im.crop((60, max(0, int(y_lo)), im.width - 50, int(y_hi))).convert("L")
    dark = (np.asarray(region) < 160).sum(axis=1) > 3
    bands = []
    start = None
    for i, v in enumerate(dark):
        if v and start is None:
            start = i
        elif not v and start is not None:
            bands.append((start, i))
            start = None
    if start is not None:
        bands.append((start, len(dark)))
    if not bands:
        return y_hi
    return y_lo + bands[-1][0] - 6


def question_events(
    lines_by_page: dict[int, list[tuple[float, float, str]]],
    qstart_re: re.Pattern,
    total: int,
    combined: bool,
    book: str,
    ans_marker: str = "【答案】",
) -> list[tuple[int, int, float, int, float]]:
    """按序产出每题 (qnum, 起始页, 起始y, 结束页, 结束y)。

    combined=True（题解同册/交错版式）：起点取题块内首个 【答案】 行，终点为下一题题号行；
    combined=False（纯解析册）：题号+【答案】/【解】同一标记行，终点为下一题标记行。
    题号行漏检/损坏时，用孤儿标记行（号码损坏的 m、号码丢失的 s、交错版的答案行 a）
    按前后题号约束回填；s 类孤儿起点向上吸附到文字层丢失的答案行。
    """
    stream = []  # (kind, num, page, y0, y1)
    for page in sorted(lines_by_page):
        for y0, y1, text in lines_by_page[page]:
            m = qstart_re.match(text)
            if m:
                num_str = next((g for g in m.groups() if g is not None), None)
                if num_str and 1 <= int(num_str) <= total:
                    stream.append(("q", int(num_str), page, y0, y1))
                    continue
            if combined and ans_marker in text:
                stream.append(("a", None, page, y0, y1))
            elif not combined and GARBLE_MARK_RE.match(text):
                stream.append(("m", None, page, y0, y1))
            elif not combined and STANDALONE_MARK_RE.match(text):
                stream.append(("s", None, page, y0, y1))

    blocks: list[list] = []  # [qnum, qstart|None, ans|None, absorbed_s]
    pending: list[tuple[str, int, float, float]] = []
    expected = 1

    def fill_missing(upto: int) -> None:
        nonlocal expected
        while expected < upto:
            if not pending:
                raise ValueError(f"第{expected}题题号漏检且无孤儿标记行可分配")
            kind, page, y0, y1 = pending.pop(0)
            blocks.append([expected, None, (page, y0, y1, kind), False])
            expected += 1

    for kind, num, page, y0, y1 in stream:
        if kind == "q":
            if num < expected:
                continue  # 解析/矩阵碎片里的数字行
            fill_missing(num)
            pending.clear()  # 无缺口时，孤儿是上一题解析内部行，丢弃
            blocks.append([num, (page, y0, y1, "q"), None, False])
            expected = num + 1
        elif kind == "a":
            if blocks and blocks[-1][2] is None:
                blocks[-1][2] = (page, y0, y1, "a")
            else:
                pending.append((kind, page, y0, y1))
        elif kind == "m":
            pending.append((kind, page, y0, y1))
        else:  # 's'：当前题块的首个独立【解】是解析正文，其后才是孤儿
            if blocks and not blocks[-1][3]:
                blocks[-1][3] = True
            else:
                pending.append((kind, page, y0, y1))
    fill_missing(total + 1)
    if len(blocks) != total:
        raise ValueError(f"题块数量异常：{len(blocks)} != {total}")

    def start_of(block: list) -> tuple[int, float]:
        qnum, qstart, ans, _ = block
        if combined:
            pos = ans or qstart
        else:
            pos = qstart or ans
        if pos is None:
            raise ValueError(f"第{qnum}题答案起点缺失")
        page, y0, y1, kind = pos
        if kind == "s":
            # 答案行被文字层丢失：向上吸附到页面图像中真实的答案行带
            prev_bottom = 0.0
            for ly0, ly1, _t in lines_by_page[page]:
                if ly1 < y0 - 4:
                    prev_bottom = max(prev_bottom, ly1)
            y0 = snap_up(book, page, prev_bottom + 4, y0)
        return page, y0 - 6

    last_page = max(lines_by_page)
    events = []
    for index, block in enumerate(blocks):
        qnum = block[0]
        sp, sy = start_of(block)
        if index + 1 < len(blocks):
            nxt = blocks[index + 1]
            # 终点用下一题的题干行（而非其答案行），避免把下一题题干带进本题裁图
            pos = nxt[1] or nxt[2]
            end = (pos[0], pos[1] - 10)
        else:
            end = (last_page, None)
        events.append((qnum, sp, sy, end[0], end[1]))
    return events


def render_crop(
    book: str,
    lines_by_page: dict[int, list[tuple[float, float, str]]],
    start: tuple[int, float],
    end: tuple[int, float | None],
    out_path: Path,
) -> None:
    (sp, sy), (ep, ey) = start, end
    pieces = []
    for page in range(sp, ep + 1):
        with Image.open(page_image(book, page)) as source:
            lines = lines_by_page.get(page, [])
            top = sy if page == sp else content_top(lines, source.height)
            bottom = ey if (page == ep and ey is not None) else content_bottom(lines, source.height)
            if bottom - top > 28:
                pieces.append(trim(source.crop((60, max(0, int(top)), source.width - 50, min(source.height, int(bottom))))))
    if not pieces:
        raise ValueError(f"{book} 裁图为空：{start} -> {end}")
    width = max(piece.width for piece in pieces)
    combined_img = Image.new("RGB", (width, sum(p.height for p in pieces) + 20 * (len(pieces) - 1)), "white")
    y = 0
    for piece in pieces:
        combined_img.paste(piece, (0, y))
        y += piece.height + 20
    out_path.parent.mkdir(parents=True, exist_ok=True)
    combined_img.save(out_path, optimize=True)


# 2022 详解（03 文件夹版）无内联答案的题：隔离，不编造
ISOLATED = {2022: {2, 3, 13, 14, 15}}
# 2022 第 6 题题干行被 OCR 漏检但答案存在，与第 5 题共享裁图
SHARE_PREV = {2022: {6}}


def events_2022(
    lines_by_page: dict[int, list[tuple[float, float, str]]],
) -> list[tuple[int, int, float, int, float]]:
    """2022 详解：题干 N. 锚点 + 【答案】 行；部分题无内联答案（隔离），Q6 共享 Q5 裁图。"""
    qstart_re = re.compile(r"^\s*(\d{1,2})\s*[.．](?!\d)")
    stems: dict[int, tuple[int, float]] = {}
    answers: dict[int, tuple[int, float]] = {}
    current = 0
    for page in sorted(lines_by_page):
        for y0, _y1, text in lines_by_page[page]:
            m = qstart_re.match(text)
            if m and current < int(m.group(1)) <= 22:
                current = int(m.group(1))
                stems[current] = (page, y0)
            elif "【答案】" in text and current and current not in answers:
                answers[current] = (page, y0)
    starts: dict[int, tuple[int, float]] = {}
    for qnum in range(1, 23):
        if qnum in ISOLATED[2022] or qnum in SHARE_PREV[2022]:
            continue
        pos = answers.get(qnum) or stems.get(qnum)
        if pos is None:
            raise ValueError(f"2022 第{qnum}题无任何锚点")
        starts[qnum] = pos
    events = []
    cropped = sorted(starts)
    for index, qnum in enumerate(cropped):
        sp, sy = starts[qnum]
        # 终点：下一道有题干锚点的题（含隔离题，防止其题干混入上一题裁图）
        later_stems = [(p, y) for n, (p, y) in stems.items() if n > qnum]
        if index + 1 < len(cropped):
            nxt = starts[cropped[index + 1]]
            candidates = [nxt] + [s for s in later_stems if s < nxt]
            ep, ey = min(candidates)
        elif later_stems:
            ep, ey = min(later_stems)
        else:
            ep, ey = max(lines_by_page), None
        events.append((qnum, sp, sy - 6, ep, (ey - 10) if ey is not None else None))
    return events


def crop_year(year: int) -> int:
    sp = spec(year)
    book = answer_book(year)
    lines_by_page = answer_lines(year)
    out_dir = BOOK / "math-bank" / "answer_crops"

    if year == 2023:
        # 速查：选择/填空的答案是紧凑区块，同区题目共享一张裁图；解答题逐题
        p1 = lines_by_page[1]
        marks = {text: y0 for y0, _, text in p1}
        choice_top = next(y for t, y in marks.items() if t.startswith("一、选择题"))
        fill_top = next(y for t, y in marks.items() if t.startswith("二、填空题"))
        solve_top = next(y for t, y in marks.items() if t.startswith("三、解答题"))
        choice_img = out_dir / "y2023_choice.png"
        fill_img = out_dir / "y2023_fill.png"
        render_crop(book, lines_by_page, (1, choice_top), (1, fill_top - 6), choice_img)
        render_crop(book, lines_by_page, (1, fill_top), (1, solve_top - 6), fill_img)
        solve_re = re.compile(r"^\s*(\d{1,2})\s*[.．、]?\s*【(?:解|证明)】")
        events = []
        expected = 17
        for page in sorted(lines_by_page):
            for y0, _y1, text in lines_by_page[page]:
                m = solve_re.match(text)
                if m and int(m.group(1)) == expected:
                    events.append((expected, page, y0))
                    expected += 1
        if [e[0] for e in events] != list(range(17, 23)):
            raise ValueError(f"2023 解答题标记异常：{[e[0] for e in events]}")
        for index, (qnum, page, y0) in enumerate(events):
            end = (events[index + 1][1], events[index + 1][2] - 10) if index + 1 < len(events) else (max(lines_by_page), None)
            render_crop(book, lines_by_page, (page, y0 - 6), end, out_dir / f"y2023_q{qnum:02d}.png")
        import shutil

        for qnum in range(1, 11):
            shutil.copyfile(choice_img, out_dir / f"y2023_q{qnum:02d}.png")
        for qnum in range(11, 17):
            shutil.copyfile(fill_img, out_dir / f"y2023_q{qnum:02d}.png")
        return 22

    if year in SCAN_LAYOUT_YEARS:
        if year == 2022:
            # 03 详解单年解析册：N. 题干 + 部分题内联【答案】；无答案题隔离
            events = events_2022(lines_by_page)
        elif year == 2020:
            # 答案册不重复题干，标记即「N.【答案】X」；解答题为「N.【解析】」「N.证明：」
            qstart_re = re.compile(r"^\s*(\d{1,2})\s*[.．]\s*(?:【(?:答案|解析)】|证明|解[:：])")
            events = question_events(lines_by_page, qstart_re, sp["total"], combined=True, book=book)
        elif year == 2016:
            # 题干 N. 起，解析标记为【详解】
            qstart_re = re.compile(r"^\s*(\d{1,2})\s*[.．](?!\d)")
            events = question_events(lines_by_page, qstart_re, sp["total"], combined=True, book=book, ans_marker="【详解】")
        elif year == 2019:
            # 选择题为（N），填空/解答为 N. 混排
            qstart_re = re.compile(r"^\s*(?:[（(]\s*(\d{1,2})\s*[）)]|(\d{1,2})\s*[.．](?!\d))")
            events = question_events(lines_by_page, qstart_re, sp["total"], combined=True, book=book)
        else:
            qstart_re = re.compile(r"^\s*[（(]\s*(\d{1,2})\s*[）)]")
            events = question_events(lines_by_page, qstart_re, sp["total"], combined=True, book=book)
    elif year in (2010, 2011, 2012, 2013, 2014, 2017):
        qstart_re = re.compile(
            r"^\s*[（(]\s*(\d{1,2})\s*[）)]\s*(?:[（(]\s*[ⅠⅡiI1]{1,3}\s*[）)])?\s*[【\[［]\s*(?:答案|解|证明)\s*[】\]］]"
        )
        events = question_events(lines_by_page, qstart_re, sp["total"], combined=False, book=book)
    elif year == 2024:
        qstart_re = re.compile(r"^\s*(\d{1,2})\s*[.．](?!\d)")
        events = question_events(lines_by_page, qstart_re, sp["total"], combined=True, book=book)
    elif year == 2026:
        qstart_re = re.compile(r"^\s*(\d{1,2})．")
        events = question_events(lines_by_page, qstart_re, sp["total"], combined=True, book=book)
    else:
        raise ValueError(f"{year} 无裁图配置")

    for qnum, sp_page, sp_y, ep_page, ep_y in events:
        render_crop(book, lines_by_page, (sp_page, sp_y), (ep_page, ep_y), out_dir / f"y{year}_q{qnum:02d}.png")
    for qnum in SHARE_PREV.get(year, set()):
        # 共享前一题的裁图（其答案在上一题裁图区间内）
        import shutil

        shutil.copyfile(out_dir / f"y{year}_q{qnum - 1:02d}.png", out_dir / f"y{year}_q{qnum:02d}.png")
    return len(events)


QLine_RE = re.compile(r"^\s*(?:#{1,6}\s*)?(?:[（(]\s*(\d{1,2})\s*[）)]|(\d{1,2})\s*[.．](?!\d))")


def crop_figures(years: list[int]) -> None:
    """为题干依赖图（has_image）的题从真题页裁「原题图」：[题号行, 下一题号行)。"""
    path = BOOK / "questions.json"
    if not path.exists():
        return
    data = json.loads(path.read_text(encoding="utf-8"))
    for chapter in data["chapters"]:
        year = int(chapter["name"].rstrip("年"))
        if year not in years:
            continue
        targets = [q for q in chapter["questions"] if q["has_image"]]
        if not targets:
            continue
        book = question_book(year)
        lines_by_page = layout_lines_for(book)
        skip = QUESTION_SKIP_PAGES.get(year, 0)
        starts: dict[int, tuple[int, float]] = {}
        expected = 1
        for page in sorted(lines_by_page):
            if page <= skip:
                continue
            for y0, _y1, text in lines_by_page[page]:
                m = QLine_RE.match(text)
                if m:
                    num = int(next(g for g in m.groups() if g is not None))
                    # 递增即收：容忍个别题号行被 OCR 漏检
                    if expected <= num <= spec(year)["total"]:
                        starts[num] = (page, y0)
                        expected = num + 1
        for q in targets:
            n = q["qnum"]
            if n not in starts:
                raise ValueError(f"{year} 第{n}题题干图定位失败")
            sp, sy = starts[n]
            if n + 1 in starts:
                ep, ey = starts[n + 1]
                end = (ep, ey - 10)
            else:
                end = (max(lines_by_page), None)
            out = BOOK / "math-bank" / "images" / "questions" / f"y{year}_q{n:02d}.png"
            render_crop(book, lines_by_page, (sp, sy - 6), end, out)
            print(f"figure {year} Q{n} -> {out.name}")


def crop_answers(years: list[int]) -> None:
    for year in years:
        count = crop_year(year)
        print(f"cropped {year}: {count} answer images")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--years", type=int, nargs="*", default=YEARS)
    parser.add_argument("--questions-only", action="store_true")
    parser.add_argument("--keys-only", action="store_true")
    parser.add_argument("--crop-only", action="store_true")
    parser.add_argument("--figures-only", action="store_true")
    args = parser.parse_args()
    if args.figures_only:
        crop_figures(args.years)
        return
    if args.crop_only:
        crop_answers(args.years)
        return
    if not args.keys_only:
        build_questions(args.years)
    if not args.questions_only:
        apply_answer_keys(args.years)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
