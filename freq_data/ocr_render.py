#!/usr/bin/env python3
"""Render scanned-PDF pages to PNGs for vision-OCR (the scanned textbooks have no
text layer; Boya = broken font encoding, Developing Chinese = images).
Usage: ocr_render.py "<pdf path>" <start> <end> [dpi_scale=3] [outdir=/tmp/ocr]
Then OCR the PNGs with a vision model (Claude Read), targeting the 生词/补充词语
vocab tables (word + POS + pinyin + English) which drop straight into the deck.
3x scale is the sweet spot — legible Chinese without huge files."""
import fitz, sys, os
pdf, start, end = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
scale = float(sys.argv[4]) if len(sys.argv) > 4 else 3.0
outdir = sys.argv[5] if len(sys.argv) > 5 else "/tmp/ocr"
os.makedirs(outdir, exist_ok=True)
d = fitz.open(pdf)
base = os.path.splitext(os.path.basename(pdf))[0][:20].replace(" ", "_")
for pno in range(start, min(end, d.page_count)):
    pix = d[pno].get_pixmap(matrix=fitz.Matrix(scale, scale))
    fp = os.path.join(outdir, f"{base}_p{pno:03d}.png")
    pix.save(fp)
    print(fp)
