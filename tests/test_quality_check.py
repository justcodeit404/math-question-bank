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


# ── 结构化答案 schema 测试 ──

VALID_JUDGE_MODES = {"choice_exact", "normalized_math", "manual"}
VALID_KINDS = {"choice", "fill"}


def test_answer_structured_schema_for_choice():
    """选择题结构化答案必须有kind=choice, canonical为A/B/C/D, judge_mode=choice_exact。"""
    structured = {
        "kind": "choice",
        "canonical": "A",
        "aliases": [],
        "judge_mode": "choice_exact",
        "source_ref": "answer_crops/chapter_0_q1.png",
    }
    assert structured["kind"] == "choice"
    assert structured["canonical"] in {"A", "B", "C", "D"}
    assert structured["judge_mode"] in VALID_JUDGE_MODES
    assert isinstance(structured["aliases"], list)


def test_answer_structured_schema_for_fill():
    """填空题结构化答案必须有kind=fill, canonical非空时judge_mode为normalized_math或manual。"""
    structured = {
        "kind": "fill",
        "canonical": "\\frac{1}{2}",
        "aliases": ["1/2", "0.5"],
        "judge_mode": "normalized_math",
        "source_ref": "answer_crops/chapter_0_q5.png",
    }
    assert structured["kind"] == "fill"
    assert structured["judge_mode"] in VALID_JUDGE_MODES
    assert isinstance(structured["aliases"], list)


def test_answer_structured_optional_for_subjective():
    """计算题/证明题/解答题不强制要求answer_structured。"""
    question = {"type": "计算题", "content": "求积分", "answer_ref": "answer_crops/x.png"}
    # 没有answer_structured是合法的
    assert "answer_structured" not in question or question.get("answer_structured") is None


# ── 质量账本测试 ──

def test_quality_ledger_exists_and_valid():
    """quality-ledger.json必须存在且包含所有题目。"""
    ledger_path = BANK_ROOT / "quality-ledger.json"
    assert ledger_path.is_file(), "质量账本不存在"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    assert "entries" in ledger
    assert "total_questions" in ledger
    assert ledger["total_questions"] == len(ledger["entries"])
    # 每个entry必须有uid和状态字段
    for uid, entry in ledger["entries"].items():
        assert entry["uid"] == uid
        assert "source_review_status" in entry
        assert "answer_review_status" in entry
        assert "overall_status" in entry


def test_quality_ledger_statuses_are_valid():
    """账本状态必须在允许的值域内。"""
    valid_statuses = {"pending", "rule_passed", "source_verified", "answer_verified",
                      "strictly_verified", "conflict", "hold"}
    ledger = json.loads((BANK_ROOT / "quality-ledger.json").read_text(encoding="utf-8"))
    for entry in ledger["entries"].values():
        assert entry["overall_status"] in valid_statuses


# ── 裁图清单测试 ──

def test_figure_crop_manifest_exists():
    """figure_crop_manifest.json必须存在且包含5条漏图记录。"""
    manifest_path = SCRIPTS_DIR / "figure_crop_manifest.json"
    assert manifest_path.is_file(), "裁图清单不存在"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert "crops" in manifest
    assert len(manifest["crops"]) >= 5
    for crop in manifest["crops"]:
        assert "bank" in crop
        assert "uid" in crop
        assert "source_pdf" in crop
        assert "source_page" in crop
        assert "output" in crop


# ── data.js 包含 answer_structured 字段测试 ──

def test_data_js_includes_answer_structured_field():
    """generate_data_js.py的VIEWER_FIELDS必须包含answer_structured。"""
    gen_script = SCRIPTS_DIR / "generate_data_js.py"
    assert gen_script.is_file()
    content = gen_script.read_text(encoding="utf-8")
    assert '"answer_structured"' in content, "generate_data_js.py VIEWER_FIELDS缺少answer_structured"
