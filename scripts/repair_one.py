#!/usr/bin/env python3
"""单题修复端到端：应用修复 → 单册质量门禁 → 重出 data.js → 更新台账哈希 → 打印上云清单。

用法（修复条目须先写进 apply_isolated_repairs.py 的 REPAIRS）：
    python scripts/repair_one.py --book 1000题 --uid 1000-基础·多元函数微分学-15

上云（修复默认要上云，见根 AGENTS.md §1）：
    bash scripts/sync_book_to_cloud.sh 1000题
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import apply_isolated_repairs
import enhanced_quality_audit
from generate_data_js import BANK_CONFIG, generate_data_js, write_stats_js
from quality_pipeline import question_content_hash

ROOT = Path(__file__).resolve().parent.parent
LEDGER_PATH = ROOT / "quality-ledger.json"


def book_key(book_name: str) -> str:
    for key, cfg in BANK_CONFIG.items():
        if cfg["name"] == book_name:
            return key
    raise SystemExit(f"未知题库: {book_name}（可选: {', '.join(cfg['name'] for cfg in BANK_CONFIG.values())}）")


def sync_ledger_hash(book_name: str, uid: str) -> str:
    data = json.loads((ROOT / book_name / "questions.json").read_text(encoding="utf-8"))
    question = next(
        (q for ch in data.get("chapters", []) for q in ch.get("questions", []) if q.get("uid") == uid),
        None,
    )
    if question is None:
        raise SystemExit(f"{book_name} 找不到 UID: {uid}")
    new_hash = question_content_hash(question)

    ledger = json.loads(LEDGER_PATH.read_text(encoding="utf-8"))
    entry = ledger.get("entries", {}).get(uid)
    if entry is None:
        raise SystemExit(f"quality-ledger.json 找不到 UID: {uid}")
    entry["content_hash"] = new_hash
    entry["last_reviewed"] = datetime.now(timezone.utc).isoformat()
    ledger["updated_at"] = datetime.now(timezone.utc).isoformat()
    tmp = LEDGER_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(ledger, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(LEDGER_PATH)
    return new_hash


def rebuild_data_js(book_name: str) -> None:
    key = book_key(book_name)
    stats = {}
    for k, cfg in BANK_CONFIG.items():
        if k == key:
            stats[cfg["name"]] = generate_data_js(k, cfg["questions"], cfg["data_js"])
        else:
            data = json.loads(cfg["questions"].read_text(encoding="utf-8"))
            stats[cfg["name"]] = {
                "title": data.get("title", ""),
                "total": sum(len(ch.get("questions", [])) for ch in data.get("chapters", [])),
                "chapters": len(data.get("chapters", [])),
            }
    write_stats_js(stats)


def print_sync_checklist(book_name: str) -> None:
    bank_dir = ROOT / book_name / "math-bank"
    print("\n=== 上云清单（修复默认要上云）===")
    for name in ("data.js", "index.html"):
        path = bank_dir / name
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        print(f"{name}: {digest}")
    print(f"scp {bank_dir / 'data.js'} {bank_dir / 'index.html'} "
          f'"ubuntu@122.51.26.195:/home/ubuntu/kaoyan/apps/bank-math/{book_name}/math-bank/"')
    print("ssh ubuntu@122.51.26.195 \"sha256sum "
          f"/home/ubuntu/kaoyan/apps/bank-math/{book_name}/math-bank/data.js\"  # 与上面本地哈希比对")
    print(f"浏览器验证: https://study.xinghebox.cloud/banks/math/{book_name}/math-bank/ （Ctrl+F5）")
    print("或跑: bash scripts/sync_book_to_cloud.sh " + book_name)


def main() -> int:
    parser = argparse.ArgumentParser(description="单题修复端到端")
    parser.add_argument("--book", required=True, help="题库目录名，如 1000题")
    parser.add_argument("--uid", required=True, help="题目 uid")
    args = parser.parse_args()

    if args.book not in apply_isolated_repairs.REPAIRS:
        raise SystemExit(f"apply_isolated_repairs.py 中没有 {args.book} 的修复清单")
    if args.uid not in apply_isolated_repairs.REPAIRS[args.book]:
        raise SystemExit(f"修复清单中没有 {args.uid}；请先把修复写进 apply_isolated_repairs.py 的 REPAIRS")

    print("── 1/4 应用修复 ──")
    apply_isolated_repairs.apply_repairs(book=args.book, uid=args.uid)

    print("── 2/4 单册质量门禁 ──")
    enhanced_quality_audit.main(["--book", args.book])

    print("── 3/4 重出 data.js ──")
    rebuild_data_js(args.book)

    print("── 4/4 更新台账哈希 ──")
    new_hash = sync_ledger_hash(args.book, args.uid)
    print(f"quality-ledger.json 已更新 {args.uid} content_hash = {new_hash[:16]}…")

    print_sync_checklist(args.book)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
