#!/usr/bin/env python3
"""渲染 880 题答案 PDF 为 200 dpi PNG。

输出目录：880题/answer_pdf_images/page_001.png … page_NNN.png
"""
import sys
from pathlib import Path

import fitz
from tqdm import tqdm

ROOT = Path(__file__).resolve().parent.parent
PDF_PATH = ROOT / '880题' / '【PDF】27版880参考答案.pdf'
OUT_DIR = ROOT / '880题' / 'answer_pdf_images'
DPI = 200


def main():
    if not PDF_PATH.exists():
        print(f'[错误] 找不到 {PDF_PATH}')
        sys.exit(1)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    doc = fitz.open(str(PDF_PATH))
    print(f'答案 PDF 共 {doc.page_count} 页，渲染到 {OUT_DIR}（{DPI} dpi）')

    for i in tqdm(range(doc.page_count), desc='渲染', unit='页'):
        out = OUT_DIR / f'page_{i + 1:03d}.png'
        if out.exists():
            continue
        pix = doc[i].get_pixmap(dpi=DPI)
        pix.save(str(out))

    doc.close()
    print(f'完成，共 {doc.page_count if False else "全部"} 页')


if __name__ == '__main__':
    main()