"""Regression coverage for the pure rule-based math-bank quality gate."""
from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from quality_check import (  # noqa: E402
    _fix_malformed_subscript,
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
