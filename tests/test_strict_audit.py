from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from strict_audit import (  # noqa: E402
    KimiConfig,
    StrictAuditEngine,
    build_image_request,
    create_audit_bundle,
    merge_model_results,
    parse_strict_json,
    runtime_api_key,
)


def test_bundle_is_stable_and_merges_verified(tmp_path):
    bundle = create_audit_bundle("660题", "book.pdf", 3)
    assert bundle.bundle_id == create_audit_bundle("660题", "book.pdf", 3).bundle_id
    checkpoint = tmp_path / "checkpoint.json"
    record = StrictAuditEngine(checkpoint).save(bundle, {"verdict": "verified"}, {"verdict": "pass"})
    assert record["status"] == "strictly_verified"
    assert json.loads(checkpoint.read_text(encoding="utf-8"))["records"]


@pytest.mark.parametrize("source,answer,expected", [
    (None, {"verdict": "verified"}, "pending"),
    ({"verdict": "verified"}, {"verdict": "rejected"}, "conflict"),
    ({"verdict": "uncertain"}, {"verdict": "verified"}, "hold"),
])
def test_merge_states(source, answer, expected):
    assert merge_model_results(source, answer) == expected


def test_strict_json_and_base64_request(tmp_path):
    with pytest.raises(ValueError):
        parse_strict_json("```json\n{}\n```")
    image = tmp_path / "x.png"
    image.write_bytes(b"png")
    request = build_image_request(image, "审核", KimiConfig())
    assert request["messages"][0]["content"][1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_key_is_runtime_only():
    assert runtime_api_key({"KIMI_API_KEY": "secret"}) == "secret"
    assert KimiConfig.from_env({}).endpoint == "https://api.kimi.com/coding/v1"
