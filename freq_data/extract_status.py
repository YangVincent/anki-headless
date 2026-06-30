#!/usr/bin/env python3
"""Snapshot of textbook-extraction progress. Run anytime: .venv/bin/python freq_data/extract_status.py"""
import os, json, glob, re, hashlib, time
import fitz

ROOT = "/home/vincent/anki-headless"
TB = f"{ROOT}/freq_data/textbooks/Learning Mandarin Material (DO NOT SELL) @binkybing"
OCR_DIR = f"{ROOT}/freq_data/ocr"

def slug(rel):
    base = re.sub(r"[^\w]+", "_", os.path.splitext(rel)[0])[:60].strip("_")
    return f"{base}_{hashlib.sha1(rel.encode()).hexdigest()[:6]}"

def is_dict(rel):
    p = rel.lower()
    return ("/dictionary/" in p or p.startswith("dictionary/")
            or "dictionary" in p.rsplit("/", 1)[-1] or "词典" in p or "图解" in p)

cls = {r["rel"]: r for r in json.load(open(f"{OCR_DIR}/_corpus_classification.json"))}
books = total_pages = 0
done_pages = empty_pages = poison = 0
complete_books = 0
scan_pages_total = scan_pages_done = 0
text_pages_total = text_pages_done = 0
dict_skipped_pages = 0
for rel, r in cls.items():
    if r["class"] == "ERROR":
        continue
    books += 1
    pc = r["pages"]; total_pages += pc
    is_scan = r["class"] == "scanned"
    if is_scan and is_dict(rel):       # dictionaries are intentionally NOT OCR'd
        dict_skipped_pages += pc
        continue
    if is_scan: scan_pages_total += pc
    else: text_pages_total += pc
    out = f"{OCR_DIR}/{slug(rel)}.jsonl"
    d = 0; e = 0
    if os.path.exists(out):
        for ln in open(out, encoding="utf-8", errors="ignore"):
            try:
                o = json.loads(ln)
            except Exception:
                continue
            d += 1
            if not o.get("text"): e += 1
            if o.get("poison"):
                pass
    done_pages += d; empty_pages += e
    if is_scan: scan_pages_done += d
    else: text_pages_done += d
    if d >= pc and pc > 0:
        complete_books += 1

# count poison + recent OCR rate from progress log
prog = f"{OCR_DIR}/_extract_progress.log"
poison = recent = 0
last_ts = []
if os.path.exists(prog):
    txt = open(prog, encoding="utf-8", errors="ignore").read()
    poison = txt.count("POISON SKIP")

print(f"=== TEXTBOOK EXTRACTION STATUS  {time.strftime('%F %T')} ===")
print(f"books complete: {complete_books}/{books}")
print(f"pages done:     {done_pages:,}/{total_pages:,}  ({100*done_pages/max(total_pages,1):.1f}%)")
print(f"  text-layer:   {text_pages_done:,}/{text_pages_total:,}")
print(f"  scanned/OCR:  {scan_pages_done:,}/{scan_pages_total:,}  ({100*scan_pages_done/max(scan_pages_total,1):.1f}%)  [dicts excluded]")
print(f"dictionaries skipped (not OCR'd): {dict_skipped_pages:,} pages")
print(f"empty-text pages: {empty_pages:,}  | poison-skipped: {poison}")
running = os.popen("ps -C python -o args= 2>/dev/null | grep -c 'extract_corpus.py --of'").read().strip()
print(f"OCR workers running: {running}")
