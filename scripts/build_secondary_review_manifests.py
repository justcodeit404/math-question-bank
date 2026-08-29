#!/usr/bin/env python3
"""Freeze the GLM/Terra secondary-review split without exposing model verdicts.

The first 250 manifest bundles are reserved for GLM.  Any already-valid GLM
result beyond that boundary remains GLM evidence and is excluded from Terra.
All emitted task manifests contain source metadata only, never review output.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from strict_audit import atomic_write_json


VALID_ISSUES = {
    "source_truncation", "source_mismatch", "source_page_mismatch", "formula_mismatch",
    "options_mismatch", "figure_missing", "figure_mismatch", "answer_image_missing",
    "answer_mismatch", "source_image_blurry", "hold_uncertain",
}
MATCH_FIELDS = ("source_match", "answer_match", "figure_match", "formula_match", "options_match")
VISIBLE_KEYS = (
    "schema_version", "bundle_id", "book", "source_pdf", "page", "chunk_index",
    "source_image", "question_sheet", "answer_sheet", "questions", "input_hashes",
)


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def sanitize(bundle: dict[str, Any]) -> dict[str, Any]:
    return {key: bundle.get(key) for key in VISIBLE_KEYS}


def valid_glm_bundle(item: Any, bundle: dict[str, Any]) -> bool:
    if not isinstance(item, dict) or item.get("model") != "glm-5.3-flash":
        return False
    if item.get("input_hashes") != bundle.get("input_hashes"):
        return False
    rows = item.get("questions")
    if not isinstance(rows, list):
        return False
    expected = {str(question.get("uid")) for question in bundle.get("questions", [])}
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            return False
        uid = str(row.get("uid") or "")
        if uid not in expected or uid in seen:
            return False
        seen.add(uid)
        if not all(isinstance(row.get(field), bool) for field in MATCH_FIELDS):
            return False
        confidence = row.get("confidence")
        if not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
            return False
        issues = row.get("issues")
        if not isinstance(issues, list) or any(issue not in VALID_ISSUES for issue in issues):
            return False
        if "hold_uncertain" in issues and confidence > 0.6:
            return False
        if not isinstance(row.get("notes", ""), str):
            return False
    return seen == expected


def discover_valid_glm(glob_root: Path, by_id: dict[str, dict[str, Any]]) -> tuple[set[str], list[str]]:
    valid: set[str] = set()
    errors: list[str] = []
    for path in sorted(glob_root.glob("batch-*.json")):
        try:
            rows = load_json(path)
        except (OSError, ValueError, json.JSONDecodeError):
            errors.append(f"invalid_json:{path.name}")
            continue
        if not isinstance(rows, list):
            errors.append(f"not_array:{path.name}")
            continue
        for item in rows:
            bundle_id = str(item.get("bundle_id") or "") if isinstance(item, dict) else ""
            bundle = by_id.get(bundle_id)
            if not bundle:
                errors.append(f"unknown_bundle:{path.name}:{bundle_id}")
            elif not valid_glm_bundle(item, bundle):
                errors.append(f"invalid_result:{path.name}:{bundle_id}")
            elif bundle_id in valid:
                errors.append(f"duplicate_bundle:{path.name}:{bundle_id}")
            else:
                valid.add(bundle_id)
    return valid, errors


def write_manifest(path: Path, shard: str, bundles: list[dict[str, Any]]) -> None:
    atomic_write_json(path, {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "provider": "glm" if shard == "glm-target" else "terra",
        "model": "glm-5.3-flash" if shard == "glm-target" else "gpt-5.6-terra",
        "shard": shard,
        "bundles": [sanitize(bundle) for bundle in bundles],
    })


def build(manifest_path: Path, glm_results_dir: Path, output_dir: Path) -> dict[str, Any]:
    manifest = load_json(manifest_path)
    bundles = manifest.get("bundles") or []
    if len(bundles) != 1056:
        raise ValueError(f"manifest bundle 数异常: {len(bundles)}")
    by_id = {str(bundle["bundle_id"]): bundle for bundle in bundles}
    valid_glm, errors = discover_valid_glm(glm_results_dir, by_id)
    if errors:
        raise ValueError("GLM 结果校验失败: " + "; ".join(errors[:20]))

    glm_target = bundles[:250]
    preexisting_glm = [bundle for bundle in bundles[250:] if bundle["bundle_id"] in valid_glm]
    terra_candidates = [bundle for bundle in bundles[250:] if bundle["bundle_id"] not in valid_glm]
    expected_terra_ranges = {
        "terra-a": bundles[250:436],
        "terra-b": bundles[436:736],
        "terra-c": bundles[736:1056],
    }
    shards = {
        name: [bundle for bundle in group if bundle["bundle_id"] not in valid_glm]
        for name, group in expected_terra_ranges.items()
    }
    if set(bundle["bundle_id"] for bundle in terra_candidates) != {
        bundle["bundle_id"] for group in shards.values() for bundle in group
    }:
        raise AssertionError("Terra 分片覆盖不完整")

    output_dir.mkdir(parents=True, exist_ok=True)
    write_manifest(output_dir / "glm-target.json", "glm-target", glm_target)
    for name, group in shards.items():
        write_manifest(output_dir / f"{name}.json", name, group)

    assignments = []
    extra_glm_ids = {bundle["bundle_id"] for bundle in preexisting_glm}
    for index, bundle in enumerate(bundles):
        provider = "glm" if index < 250 or bundle["bundle_id"] in extra_glm_ids else "terra"
        assignments.append({"bundle_id": bundle["bundle_id"], "secondary_provider": provider})
    plan = {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "manifest": str(manifest_path),
        "glm_boundary_exclusive": 250,
        "preexisting_glm_bundles": [bundle["bundle_id"] for bundle in preexisting_glm],
        "assignments": assignments,
    }
    atomic_write_json(output_dir / "secondary-plan.json", plan)

    def count(group: list[dict[str, Any]]) -> dict[str, int]:
        return {"bundles": len(group), "uids": sum(len(bundle.get("questions") or []) for bundle in group)}

    summary = {
        "glm_target": count(glm_target),
        "valid_glm_now": count([by_id[bundle_id] for bundle_id in valid_glm]),
        "preexisting_glm_outside_boundary": count(preexisting_glm),
        "terra_target": count(terra_candidates),
        "shards": {name: count(group) for name, group in shards.items()},
    }
    atomic_write_json(output_dir / "summary.json", summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="生成 GLM/Terra 互斥二审清单")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--glm-results-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.manifest, args.glm_results_dir, args.output_dir), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
