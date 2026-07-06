"""Convert 660 PDF pages to PNG images."""
import sys
from pathlib import Path
import fitz

sys.stdout.reconfigure(encoding='utf-8')

PDF_PATH = Path('《基础过关660》-高数篇 .pdf')
OUTPUT_DIR = Path('660题/pdf_images')
DPI = 200


def render_page(page_num, dpi=DPI):
    """Render a single page (0-indexed) to PNG."""
    doc = fitz.open(str(PDF_PATH))
    page = doc[page_num]
    pix = page.get_pixmap(dpi=dpi)
    out_path = OUTPUT_DIR / f'page_{page_num + 1:03d}.png'
    pix.save(str(out_path))
    doc.close()
    return out_path


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    doc = fitz.open(str(PDF_PATH))
    total = doc.page_count
    print(f'PDF has {total} pages, rendering to {OUTPUT_DIR} at {DPI} DPI')
    for i in range(total):
        out = OUTPUT_DIR / f'page_{i + 1:03d}.png'
        if out.exists():
            continue
        page = doc[i]
        pix = page.get_pixmap(dpi=DPI)
        pix.save(str(out))
        if (i + 1) % 10 == 0:
            print(f'  rendered {i + 1}/{total}')
    doc.close()
    print('Done')


if __name__ == '__main__':
    main()
