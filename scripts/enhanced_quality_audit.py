#!/usr/bin/env python3
"""数学四库发布前质量门禁：结构、公式、题图和答案图。"""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

from quality_check import check_question

ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = ROOT.parent.parent
REPORT_DIR = REPO_ROOT / "temp" / "math-quality"
BOOKS = ("660题", "880题", "1000题", "大学深埋")
ALLOWED_TYPES = {"选择题", "填空题", "计算题", "证明题", "解答题"}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def resource_issue(book_dir: Path, ref: Any, field: str) -> str | None:
    if isinstance(ref, dict):
        ref = ref.get("cropped")
    value = str(ref or "").strip().replace("\\", "/")
    if not value:
        return f"{field}_missing"
    viewer = (book_dir / "math-bank").resolve()
    target = (viewer / value).resolve()
    if book_dir.resolve() not in target.parents:
        return f"{field}_outside_book"
    if not target.is_file():
        return f"{field}_file_missing"
    return None


def audit_book(name: str) -> dict:
    book_dir = ROOT / name
    source = book_dir / "questions.json"
    data = json.loads(source.read_text(encoding="utf-8"))
    questions = [q for chapter in data.get("chapters", []) for q in chapter.get("questions", [])]
    uid_counts = Counter(str(q.get("uid") or "") for q in questions)
    records = []

    for question in questions:
        uid = str(question.get("uid") or "")
        issues: list[dict] = []

        def add(code: str, severity: str = "critical") -> None:
            issues.append({"code": code, "severity": severity})

        if not uid:
            add("uid_missing")
        elif uid_counts[uid] > 1:
            add("uid_duplicate")
        if len(str(question.get("content") or "").strip()) < 6:
            add("content_missing_or_too_short")
        if question.get("type") not in ALLOWED_TYPES:
            add("question_type_invalid")
        if question.get("type") == "选择题":
            options = question.get("options")
            if not isinstance(options, dict) or set(options) != set("ABCD"):
                add("options_incomplete")
            elif any(not str(options.get(key) or "").strip() for key in "ABCD"):
                add("option_text_missing")
            elif len({str(options[key]).strip() for key in "ABCD"}) != 4:
                add("duplicate_options")

        answer_issue = resource_issue(book_dir, question.get("answer_ref"), "answer_ref")
        if answer_issue:
            add(answer_issue)
        if question.get("has_image") or question.get("image_ref"):
            image_issue = resource_issue(book_dir, question.get("image_ref"), "image_ref")
            if image_issue:
                add(image_issue)

        for issue in check_question(question):
            code, severity = issue[0], issue[1]
            if severity == "critical" and not any(x["code"] == code for x in issues):
                add(code)
            elif severity != "critical":
                issues.append({"code": code, "severity": severity})

        hold = any(issue["severity"] == "critical" for issue in issues)
        records.append(
            {
                "uid": uid,
                "chapter": question.get("chapter"),
                "type": question.get("type"),
                "page": question.get("page"),
                "issues": issues,
                "hold": hold,
                "content_preview": str(question.get("content") or "")[:140],
            }
        )

    global_issues = []
    declared = int(data.get("total_questions") or 0)
    if declared != len(questions):
        global_issues.append(
            {
                "code": "total_questions_mismatch",
                "severity": "critical",
                "declared": declared,
                "actual": len(questions),
            }
        )
    for chapter in data.get("chapters", []):
        declared_chapter = chapter.get("question_count")
        actual_chapter = len(chapter.get("questions", []))
        if declared_chapter is not None and int(declared_chapter) != actual_chapter:
            global_issues.append(
                {
                    "code": "chapter_question_count_mismatch",
                    "severity": "critical",
                    "chapter": chapter.get("name"),
                    "declared": int(declared_chapter),
                    "actual": actual_chapter,
                }
            )

    held = [record for record in records if record["hold"]]
    manifest = {
        "schema_version": 1,
        "source_sha256": sha256_file(source),
        "source_uids": sorted({record["uid"] for record in held if record["uid"]}),
        "summary": {
            "total_questions": len(records),
            "verified": len(records) - len(held),
            "held": len(held),
            "verification_rate": round((len(records) - len(held)) / len(records), 6),
            "global_issues": len(global_issues),
        },
    }
    write_json(book_dir / "quality-hold.json", manifest)
    return {
        "book": name,
        "source_path": str(source),
        "source_sha256": manifest["source_sha256"],
        "summary": manifest["summary"],
        "global_issues": global_issues,
        "issue_counts": dict(
            Counter(issue["code"] for record in records for issue in record["issues"])
        ),
        "records": records,
    }


def main() -> int:
    books = [audit_book(name) for name in BOOKS]
    summary = {
        "total_questions": sum(book["summary"]["total_questions"] for book in books),
        "verified": sum(book["summary"]["verified"] for book in books),
        "held": sum(book["summary"]["held"] for book in books),
        "global_issues": sum(len(book["global_issues"]) for book in books),
    }
    write_json(REPORT_DIR / "quality_report.json", {"summary": summary, "books": books})
    write_json(
        REPORT_DIR / "quality_review.json",
        [
            {"book": book["book"], **record}
            for book in books
            for record in book["records"]
            if record["hold"]
        ],
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"报告: {REPORT_DIR / 'quality_report.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
