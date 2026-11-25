import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from build_linliu6 import ANSWER_TITLE_RE, SET_NAMES


def test_linliu6_structure_and_answers():
    data = json.loads((ROOT / "李林六套卷" / "questions.json").read_text(encoding="utf-8"))
    assert data["total_questions"] == 132
    assert len(data["chapters"]) == 6
    uids = set()
    keyed = 0
    for set_index, chapter in enumerate(data["chapters"], 1):
        questions = chapter["questions"]
        assert chapter["question_count"] == 22
        assert chapter["name"] == f"第{SET_NAMES[set_index - 1]}套"
        assert [q["qnum"] for q in questions] == list(range(1, 23))
        assert [q["type"] for q in questions[:16]] == ["选择题"] * 10 + ["填空题"] * 6
        assert all(q["type"] in {"计算题", "证明题"} for q in questions[16:])
        start = (set_index - 1) * 5 + 2
        assert {q["page"] for q in questions} <= set(range(start, start + 5))
        assert [q["page"] for q in questions] == sorted(q["page"] for q in questions)
        for q in questions:
            assert q["uid"] not in uids
            uids.add(q["uid"])
            assert q["has_image"] is False and q["image_ref"] is None
            assert (ROOT / "李林六套卷" / "math-bank" / q["answer_ref"]).is_file()
            if q["qnum"] <= 10:
                keyed += 1
                assert q["answer_structured"]["judge_mode"] == "choice_exact"
                assert q["answer_structured"]["canonical"] in "ABCD"
    assert keyed == 60
    all_questions = [q for chapter in data["chapters"] for q in chapter["questions"]]
    assert sum(q["type"] == "计算题" for q in all_questions) == 31
    assert sum(q["type"] == "证明题" for q in all_questions) == 5
    assert sum(bool(q["sub_questions"]) for q in all_questions) == 18


def test_linliu6_answer_title_regex_accepts_six_sets():
    text = "\n".join(
        f"# 考研数学冲刺预测6套卷第{name}套参考答案及解析"
        for name in SET_NAMES
    )
    assert "".join(match.group(1) for match in ANSWER_TITLE_RE.finditer(text)) == SET_NAMES
