#!/usr/bin/env python3
"""Build sanitized Luna-only manifests for bundles not covered by Kimi.

The generated files intentionally contain only the source page, rendered sheets,
question metadata, and input hashes.  Provider conclusions are never copied.
"""
from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from strict_audit import atomic_write_json


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _is_kimi_current(record: dict[str, Any], bundle: dict[str, Any]) -> bool:
    kimi = record.get("kimi") or {}
    if kimi.get("status") != "ok":
        return False
    # A changed input invalidates an old provider result and must return to the gap.
    old_hashes = kimi.get("input_hashes") or (kimi.get("response_meta") or {}).get("input_hashes")
    return not old_hashes or old_hashes == (bundle.get("input_hashes") or {})


def _sanitize(bundle: dict[str, Any]) -> dict[str, Any]:
    allowed = (
        "schema_version", "bundle_id", "book", "source_pdf", "page", "chunk_index",
        "source_image", "question_sheet", "answer_sheet", "questions", "input_hashes",
    )
    return {key: bundle.get(key) for key in allowed}


def build_gap_manifests(manifest_path: Path, checkpoint_path: Path, output_dir: Path) -> dict[str, Any]:
    manifest = _load(manifest_path)
    checkpoint = _load(checkpoint_path) if checkpoint_path.is_file() else {"bundles": {}}
    checkpoint_bundles = checkpoint.get("bundles") or {}
    missing: list[dict[str, Any]] = []
    for bundle in manifest.get("bundles", []):
        record = checkpoint_bundles.get(str(bundle.get("bundle_id")), {})
        if not _is_kimi_current(record, bundle):
            missing.append(_sanitize(bundle))

    by_book: dict[str, list[dict[str, Any]]] = {"880题": [], "大学深埋": []}
    unexpected: list[dict[str, Any]] = []
    for bundle in missing:
        if bundle.get("book") in by_book:
            by_book[str(bundle["book"])].append(bundle)
        else:
            unexpected.append(bundle)
    if unexpected:
        raise ValueError(f"Kimi 缺口包含计划外题库: {sorted({x.get('book') for x in unexpected})}")
    if len(by_book["880题"]) != 263 or len(by_book["大学深埋"]) != 263:
        raise ValueError(
            f"缺口数量不符合冻结快照: 880={len(by_book['880题'])}, 大学深埋={len(by_book['大学深埋'])}"
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    university = by_book["大学深埋"]
    shards = {
        "880": by_book["880题"],
        "university-a": university[: math.ceil(len(university) / 2)],
        "university-b": university[math.ceil(len(university) / 2) :],
    }
    created = datetime.now(timezone.utc).isoformat()
    summaries: dict[str, Any] = {}
    for shard, bundles in shards.items():
        payload = {
            "schema_version": 1,
            "created_at": created,
            "provider": "luna",
            "model": "gpt-5.6-luna",
            "shard": shard,
            "bundles": bundles,
        }
        path = output_dir / f"{shard}.json"
        atomic_write_json(path, payload)
        summaries[shard] = {
            "path": str(path),
            "bundles": len(bundles),
            "uids": sum(len(x.get("questions") or []) for x in bundles),
            "bundle_ids": [x["bundle_id"] for x in bundles],
        }
    summary = {
        "created_at": created,
        "manifest": str(manifest_path),
        "checkpoint": str(checkpoint_path),
        "total_missing_bundles": len(missing),
        "total_missing_uids": sum(len(x.get("questions") or []) for x in missing),
        "shards": summaries,
    }
    atomic_write_json(output_dir / "summary.json", summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="生成 Kimi 缺口的 Luna 脱敏审核分片")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    summary = build_gap_manifests(args.manifest, args.checkpoint, args.output_dir)
    print(json.dumps({k: v for k, v in summary.items() if k != "shards"}, ensure_ascii=False))
    for shard, item in summary["shards"].items():
        print(json.dumps({"shard": shard, "bundles": item["bundles"], "uids": item["uids"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
