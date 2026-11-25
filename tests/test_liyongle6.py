import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from build_liyongle6 import normalize_math, parse_choice


def test_inline_choices_and_literal_left_brace():
    text = normalize_math(r"1. 极限 \(\lim_{x\to 0}f(x)=\) A. 0. B. \(1\). C. \(2\). D. \(3\).")
    content, options = parse_choice(text[3:])
    assert content == r"极限 $\lim_{x\to 0}f(x)=$"
    assert list(options) == list("ABCD")
    assert options["B"] == r"$1$."
    assert r"\left\lbrace" in normalize_math(r"$\left\{\begin{array}{l}x\\y\end{array}\right.$")


def test_liyongle6_structure_and_resources():
    data = json.loads((ROOT / "李永乐六套卷" / "questions.json").read_text(encoding="utf-8"))
    assert data["total_questions"] == 132
    assert len(data["chapters"]) == 6
    uids = set()
    for set_index, chapter in enumerate(data["chapters"], 1):
        questions = chapter["questions"]
        assert chapter["question_count"] == 22
        assert [q["qnum"] for q in questions] == list(range(1, 23))
        assert [q["type"] for q in questions[:16]] == ["选择题"] * 10 + ["填空题"] * 6
        assert all(q["type"] in {"计算题", "证明题"} for q in questions[16:])
        content_start = (set_index - 1) * 4 + 2
        assert [q["page"] for q in questions] == sorted(q["page"] for q in questions)
        for q in questions:
            assert q["uid"] not in uids
            uids.add(q["uid"])
            assert content_start <= q["page"] <= content_start + 2
            assert (ROOT / "李永乐六套卷" / "math-bank" / q["image_ref"]["cropped"]).is_file()
            assert q["has_image"] == (set_index == 4 and q["qnum"] == 20)
            if set_index == 3 and 4 <= q["qnum"] <= 9:
                assert q["answer_ref"] is None
            else:
                assert (ROOT / "李永乐六套卷" / "math-bank" / q["answer_ref"]).is_file()
            assert q["answer_incomplete"] == (set_index == 3 and 4 <= q["qnum"] <= 10)


def test_liyongle6_choice_answer_keys():
    data = json.loads((ROOT / "李永乐六套卷" / "questions.json").read_text(encoding="utf-8"))
    questions = [q for chapter in data["chapters"] for q in chapter["questions"]]
    keyed = [q for q in questions if q.get("answer_structured")]
    assert len(keyed) == 54
    assert all(q["answer_structured"]["judge_mode"] == "choice_exact" for q in keyed)
    assert all(q["answer_structured"]["canonical"] in "ABCD" for q in keyed)
