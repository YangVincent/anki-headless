#!/usr/bin/env python3
"""Batch-OCR a scanned textbook PDF with PaddleOCR (CPU, mkldnn off to dodge the
paddle 3.x oneDNN bug). Renders each page at 3x, OCRs, writes one JSONL line per
page {page, text} to freq_data/ocr/<book>.jsonl. Resumable (skips done pages).
Usage: ocr_book.py "<pdf>" [start] [end]"""
import os
os.environ["FLAGS_use_mkldnn"] = "0"
import sys, json, time, fitz
from paddleocr import PaddleOCR

pdf = sys.argv[1]
start = int(sys.argv[2]) if len(sys.argv) > 2 else 0
d = fitz.open(pdf)
end = int(sys.argv[3]) if len(sys.argv) > 3 else d.page_count
base = os.path.splitext(os.path.basename(pdf))[0].replace(" ", "_")[:30]
os.makedirs("/home/vincent/anki-headless/freq_data/ocr", exist_ok=True)
out = f"/home/vincent/anki-headless/freq_data/ocr/{base}.jsonl"
done = set()
if os.path.exists(out):
    for ln in open(out):
        try: done.add(json.loads(ln)["page"])
        except Exception: pass

try:
    ocr = PaddleOCR(lang="ch", enable_mkldnn=False)
except Exception:
    ocr = PaddleOCR(lang="ch")
def page_text(pno):
    pix = d[pno].get_pixmap(matrix=fitz.Matrix(3, 3))
    png = f"/tmp/_ocr_{base}_{pno}.png"; pix.save(png)
    try:
        res = ocr.predict(png)
    except Exception:
        res = ocr.ocr(png)
    os.remove(png)
    lines = []
    def walk(r):
        if isinstance(r, list):
            for x in r: walk(x)
        elif isinstance(r, dict) and isinstance(r.get("rec_texts"), list):
            lines.extend(r["rec_texts"])
    walk(res)
    if not lines:
        for pg in res or []:
            for l in pg or []:
                try: lines.append(l[1][0])
                except Exception: pass
    return "\n".join(lines)

t0 = time.time(); n = 0
with open(out, "a") as fh:
    for pno in range(start, end):
        if pno in done: continue
        txt = page_text(pno)
        fh.write(json.dumps({"page": pno, "text": txt}, ensure_ascii=False) + "\n"); fh.flush()
        n += 1
        if n % 5 == 0:
            print(f"  {pno+1}/{end} done, {n} pages, {(time.time()-t0)/n:.1f}s/page", flush=True)
print(f"FINISHED: OCR'd {n} pages -> {out} ({(time.time()-t0)/max(n,1):.1f}s/page avg)", flush=True)
