"""Regression coverage for the pure rule-based math-bank quality gate."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
BANK_ROOT = SCRIPTS_DIR.parent
sys.path.insert(0, str(SCRIPTS_DIR))

from quality_check import (  # noqa: E402
    _fix_malformed_subscript,
    build_report,
    check_question,
    check_text,
)


def codes(text: str) -> set[str]:
    return {issue[0] for issue in check_text(text)}


def test_valid_latex_is_not_flagged():
    assert codes(r"函数满足 $f(x)=\frac{1}{2}x^2$") == set()


def test_math_delimiter_and_fraction_errors_are_detected():
    assert "missing_dollar" in codes(r"函数为 \frac{1}{2}")
    assert "malformed_frac" in codes(r"$\frac{1}$")
    assert "unbalanced_dollars" in codes(r"$x + 1")


def test_safe_subscript_fix_is_exact_and_idempotent():
    broken = r"$a_{(_{0},_{1})}$"
    fixed = r"$a_{(0,1)}$"
    assert _fix_malformed_subscript(broken) == fixed
    assert _fix_malformed_subscript(fixed) == fixed


def test_question_shape_checks_choice_and_fill_blank():
    choice_codes = {issue[0] for issue in check_question({"type": "选择题", "options": []})}
    assert {"options_type", "missing_options"} <= choice_codes

    fill_codes = {issue[0] for issue in check_question({"type": "填空题", "content": "求极限"})}
    assert "missing_blank" in fill_codes


def test_explicit_figure_cue_requires_displayable_question_image():
    question = {
        "type": "选择题",
        "content": "图中实线和虚线分别表示甲、乙的速度曲线，则（ ）",
        "options": {"A": "1", "B": "2", "C": "3", "D": "4"},
        "has_image": False,
        "image_ref": None,
    }
    assert "missing_figure" in {issue[0] for issue in check_question(question)}

    question["has_image"] = True
    question["image_ref"] = {"cropped": "images/p024_q3.png"}
    assert "missing_figure" not in {issue[0] for issue in check_question(question)}


def test_missing_referenced_image_file_is_critical(tmp_path):
    question = {
        "id": "3",
        "type": "选择题",
        "content": "如图所示，则（ ）",
        "options": {"A": "1", "B": "2", "C": "3", "D": "4"},
        "has_image": True,
        "image_ref": {"cropped": "images/not-found.png"},
    }
    report = build_report([question], tmp_path)
    assert "missing_image_file" in {issue["code"] for issue in report[0]["issues"]}


@pytest.mark.parametrize(
    ("book", "uid", "crop"),
    [
        ("1000题", "1000-基础·一元函数积分学的概念与性质-3", "images/p024_q3.png"),
        ("1000题", "1000-基础·一元函数积分学的应用(一)-4", "images/p031_q4.png"),
        ("1000题", "1000-强化·一元函数积分学的应用(一)-10", "images/p087_q10.png"),
        ("1000题", "1000-强化·一元函数积分学的应用(一)-24", "images/p089_q24.png"),
        ("大学深埋", "大学深埋-微积分应用-例18-p125", "images/p125_example18.png"),
    ],
)
def test_known_figure_questions_keep_their_crops(book, uid, crop):
    data = json.loads((BANK_ROOT / book / "questions.json").read_text(encoding="utf-8"))
    questions = [q for chapter in data["chapters"] for q in chapter["questions"]]
    question = next(q for q in questions if q["uid"] == uid)
    assert question["has_image"] is True
    assert question["image_ref"]["cropped"] == crop
    assert (BANK_ROOT / book / "math-bank" / crop).is_file()
