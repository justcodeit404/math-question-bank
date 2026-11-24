import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from build_zhenti import ISOLATED, SHARE_PREV, spec

BOOK = ROOT / "历年真题"


def load():
    return json.loads((BOOK / "questions.json").read_text(encoding="utf-8"))


def test_zhenti_structure():
    data = load()
    assert data["bank"] == "历年真题"
    assert len(data["chapters"]) == 17
    assert data["total_questions"] == 385
    assert data["total_questions"] == sum(ch["question_count"] for ch in data["chapters"])
    uids = set()
    for chapter in data["chapters"]:
        year = int(chapter["name"].rstrip("年"))
        sp = spec(year)
        questions = chapter["questions"]
        assert chapter["question_count"] == sp["total"]
        assert [q["qnum"] for q in questions] == list(range(1, sp["total"] + 1))
        assert [q["type"] for q in questions[: sp["choice_end"]]] == ["选择题"] * sp["choice_end"]
        assert [q["type"] for q in questions[sp["choice_end"] : sp["blank_end"]]] == ["填空题"] * 6
        assert all(q["type"] in {"计算题", "证明题"} for q in questions[sp["blank_end"] :])
        assert [q["page"] for q in questions] == sorted(q["page"] for q in questions)
        for q in questions:
            assert q["uid"] not in uids
            uids.add(q["uid"])
            assert q["chapter"] == chapter["name"]
            if q["qnum"] in ISOLATED.get(year, set()):
                assert q["answer_incomplete"] is True and q["answer_ref"] is None
            else:
                assert q["answer_incomplete"] is False
                assert (BOOK / "math-bank" / q["answer_ref"]).is_file()


def test_zhenti_builder_choice_keys():
    data = load()
    for year in (2023, 2024, 2026):
        chapter = next(ch for ch in data["chapters"] if ch["name"] == f"{year}年")
        sp = spec(year)
        for q in chapter["questions"][: sp["choice_end"]]:
            structured = q["answer_structured"]
            assert structured and structured["judge_mode"] == "choice_exact"
            assert structured["canonical"] in "ABCD"


def test_zhenti_ai_answered_2022():
    """2022 年 6 道原书缺答案的题由 AI 解答补齐，答案与裁图必须存在。"""
    from build_zhenti import AI_ANSWERED

    data = load()
    chapter = next(ch for ch in data["chapters"] if ch["name"] == "2022年")
    expected = {2: "D", 3: "B", 5: "A", 13: r"\frac{8\sqrt{3}}{9}\pi",
                14: r"C_1+\mathrm{e}^x(C_2\cos 2x+C_3\sin 2x)", 15: r"\frac{\pi}{12}"}
    assert set(AI_ANSWERED[2022]) == set(expected)
    for qnum, canonical in expected.items():
        q = chapter["questions"][qnum - 1]
        assert q["answer_incomplete"] is False
        assert (BOOK / "math-bank" / q["answer_ref"]).is_file()
        assert q["answer_structured"]["canonical"] == canonical


def test_zhenti_source_mapping():
    from source_mapping import resolve_answer_pdf, resolve_question_pdf

    for year, page in ((2010, 1), (2015, 2), (2022, 3), (2024, 1), (2026, 2)):
        q = {"_book": "历年真题", "uid": f"历年真题-{year}-1", "chapter": f"{year}年", "page": page}
        ref = resolve_question_pdf(q)
        assert ref is not None and ref.path.is_file(), ref
        ans = resolve_answer_pdf(q)
        assert ans is not None and ans.path.is_file(), ans


def test_zhenti_share_prev_crops_exist():
    data = load()
    for year, qnums in SHARE_PREV.items():
        chapter = next(ch for ch in data["chapters"] if ch["name"] == f"{year}年")
        for qnum in qnums:
            q = chapter["questions"][qnum - 1]
            assert (BOOK / "math-bank" / q["answer_ref"]).is_file()
