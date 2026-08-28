"""四库题目到原始题目/答案 PDF 的只读映射。

题目 JSON 的 ``page`` 在不同题库中均是各自 PDF 的页码；660、880 和大学深埋
分别把高数与线代放在不同 PDF 中，因此不能只按题库名称选择一个文件。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
BANK_ROOT = SCRIPT_DIR.parent
REPO_ROOT = BANK_ROOT.parent.parent
PDF_ROOT = REPO_ROOT / "资料" / "数学2" / "电子资料"


@dataclass(frozen=True)
class PdfRef:
    """一本原始 PDF 及其页码信息。"""

    path: Path
    page: int
    role: str = "question"


QUESTION_PDFS: dict[str, str] = {
    "660-gaosh": "《基础过关660》-高数篇 .pdf",
    "660-linear": "《基础过关660》-线代篇.pdf",
    "880-gaosh": "【A4紧凑版】李林880数二高数篇做题本.pdf",
    "880-linear": "【横版】李林880数二线代篇做题本.pdf",
    "1000": "27张宇1000题数二-试题册.pdf",
    "university-gaosh": "27大雪深埋强化讲义书（扫描版）.pdf",
    "university-linear": "【横版】27ep线代讲义例题做题本.pdf",
}

ANSWER_PDFS: dict[str, str] = {
    # 660 的答案就在对应题册 PDF 的后半部分，具体题号到裁图已在 answer_ref 中保存。
    "660-gaosh": "《基础过关660》-高数篇 .pdf",
    "660-linear": "《基础过关660》-线代篇.pdf",
    "880": "【PDF】27版880参考答案.pdf",
    "1000": "27张宇1000题数二-解析册.pdf",
    "university": "27大雪深埋强化讲义书（扫描版）.pdf",
}


def _number_from_uid(uid: str) -> int | None:
    match = re.search(r"-(\d+)(?:$|-p)", str(uid or ""))
    if not match:
        match = re.search(r"-(\d+)$", str(uid or ""))
    return int(match.group(1)) if match else None


def _book_key(question: dict[str, Any]) -> str:
    book = str(question.get("_book") or question.get("book") or "")
    uid = str(question.get("uid") or "")
    chapter = str(question.get("chapter") or "")
    number = _number_from_uid(uid)

    if book == "660题":
        return "660-linear" if (number is not None and number >= 461) else "660-gaosh"
    if book == "880题":
        return "880-linear" if (number is not None and number >= 617) else "880-gaosh"
    if book == "1000题":
        return "1000"
    if book == "大学深埋":
        return "university-linear" if chapter.startswith("线代") else "university-gaosh"
    raise KeyError(f"未知题库: {book}")


def resolve_question_pdf(question: dict[str, Any]) -> PdfRef | None:
    """返回题目对应的原始题目 PDF；文件不存在时仍返回路径供诊断。"""

    page = question.get("page")
    if page is None:
        return None
    try:
        page_number = int(page)
    except (TypeError, ValueError):
        return None
    key = _book_key(question)
    return PdfRef(PDF_ROOT / QUESTION_PDFS[key], page_number, "question")


def resolve_answer_pdf(question: dict[str, Any]) -> PdfRef | None:
    """返回答案来源 PDF（页码通常由 answer_ref 裁图记录，故页码为0）。"""

    key = _book_key(question)
    answer_key = key if key in {"660-gaosh", "660-linear"} else (
        "880" if key.startswith("880-") else "1000" if key == "1000" else "university"
    )
    return PdfRef(PDF_ROOT / ANSWER_PDFS[answer_key], 0, "answer")


def validate_mapping(questions: list[dict[str, Any]]) -> list[str]:
    """检查映射是否存在、页码是否为正整数，返回可读错误列表。"""

    errors: list[str] = []
    for q in questions:
        uid = str(q.get("uid") or "?")
        ref = resolve_question_pdf(q)
        if ref is None:
            errors.append(f"{uid}: missing source page")
            continue
        if ref.page <= 0:
            errors.append(f"{uid}: invalid source page {ref.page}")
        if not ref.path.is_file():
            errors.append(f"{uid}: source PDF missing: {ref.path.name}")
    return errors

