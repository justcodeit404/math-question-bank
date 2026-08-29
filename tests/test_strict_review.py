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


def test_configured_glm_is_required_secondary(tmp_path, monkeypatch):
    monkeypatch.setattr(strict_review, "CHECKPOINT_PATH", tmp_path / "checkpoint.json")
    checkpoint = _checkpoint()
    checkpoint["bundles"]["b1"]["secondary_provider"] = "glm"
    row = {
        "uid": "u1", "source_match": True, "answer_match": True,
        "figure_match": True, "formula_match": True, "options_match": True,
        "confidence": 0.99, "issues": [],
    }
    row2 = dict(row, uid="u2")
    for provider, model in (("kimi", strict_review.KIMI_MODEL), ("glm", "glm-5.3-flash")):
        item = {
            "bundle_id": "b1", "model": model,
            "input_hashes": checkpoint["bundles"]["b1"]["bundle"]["input_hashes"],
            "questions": [dict(row), dict(row2)],
        }
        if provider == "glm":
            item["reviewed_at"] = "2026-08-29T00:00:00+00:00"
            for item_row in item["questions"]:
                item_row["notes"] = "视觉核验"
        path = tmp_path / f"{provider}.json"
        path.write_text(json.dumps([item]), encoding="utf-8")
        strict_review.ingest_provider(checkpoint, provider, path)
    assert checkpoint["questions"]["u1"]["secondary_provider"] == "glm"
    assert checkpoint["questions"]["u1"]["overall_status"] == "strictly_verified"


def test_terra_rejects_nonstandard_issue_code(tmp_path, monkeypatch):
    monkeypatch.setattr(strict_review, "CHECKPOINT_PATH", tmp_path / "checkpoint.json")
    checkpoint = _checkpoint()
    checkpoint["bundles"]["b1"]["secondary_provider"] = "terra"
    rows = []
    for uid in ("u1", "u2"):
        rows.append({
            "uid": uid, "source_match": True, "answer_match": True,
            "figure_match": True, "formula_match": True, "options_match": True,
            "confidence": 0.99, "issues": ["中文问题"], "notes": "视觉核验",
        })
    path = tmp_path / "terra.json"
    path.write_text(json.dumps([{
        "bundle_id": "b1", "provider": "terra", "model": "gpt-5.6-terra",
        "reviewed_at": "2026-08-29T00:00:00+00:00",
        "input_hashes": checkpoint["bundles"]["b1"]["bundle"]["input_hashes"],
        "questions": rows,
    }]), encoding="utf-8")
    strict_review.ingest_provider(checkpoint, "terra", path)
    assert checkpoint["bundles"]["b1"]["terra"]["status"] == "invalid_response"
