#!/usr/bin/env python3
"""Offline plumbing for strict, page-level math-bank audits.

This module deliberately does not make network calls.  It prepares a Kimi
OpenAI-compatible vision request and persists model results supplied by a
caller, leaving transport, retries and human approval to the surrounding
pipeline.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Mapping

try:  # Support both ``python scripts/strict_audit.py`` and package imports.
    from source_mapping import resolve_answer_pdf, resolve_question_pdf
except ImportError:  # pragma: no cover - only relevant when packaged differently
    resolve_answer_pdf = resolve_question_pdf = None  # type: ignore[assignment]

DEFAULT_ENDPOINT = "https://api.kimi.com/coding/v1"
DEFAULT_MODEL = "kimi-for-coding"
FINAL_STATUSES = {"strictly_verified", "conflict", "hold", "pending"}
_VERIFIED = {"verified", "pass", "passed", "ok", "true"}
_REJECTED = {"rejected", "fail", "failed", "invalid", "false"}
_UNCERTAIN = {"uncertain", "hold", "pending", "unknown"}


@dataclass(frozen=True)
class KimiConfig:
    """Non-secret runtime configuration.  The API key is never stored here."""

    endpoint: str = DEFAULT_ENDPOINT
    model: str = DEFAULT_MODEL

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "KimiConfig":
        env = os.environ if environ is None else environ
        return cls(
            endpoint=(env.get("KIMI_API_BASE") or DEFAULT_ENDPOINT).rstrip("/"),
            model=env.get("KIMI_MODEL") or DEFAULT_MODEL,
        )


def runtime_api_key(environ: Mapping[str, str] | None = None) -> str:
    """Read a key only when needed; never print, persist, or include it in bundles."""
    env = os.environ if environ is None else environ
    key = (env.get("KIMI_API_KEY") or env.get("OPENAI_API_KEY") or "").strip()
    if not key:
        raise RuntimeError("缺少运行时 KIMI_API_KEY（或 OPENAI_API_KEY）")
    return key


@dataclass
class AuditBundle:
    schema_version: int
    bundle_id: str
    book: str
    source_pdf: str
    page: int
    image_path: str | None = None
    source_result: dict[str, Any] | None = None
    answer_result: dict[str, Any] | None = None
    status: str = "pending"
    metadata: dict[str, Any] = field(default_factory=dict)


def create_audit_bundle(
    book: str, source_pdf: str, page: int, image_path: str | None = None, **metadata: Any
) -> AuditBundle:
    """Create stable metadata keyed by exactly ``(book, source_pdf, page)``."""
    if not book.strip() or not source_pdf.strip() or page < 1:
        raise ValueError("book/source_pdf 必填，page 必须为正整数")
    key = json.dumps([book, source_pdf, page], ensure_ascii=False, separators=(",", ":"))
    bundle_id = hashlib.sha256(key.encode("utf-8")).hexdigest()[:20]
    return AuditBundle(1, bundle_id, book, source_pdf, page, image_path, metadata=dict(metadata))


def create_bundle_for_question(
    question: Mapping[str, Any], image_path: str | None = None
) -> AuditBundle:
    """Create a bundle using the shared, read-only book/PDF mapping rules."""
    if resolve_question_pdf is None:
        raise RuntimeError("source_mapping 不可用")
    ref = resolve_question_pdf(dict(question))
    if ref is None:
        raise ValueError("题目缺少有效 source page")
    book = str(question.get("_book") or question.get("book") or "")
    if not book:
        raise ValueError("题目缺少 book/_book")
    answer_ref = resolve_answer_pdf(dict(question)) if resolve_answer_pdf else None
    return create_audit_bundle(
        book,
        str(ref.path),
        ref.page,
        image_path,
        uid=question.get("uid"),
        answer_pdf=str(answer_ref.path) if answer_ref else None,
    )


def build_image_request(
    image_path: str | Path, prompt: str, config: KimiConfig | None = None
) -> dict[str, Any]:
    """Build an OpenAI-compatible Base64 image request; does not send it."""
    path = Path(image_path)
    raw = path.read_bytes()
    mime = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}.get(path.suffix.lower(), "application/octet-stream")
    cfg = config or KimiConfig.from_env()
    return {
        "endpoint": f"{cfg.endpoint}/chat/completions",
        "model": cfg.model,
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}"}},
        ]}],
        "response_format": {"type": "json_object"},
    }


def parse_strict_json(raw: str, expected: type = dict) -> Any:
    """Parse a model response as JSON, rejecting markdown and trailing content."""
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("模型响应为空")
    text = raw.lstrip("\ufeff \t\r\n")
    if text.startswith("```") or "```" in text:
        raise ValueError("禁止 Markdown 代码围栏")
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"模型响应不是严格 JSON: {exc.msg}") from exc
    if not isinstance(value, expected):
        raise ValueError(f"模型响应必须是 {expected.__name__}")
    return value


def _verdict(result: Mapping[str, Any] | None) -> str:
    if not result:
        return "missing"
    value = str(result.get("verdict", result.get("status", ""))).strip().lower()
    if value in _VERIFIED:
        return "verified"
    if value in _REJECTED:
        return "rejected"
    if value in _UNCERTAIN:
        return "uncertain"
    return "invalid"


def merge_model_results(
    source_result: Mapping[str, Any] | None, answer_result: Mapping[str, Any] | None
) -> str:
    """Merge independent source/answer verdicts into the four-state gate."""
    source, answer = _verdict(source_result), _verdict(answer_result)
    if "invalid" in (source, answer):
        return "hold"
    if "missing" in (source, answer):
        return "pending"
    if "uncertain" in (source, answer):
        return "hold"
    return "strictly_verified" if source == answer == "verified" else "conflict"


def atomic_write_json(path: str | Path, value: Any) -> None:
    """Write JSON via same-directory temporary file and atomic replacement."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, target)
    except Exception:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


class StrictAuditEngine:
    """Checkpointed result store.  It never invokes an HTTP client."""

    def __init__(self, checkpoint: str | Path):
        self.checkpoint = Path(checkpoint)
        if self.checkpoint.is_file():
            data = json.loads(self.checkpoint.read_text(encoding="utf-8"))
            self.records: dict[str, dict[str, Any]] = data.get("records", {})
        else:
            self.records = {}

    def is_complete(self, bundle_id: str) -> bool:
        return self.records.get(bundle_id, {}).get("status") in FINAL_STATUSES - {"pending"}

    def save(self, bundle: AuditBundle, source_result: Mapping[str, Any] | None, answer_result: Mapping[str, Any] | None) -> dict[str, Any]:
        previous = self.records.get(bundle.bundle_id, {})
        # A resumed run may receive only the model that was not completed yet.
        if source_result is None:
            source_result = previous.get("source_result")
        if answer_result is None:
            answer_result = previous.get("answer_result")
        status = merge_model_results(source_result, answer_result)
        record = asdict(bundle)
        record.update({"source_result": source_result, "answer_result": answer_result, "status": status})
        self.records[bundle.bundle_id] = record
        atomic_write_json(self.checkpoint, {"schema_version": 1, "records": self.records})
        return record


def main() -> int:
    parser = argparse.ArgumentParser(description="离线严格审核 bundle/checkpoint 工具")
    parser.add_argument("--book", required=True)
    parser.add_argument("--source-pdf", required=True)
    parser.add_argument("--page", required=True, type=int)
    parser.add_argument("--checkpoint", required=True, type=Path)
    parser.add_argument("--source-result", type=Path)
    parser.add_argument("--answer-result", type=Path)
    args = parser.parse_args()
    bundle = create_audit_bundle(args.book, args.source_pdf, args.page)
    load = lambda p: parse_strict_json(p.read_text(encoding="utf-8")) if p else None
    record = StrictAuditEngine(args.checkpoint).save(bundle, load(args.source_result), load(args.answer_result))
    print(json.dumps({"bundle_id": record["bundle_id"], "status": record["status"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
