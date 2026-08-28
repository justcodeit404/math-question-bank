#!/usr/bin/env python3
"""根据 figure_crop_manifest.json 重新裁剪题图或验证现有裁图。

用法：
    python scripts/rebuild_figure_crops.py           # 验证所有现有裁图
    python scripts/rebuild_figure_crops.py --rebuild  # 有坐标的重新裁剪，无坐标的跳过
    python scripts/rebuild_figure_crops.py --bank 1000题  # 只处理指定题库
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = ROOT.parent.parent
PDF_DIR = REPO_ROOT / "资料" / "数学2" / "电子资料"
MANIFEST = ROOT / "scripts" / "figure_crop_manifest.json"


def load_manifest():
    if not MANIFEST.exists():
        print(f"[错误] 清单不存在: {MANIFEST}", file=sys.stderr)
        sys.exit(1)
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def verify_crop(entry):
    """验证裁图文件存在且非空。"""
    bank_dir = ROOT / entry["bank"]
    crop_path = bank_dir / "math-bank" / entry["output"]
    if not crop_path.exists():
        return False, f"文件不存在: {crop_path}"
    size = crop_path.stat().st_size
    if size < 1000:
        return False, f"文件过小 ({size} bytes): {crop_path}"
    return True, f"OK ({size} bytes)"


def rebuild_crop(entry):
    """根据坐标重新裁剪。需要 PyMuPDF 和 Pillow。"""
    coords = entry.get("coordinates")
    if not coords:
        return False, "无坐标，跳过（status=existing_verified）"

    try:
        import pymupdf as fitz
        from PIL import Image
    except ImportError:
        return False, "缺少 PyMuPDF 或 Pillow"

    pdf_path = PDF_DIR / entry["source_pdf"]
    if not pdf_path.exists():
        return False, f"源PDF不存在: {pdf_path}"

    dpi = entry.get("dpi", 200)
    zoom = dpi / 72
    doc = fitz.open(pdf_path)
    page = doc[entry["source_page"] - 1]
    mat = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=mat, alpha=False)
    page_img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    doc.close()

    x, y = coords["x"], coords["y"]
    w, h = coords["width"], coords["height"]
    crop = page_img.crop((x, y, x + w, y + h))

    bank_dir = ROOT / entry["bank"]
    out_path = bank_dir / "math-bank" / entry["output"]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    crop.save(out_path, optimize=True)
    return True, f"已裁剪到 {out_path} ({crop.size})"


def main():
    parser = argparse.ArgumentParser(description="重建/验证数学题库题图裁剪")
    parser.add_argument("--rebuild", action="store_true", help="有坐标的重新裁剪")
    parser.add_argument("--bank", default=None, help="只处理指定题库")
    args = parser.parse_args()

    manifest = load_manifest()
    crops = manifest.get("crops", [])
    if args.bank:
        crops = [c for c in crops if c["bank"] == args.bank]

    print(f"共 {len(crops)} 条裁图记录")
    ok_count = 0
    fail_count = 0
    skip_count = 0

    for entry in crops:
        uid = entry["uid"]
        bank = entry["bank"]
        if args.rebuild and entry.get("coordinates"):
            success, msg = rebuild_crop(entry)
            action = "重建"
        else:
            success, msg = verify_crop(entry)
            action = "验证"

        status = "OK" if success else "FAIL"
        if "跳过" in msg:
            status = "SKIP"
            skip_count += 1
        elif success:
            ok_count += 1
        else:
            fail_count += 1
        print(f"  [{status}] {action} {bank} | {uid}: {msg}")

    print(f"\n结果: OK={ok_count} FAIL={fail_count} SKIP={skip_count}")
    return 1 if fail_count > 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
