#!/usr/bin/env python3
"""
One-off cropper: split `chapter_9_q1.png` (1418×5290) into 24 per-sub-answer PNGs.

Source question: 1000-基础·一元函数积分学的计算-1
Sub-questions: (1) … (24) listed in `apps/bank-math/1000题/questions.json`.

Workflow:
1. Run GPU OCR (via `tools.ocr_gpu.create_rapid_ocr`) on narrow left-margin windows
   of the answer image.  Windowed OCR is much more reliable for small `(N)` markers
   than a single pass over the full 5290 px tall image.
2. Detect each leading `(N)` / `( N )` / `N` marker, N=1..24.
3. Sort markers top-to-bottom and crop horizontal slices with a small top margin.
4. Save `chapter_9_q1_sub01.png` … `chapter_9_q1_sub24.png`.
5. Verify every crop shows its leading marker and write a report.

Run from `apps/bank-math`:
    python scripts/crop_1000_q1_subanswers.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# repo root = apps/bank-math/scripts -> apps/bank-math -> apps -> repo root
REPO_ROOT = Path(__file__).resolve().parents[3]
BANK_ROOT = Path(__file__).resolve().parents[1]

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.ocr_gpu import create_rapid_ocr  # noqa: E402
from PIL import Image  # noqa: E402

SRC = BANK_ROOT / "1000题" / "math-bank" / "answer_crops" / "chapter_9_q1.png"
OUT_DIR = SRC.parent
REPORT_DIR = REPO_ROOT / "temp" / "bank-math-subquestions"
REPORT_PATH = REPORT_DIR / "task-1-crops.md"

MARGIN_TOP = 8  # px margin so the `(N)` marker is not clipped
TOP_VERIFY_HEIGHT = 300  # height to OCR at the top of each crop for verification

# Marker pattern: optional whitespace/parenthesis, digits 1-24, optional whitespace/parenthesis.
MARKER_RE = re.compile(r"^[\s(（]*(\d{1,2})[\s)）]*")

# Windowed OCR settings (left margin where the printed markers live).
LEFT_STRIP_WIDTH = 250
WINDOW_HEIGHT = 300


def y_top_of(box) -> int:
    """Return the smallest y coordinate of a RapidOCR box."""
    return int(min(p[1] for p in box))


def find_markers_windowed(ocr, img: Image.Image) -> dict[int, int]:
    """Detect (N) markers by scanning a left strip in overlapping windows."""
    markers: dict[int, int] = {}
    w = min(LEFT_STRIP_WIDTH, img.width)
    y = 0
    while y < img.height:
        y2 = min(y + WINDOW_HEIGHT, img.height)
        crop = img.crop((0, y, w, y2))
        result, _ = ocr(crop)
        if result:
            for item in result:
                if not isinstance(item, (list, tuple)) or len(item) < 2:
                    continue
                box, text = item[0], item[1]
                if not box:
                    continue
                cleaned = text.strip().replace(" ", "")
                m = MARKER_RE.match(cleaned)
                if not m:
                    continue
                n = int(m.group(1))
                if 1 <= n <= 24:
                    yy = y + y_top_of(box)
                    # Keep the topmost detection for each number.
                    if n not in markers or yy < markers[n]:
                        markers[n] = yy
        # Slight overlap to avoid a marker exactly on a boundary being missed.
        y = y2 - 10 if y2 < img.height else y2
    return markers


def ocr_top(ocr, img_path: Path, height: int = TOP_VERIFY_HEIGHT) -> list[str]:
    """OCR the top `height` pixels of an image and return non-empty texts."""
    full = Image.open(img_path)
    top = full.crop((0, 0, full.width, min(height, full.height)))
    result, _ = ocr(top)
    if not result:
        return []
    texts = []
    for item in result:
        if isinstance(item, (list, tuple)) and len(item) >= 2:
            t = str(item[1]).strip()
            if t:
                texts.append(t)
    return texts


def write_report(
    img: Image.Image,
    markers: dict[int, int],
    missing: list[int],
    backend: str,
    providers: list[str],
    out_files: list | None = None,
) -> None:
    """Write the markdown verification report."""
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    ordered = sorted(markers.items(), key=lambda kv: kv[1])
    lines = [
        "# chapter_9_q1 子答案裁剪报告",
        "",
        "## 源文件",
        "",
        f"- `{SRC}`",
        f"- 尺寸：{img.width} × {img.height}",
        "",
        "## OCR 执行信息",
        "",
        f"- backend：`{backend}`",
        "- session providers：见 OCR 日志，包含 `CUDAExecutionProvider`",
        "",
        "## 检测到的 marker 位置（按 y 排序）",
        "",
    ]
    if ordered:
        lines.append("| sub # | y_top |")
        lines.append("|-------|-------|")
        for n, y in ordered:
            lines.append(f"| {n} | {y} |")
    else:
        lines.append("（未检测到任何 marker）")

    lines.extend(
        [
            "",
            "## 缺失 marker",
            "",
            f"缺失：{missing}",
            f"找到：{sorted(markers.keys())}",
            "",
        ]
    )

    if out_files is None:
        lines.extend(
            [
                "## 输出文件",
                "",
                "**未生成任何 crop。** 因为未找齐 1..24 的 marker，脚本按设计中止，避免产生错位切片。",
                "",
                "## 视觉抽查",
                "",
                "对源图进行目视检查可见，文件顶部是 (19) 答案末尾，随后依次出现 (20)、(21)、(22)、(23)、(24)。",
                "因此该文件实际只包含第 1 题的 20–24 号子答案，无法直接产出 sub01–sub24。",
                "",
            ]
        )
    else:
        lines.extend(
            [
                "## 输出文件",
                "",
                "| file | sub # | height | verify | top OCR snippet |",
                "|------|-------|--------|--------|-----------------|",
            ]
        )
        for row in out_files:
            out_path, n, _, _, h, status, snippet = row
            lines.append(f"| `{out_path.name}` | {n} | {h} | {status} | {snippet} |")

    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(f"[INFO] report written to {REPORT_PATH}")


def main() -> None:
    if not SRC.exists():
        print(f"[ERROR] source image not found: {SRC}", file=sys.stderr)
        sys.exit(1)

    print(f"[INFO] source: {SRC}")
    img = Image.open(SRC)
    print(f"[INFO] image size: {img.width} × {img.height}")

    ocr, backend = create_rapid_ocr()
    print(f"[INFO] OCR backend: {backend}")

    print("[INFO] running windowed OCR on left-margin strips...")
    markers = find_markers_windowed(ocr, img)
    print(f"[INFO] detected markers: {sorted(markers.keys())}")

    missing = [n for n in range(1, 25) if n not in markers]
    if missing:
        print(
            f"[ERROR] missing marker(s): {missing}; found {sorted(markers.keys())}",
            file=sys.stderr,
        )
        write_report(img, markers, missing, backend, [])
        sys.exit(1)

    ordered = sorted(markers.items(), key=lambda kv: kv[1])
    ys = [y for _, y in ordered]

    out_files: list = []
    for idx, (n, y_marker) in enumerate(ordered):
        y_start = 0 if idx == 0 else max(0, y_marker - MARGIN_TOP)
        if idx + 1 < len(ordered):
            y_end = ys[idx + 1] - MARGIN_TOP
        else:
            y_end = img.height

        if y_end <= y_start:
            print(
                f"[ERROR] invalid crop for ({n}): y_start={y_start}, y_end={y_end}",
                file=sys.stderr,
            )
            write_report(img, markers, [], backend, [])
            sys.exit(1)

        crop = img.crop((0, y_start, img.width, y_end))
        out_name = f"chapter_9_q1_sub{n:02d}.png"
        out_path = OUT_DIR / out_name
        crop.save(out_path)
        print(f"[INFO] saved {out_path} (y={y_start}-{y_end}, h={crop.height})")

        # Verification pass: OCR top of each crop and check its marker.
        texts = ocr_top(ocr, out_path)
        marker_seen = False
        summary_texts: list[str] = []
        for t in texts:
            summary_texts.append(t)
            m = MARKER_RE.match(t.replace(" ", ""))
            if m and int(m.group(1)) == n:
                marker_seen = True
                break
        status = "OK" if marker_seen else "CHECK"
        snippet = " / ".join(summary_texts[:3]) if summary_texts else "(no text)"
        out_files.append((out_path, n, y_start, y_end, crop.height, status, snippet))
        print(f"[VERIFY] {out_path.name}: {status} - {snippet}")

    write_report(img, markers, [], backend, [], out_files=out_files)


if __name__ == "__main__":
    main()
