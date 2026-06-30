#!/usr/bin/env python3
"""OCR a single arbitrary PDF using the same robust pipeline as extract_corpus
(text-layer fast path, in-memory render capped at MAX_PX, PaddleOCR mobile mkldnn-off).
  ocr_pdf.py <input.pdf> <output.jsonl> [--sample p1,p2,...]
Writes {"page": n, "text": t} per line. Resumable (skips pages already in output)."""
import os, sys, json, importlib.util
os.environ["FLAGS_use_mkldnn"] = "0"
os.environ["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] = "True"
import fitz

spec = importlib.util.spec_from_file_location("ec", "/home/vincent/anki-headless/freq_data/extract_corpus.py")
ec = importlib.util.module_from_spec(spec); spec.loader.exec_module(ec)

pdf, out = sys.argv[1], sys.argv[2]
sample = None
if "--sample" in sys.argv:
    sample = [int(x) for x in sys.argv[sys.argv.index("--sample") + 1].split(",")]

d = fitz.open(pdf)
done = set()
if not sample and os.path.exists(out):
    for ln in open(out, encoding="utf-8", errors="ignore"):
        try: done.add(json.loads(ln)["page"])
        except Exception: pass

pages = sample if sample else range(d.page_count)
mode = "w" if sample else "a"
with open(out, mode, encoding="utf-8") as fh:
    for pno in pages:
        if pno in done:
            continue
        tl = ec.text_layer(d[pno])
        txt = tl if tl is not None else ec.ocr_page(d[pno])
        fh.write(json.dumps({"page": pno, "text": txt}, ensure_ascii=False) + "\n"); fh.flush()
        if sample:
            print(f"--- page {pno} ({len(txt)} chars) ---\n{txt[:400]}\n")
