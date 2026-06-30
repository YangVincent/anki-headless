#!/usr/bin/env python3
"""Clean the extracted textbook corpus into readable per-book plain text, suitable for
feeding to an LLM to mine grammar patterns, lesson structure, and model essays.

NON-DESTRUCTIVE: reads the raw freq_data/ocr/<slug>.jsonl, writes cleaned text to
freq_data/clean/<slug>.txt. Re-run anytime (e.g. after more OCR completes).

What it removes (only high-confidence piracy/scan watermarks, verified by frequency
across the corpus) — everything else, including legitimate English and company names
in the business texts, is preserved:
  hanyuxuexi · aibochinese(.com) · vk.com · QTEDU · Tiéng/Tieng Trung · "Scanned by …"
  · annas-blog.org · the "For more" aibochinese tagline
"""
import os, re, json, hashlib, glob, argparse

ROOT = "/home/vincent/anki-headless"
OCR_DIR = f"{ROOT}/freq_data/ocr"
CLEAN_DIR = f"{ROOT}/freq_data/clean"

# tokens (whitespace-delimited chunks) containing any of these substrings are dropped
# wholesale — this also catches OCR-fused junk like "Comprehensivevawsalaibochinese.Com".
_WM_TOKEN = re.compile(r"\S*(?:aibochinese|hanyuxuexi|qtedu|annas-blog)\S*", re.I)
# phrase / line level watermarks
_SCANNED_BY = re.compile(r"scanned\s+by[^\n]*", re.I)
_TIENG = re.compile(r"ti[ée]ng\s*trung[^\n]*", re.I)
_VK = re.compile(r"\bvk\.com\b", re.I)
_FOR_MORE = re.compile(r",?\s*for\s+more\b\.?", re.I)
_MULTISPACE = re.compile(r"[ \t]{2,}")
# a line that, after cleaning, is just punctuation / a stray latin letter / nothing useful
_JUNK_LINE = re.compile(r"^[\s\W]*$")


def clean_text(text: str) -> str:
    """Strip watermarks from a page's OCR text, preserving all real content."""
    text = _SCANNED_BY.sub(" ", text)
    text = _TIENG.sub(" ", text)
    text = _WM_TOKEN.sub(" ", text)
    text = _VK.sub(" ", text)
    text = _FOR_MORE.sub(" ", text)
    out_lines = []
    for line in text.split("\n"):
        line = _MULTISPACE.sub(" ", line).strip()
        if not line or _JUNK_LINE.match(line):
            continue
        out_lines.append(line)
    return "\n".join(out_lines)


def _slug(rel):
    base = re.sub(r"[^\w]+", "_", os.path.splitext(rel)[0])[:60].strip("_")
    return f"{base}_{hashlib.sha1(rel.encode()).hexdigest()[:6]}"


def build(verbose=True):
    os.makedirs(CLEAN_DIR, exist_ok=True)
    cls = {r["rel"]: r for r in json.load(open(f"{OCR_DIR}/_corpus_classification.json"))}
    by_slug = {_slug(rel): rel for rel in cls}
    nbooks = npages = 0
    for f in sorted(glob.glob(f"{OCR_DIR}/*.jsonl")):
        sg = os.path.splitext(os.path.basename(f))[0]
        rel = by_slug.get(sg, sg)
        pages = []
        for ln in open(f, encoding="utf-8", errors="ignore"):
            try:
                o = json.loads(ln)
            except Exception:
                continue
            pages.append((o.get("page", 0), o.get("text", "")))
        if not pages:
            continue
        pages.sort()
        chunks = []
        for pno, t in pages:
            c = clean_text(t)
            if c.strip():
                chunks.append(c)
        body = "\n\n".join(chunks)
        if not body.strip():
            continue
        out = f"{CLEAN_DIR}/{sg}.txt"
        with open(out, "w", encoding="utf-8") as fh:
            fh.write(f"# {rel}\n\n{body}\n")
        nbooks += 1
        npages += len(chunks)
    if verbose:
        print(f"cleaned {nbooks} books / {npages:,} pages -> {CLEAN_DIR}/")
    return nbooks, npages


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true", help="show before/after on a sample page")
    args = ap.parse_args()
    if args.demo:
        sample = ('高级综合ⅡIAdvanced Comprehensivevawsalaibochinese.Com，For more\n'
                  '国际广告与国内广告最主要、最明显的区别就在语言文字方面。\n'
                  'Scanned by Tiéng Trung QTEDU\nwww.aibochinese.com, For more\n'
                  '广告语言的转换，决不只是不同语言间的文字翻译问题。 hanyuxuexi')
        print("--- BEFORE ---\n" + sample)
        print("\n--- AFTER ---\n" + clean_text(sample))
    else:
        build()
