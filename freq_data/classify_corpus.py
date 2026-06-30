#!/usr/bin/env python3
"""Classify every textbook PDF: does it have an extractable text layer (fast, no OCR)
or is it scanned images (needs OCR)? Samples pages spread through each book."""
import os, glob, json, re, hashlib
import fitz

ROOT = "/home/vincent/anki-headless"
TB = f"{ROOT}/freq_data/textbooks/Learning Mandarin Material (DO NOT SELL) @binkybing"
OCR_DIR = f"{ROOT}/freq_data/ocr"

def slug(relpath):
    base = re.sub(r"[^\w]+", "_", os.path.splitext(relpath)[0])[:60].strip("_")
    h = hashlib.sha1(relpath.encode()).hexdigest()[:6]
    return f"{base}_{h}"

rows = []
text_books = scan_books = err_books = 0
text_pages = scan_pages = 0
for fp in sorted(glob.glob(f"{TB}/**/*.pdf", recursive=True)):
    rel = os.path.relpath(fp, TB)
    if "kosakata" in rel.lower():
        continue
    try:
        d = fitz.open(fp)
        pc = d.page_count
    except Exception as e:
        err_books += 1
        rows.append({"rel": rel, "class": "ERROR", "pages": 0, "err": str(e)[:80]})
        continue
    # sample up to 8 pages spread across the book (skip first 2 = cover/title)
    idxs = sorted(set(int(x) for x in
                      [pc*0.15, pc*0.3, pc*0.45, pc*0.6, pc*0.75, pc*0.9] if 0 <= x < pc))
    if not idxs:
        idxs = list(range(pc))
    chars = []
    maxdim = 0
    for i in idxs:
        try:
            t = d[i].get_text("text")
            chars.append(len(t.strip()))
            r = d[i].rect
            maxdim = max(maxdim, r.width, r.height)
        except Exception:
            chars.append(0)
    avg = sum(chars) / len(chars) if chars else 0
    cls = "text" if avg >= 80 else "scanned"
    if cls == "text":
        text_books += 1; text_pages += pc
    else:
        scan_books += 1; scan_pages += pc
    # is it already done by the OCR queue?
    out = f"{OCR_DIR}/{slug(rel)}.jsonl"
    done = 0
    if os.path.exists(out):
        for ln in open(out):
            try:
                json.loads(ln); done += 1
            except Exception:
                pass
    rows.append({"rel": rel, "class": cls, "pages": pc, "avg_chars": round(avg),
                 "maxdim_pt": round(maxdim), "ocr_done": done})

rows.sort(key=lambda r: (r["class"], -r.get("pages", 0)))
with open(f"{OCR_DIR}/_corpus_classification.json", "w") as f:
    json.dump(rows, f, ensure_ascii=False, indent=2)

print(f"TEXT-LAYER books: {text_books}  ({text_pages:,} pages) -> direct extract, no OCR")
print(f"SCANNED books:    {scan_books}  ({scan_pages:,} pages) -> need OCR")
print(f"ERROR books:      {err_books}")
print(f"TOTAL: {text_books+scan_books+err_books} books, {text_pages+scan_pages:,} pages")
print()
print("Largest SCANNED books (the real OCR workload):")
for r in [x for x in rows if x["class"] == "scanned"][:15]:
    print(f"  {r['pages']:4d}p  done={r['ocr_done']:4d}  maxdim={r['maxdim_pt']:5d}pt  {r['rel'][:70]}")
print()
print("Sample TEXT-LAYER books (instant extract):")
for r in [x for x in rows if x["class"] == "text"][:8]:
    print(f"  {r['pages']:4d}p  avg_chars={r['avg_chars']:5d}  {r['rel'][:70]}")
