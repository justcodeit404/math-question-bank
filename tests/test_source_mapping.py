import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from source_mapping import resolve_question_pdf, validate_mapping


def test_660_high_and_linear_use_different_pdfs():
    high = resolve_question_pdf({"_book": "660题", "uid": "660-460", "page": 167})
    linear = resolve_question_pdf({"_book": "660题", "uid": "660-461", "page": 4})
    assert high is not None and high.path.name == "《基础过关660》-高数篇 .pdf"
    assert linear is not None and linear.path.name == "《基础过关660》-线代篇.pdf"


def test_880_high_and_linear_use_different_pdfs():
    high = resolve_question_pdf({"_book": "880题", "uid": "880-616", "page": 89})
    linear = resolve_question_pdf({"_book": "880题", "uid": "880-617", "page": 1})
    assert high is not None and "高数篇" in high.path.name
    assert linear is not None and "线代篇" in linear.path.name


def test_university_linear_is_selected_by_chapter():
    ref = resolve_question_pdf(
        {"_book": "大学深埋", "uid": "大学深埋-线代-例1-p1", "chapter": "线代 · 行列式和矩阵", "page": 1}
    )
    assert ref is not None and "线代讲义" in ref.path.name


def test_mapping_reports_missing_pdf_without_throwing(monkeypatch):
    monkeypatch.setattr("source_mapping.PDF_ROOT", Path("definitely-missing-pdf-root"))
    errors = validate_mapping([{"_book": "1000题", "uid": "1000-1", "page": 1}])
    assert errors and "source PDF missing" in errors[0]
