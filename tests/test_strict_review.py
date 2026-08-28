from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import strict_review  # noqa: E402


def _checkpoint() -> dict:
    bundle = {
        "bundle_id": "b1",
        "book": "660题",
        "page": 1,
        "input_hashes": {"source": "s", "questions": "q", "answers": "a"},
        "questions": [{"uid": "u1"}, {"uid": "u2"}],
    }
    return {"schema_version": 2, "bundles": {"b1": {"bundle": bundle}}}


def test_ingest_requires_exact_uid_set(tmp_path, monkeypatch):
    monkeypatch.setattr(strict_review, "CHECKPOINT_PATH", tmp_path / "checkpoint.json")
    path = tmp_path / "luna.json"
    path.write_text(json.dumps([{"bundle_id": "b1", "questions": [{
        "uid": "u1", "source_match": True, "answer_match": True,
        "figure_match": True, "formula_match": True, "options_match": True,
        "confidence": 0.99, "issues": [],
    }]}]), encoding="utf-8")
    checkpoint = _checkpoint()
    strict_review.ingest_provider(checkpoint, "luna", path)
    assert checkpoint["bundles"]["b1"]["luna"]["status"] == "invalid_response"
    assert checkpoint["questions"]["u1"]["overall_status"] == "pending"


def test_both_models_produce_strict_status(tmp_path, monkeypatch):
    monkeypatch.setattr(strict_review, "CHECKPOINT_PATH", tmp_path / "checkpoint.json")
    checkpoint = _checkpoint()
    row = {
        "uid": "u1", "source_match": True, "answer_match": True,
        "figure_match": True, "formula_match": True, "options_match": True,
        "confidence": 0.99, "issues": [],
    }
    row2 = dict(row, uid="u2")
    for provider in ("luna", "kimi"):
        path = tmp_path / f"{provider}.json"
        path.write_text(json.dumps([{"bundle_id": "b1", "questions": [row, row2]}]), encoding="utf-8")
        strict_review.ingest_provider(checkpoint, provider, path)
    assert checkpoint["questions"]["u1"]["overall_status"] == "strictly_verified"
    assert checkpoint["questions"]["u2"]["overall_status"] == "strictly_verified"
