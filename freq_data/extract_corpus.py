#!/usr/bin/env python3
"""Unified textbook-corpus extractor (supersedes ocr_queue.py).

Per page: if the PDF has an embedded text layer, use it (instant, perfect); else
OCR with PaddleOCR PP-OCRv5-mobile — mkldnn OFF (paddle 3.x CPU bug), in-memory
ndarray (no temp file -> immune to a full /tmp), render capped to MAX_PX (prevents
the giant-page OOM that wedged the old queue).

Robust + resumable + sharded:
  --of N --shard K   -> only process books where book_index % N == K
  --no-ocr           -> only write text-layer pages, skip pages needing OCR
                        (fast phase-1 pass over the whole corpus)
  --budget P         -> exit(0) after P new OCR pages so the wrapper restarts fresh
                        (bounds any PaddleOCR memory growth)

Poison-page guard: before OCRing a page we record (slug,page) to a per-shard
checkpoint; if a launch starts on the exact page that killed the previous launch,
we write it empty and skip it, so one bad page can never wedge a shard.

Output: freq_data/ocr/<slug>.jsonl, one {"page": n, "text": t} per line (the
existing contract used by ocr_book.py / ocr_queue.py). Fully resumable per page.
"""
import os, sys, json, glob, re, hashlib, time, argparse
os.environ["FLAGS_use_mkldnn"] = "0"
os.environ["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] = "True"
os.environ.setdefault("OMP_NUM_THREADS", "1")
import numpy as np
import fitz

ROOT = "/home/vincent/anki-headless"
TB = f"{ROOT}/freq_data/textbooks/Learning Mandarin Material (DO NOT SELL) @binkybing"
OCR_DIR = f"{ROOT}/freq_data/ocr"
os.makedirs(OCR_DIR, exist_ok=True)
PROGRESS = f"{OCR_DIR}/_extract_progress.log"

SKIP_DICTS = True        # don't OCR dictionaries (low value for a frequency corpus; ~6.4k pages).
                         # Text-layer dicts already extracted in phase 1 are kept as-is.
MAX_PX = 1300            # render long-side cap (sweep: same quality as 2000, ~30% faster)
TEXT_MIN_CHARS = 60      # page text-layer >= this -> trust it, skip OCR
MEM_FLOOR_MB = 1200      # below this available RAM, exit for a clean restart
CPU_THREADS = 1

def log(m, shard="-"):
    line = f"[{int(time.time())}|s{shard}] {m}"
    print(line, flush=True)
    try:
        with open(PROGRESS, "a") as f:
            f.write(line + "\n")
    except Exception:
        pass

# --- priority tiers (copied from ocr_queue.py so ordering is unchanged) ---
def tier(path):
    p = path.lower()
    fn = os.path.basename(path).lower()
    is_wb = ("workbook" in p or "练习" in p)
    m = (re.search(r"标准教程\s*([1-6])", fn) or re.search(r"standard course\s*([1-6])", fn)
         or re.search(r"\bhsk\s*([1-6])[ab]?\b", fn))
    hsk_lvl = int(m.group(1)) if m else None
    if "boya" in p and ("intermediate" in p or "advanced" in p): return 1
    if "developing" in p and ("intermediate" in p or "advanced" in p): return 1
    if ("standard course" in p or "标准教程" in p) and hsk_lvl in (5, 6) and not is_wb: return 1
    if any(k in p for k in ("logistics", "物流", "adverb", "副词", "synonym", "同义", "idiom", "成语", "chengyu")): return 2
    if any(k in p for k in ("silk road", "丝路", "bct", "business", "商务", "经贸", "经理", "managers")): return 2
    if any(k in p for k in ("jiaocheng", "整合", "integrated chinese", "practical chinese reader", "yuedu", "阅读")): return 3
    if any(k in p for k in ("boya", "developing", "go for chinese", "目标汉语", "zhongwen", "中文", "/hanyu ", "汉语第", "new practical")): return 4
    if any(k in p for k in ("hsk", "grammar", "语法", "hanzi", "vocab", "词")): return 5
    return 6

def is_dict(rel):
    p = rel.lower()
    return ("/dictionary/" in p or p.startswith("dictionary/")
            or "dictionary" in p.rsplit("/", 1)[-1] or "词典" in p or "图解" in p)

def slug(relpath):
    base = re.sub(r"[^\w]+", "_", os.path.splitext(relpath)[0])[:60].strip("_")
    h = hashlib.sha1(relpath.encode()).hexdigest()[:6]
    return f"{base}_{h}"

def build_list():
    pdfs = []
    for fp in glob.glob(f"{TB}/**/*.pdf", recursive=True):
        rel = os.path.relpath(fp, TB)
        if "kosakata" in rel.lower():
            continue
        try:
            pc = fitz.open(fp).page_count
        except Exception:
            continue
        pdfs.append((tier(rel), pc, rel, fp))
    pdfs.sort(key=lambda x: (x[0], x[1]))   # tier asc, then small books first
    return pdfs

def mem_avail_mb():
    try:
        for ln in open("/proc/meminfo"):
            if ln.startswith("MemAvailable:"):
                return int(ln.split()[1]) // 1024
    except Exception:
        pass
    return 99999

_ocr = None
def get_ocr():
    global _ocr
    if _ocr is None:
        from paddleocr import PaddleOCR
        _ocr = PaddleOCR(
            lang="ch", enable_mkldnn=False, cpu_threads=CPU_THREADS,
            use_doc_orientation_classify=False, use_doc_unwarping=False,
            use_textline_orientation=False,
            text_detection_model_name="PP-OCRv5_mobile_det",
            text_recognition_model_name="PP-OCRv5_mobile_rec",
        )
    return _ocr

def _collect(res):
    lines = []
    def walk(x):
        if isinstance(x, list):
            for y in x: walk(y)
        elif isinstance(x, dict) and isinstance(x.get("rec_texts"), list):
            lines.extend(x["rec_texts"])
    walk(res)
    if not lines:                       # legacy result shape fallback
        for pg in res or []:
            for ln in pg or []:
                try: lines.append(ln[1][0])
                except Exception: pass
    return "\n".join(lines)

def ocr_page(page):
    r = page.rect
    zoom = max(min(MAX_PX / max(r.width, r.height, 1), 3.0), 0.5)
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
    img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.h, pix.w, pix.n)
    if pix.n == 4:
        img = img[:, :, :3]
    img = np.ascontiguousarray(img[:, :, ::-1])    # RGB -> BGR
    try:
        res = get_ocr().predict(img)
    except Exception:
        res = get_ocr().ocr(img)
    return _collect(res)

def text_layer(page):
    try:
        t = page.get_text("text").strip()
    except Exception:
        return None
    return t if len(t) >= TEXT_MIN_CHARS else None

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--of", type=int, default=1)
    ap.add_argument("--shard", type=int, default=0)
    ap.add_argument("--no-ocr", action="store_true")
    ap.add_argument("--budget", type=int, default=600)
    args = ap.parse_args()
    N, K = args.of, args.shard

    ckpt_path = f"{OCR_DIR}/_ckpt_s{K}of{N}"
    last_ckpt = None
    if not args.no_ocr and os.path.exists(ckpt_path):
        try:
            last_ckpt = tuple(json.load(open(ckpt_path)))
        except Exception:
            last_ckpt = None

    pdfs = build_list()
    mine = [(i, t, pc, rel, fp) for i, (t, pc, rel, fp) in enumerate(pdfs) if i % N == K]
    mode = "TEXT-ONLY" if args.no_ocr else "OCR"
    log(f"START {mode} shard {K}/{N}: {len(mine)}/{len(pdfs)} books", K)

    new_ocr = 0
    for idx, ti, pc, rel, fp in mine:
        if SKIP_DICTS and not args.no_ocr and is_dict(rel):
            continue                                   # skip dictionaries in the OCR phase
        sg = slug(rel)
        out = f"{OCR_DIR}/{sg}.jsonl"
        done = set()
        if os.path.exists(out):
            for ln in open(out, encoding="utf-8", errors="ignore"):
                try: done.add(json.loads(ln)["page"])
                except Exception: pass
        if len(done) >= pc:
            continue
        try:
            d = fitz.open(fp)
        except Exception as e:
            log(f"OPEN FAIL {rel[:50]}: {str(e)[:60]}", K)
            continue
        log(f"BOOK t{ti} [{len(done)}/{pc}] {rel[:58]}", K)
        with open(out, "a", encoding="utf-8") as fh:
            for pno in range(pc):
                if pno in done:
                    continue
                tl = text_layer(d[pno])
                if tl is not None:
                    fh.write(json.dumps({"page": pno, "text": tl}, ensure_ascii=False) + "\n")
                    fh.flush()
                    continue
                if args.no_ocr:
                    continue                       # leave OCR pages for phase 2
                # poison-page guard
                if last_ckpt == [sg, pno] or last_ckpt == (sg, pno):
                    log(f"POISON SKIP {rel[:40]} p{pno} (killed previous launch)", K)
                    fh.write(json.dumps({"page": pno, "text": "", "poison": 1}, ensure_ascii=False) + "\n")
                    fh.flush()
                    last_ckpt = None
                    continue
                if mem_avail_mb() < MEM_FLOOR_MB:
                    log(f"RAM low ({mem_avail_mb()}MB) — exit for restart", K)
                    sys.exit(3)
                try:
                    json.dump([sg, pno], open(ckpt_path, "w"))   # checkpoint before risky op
                except Exception:
                    pass
                try:
                    txt = ocr_page(d[pno])
                except Exception as e:
                    txt = ""
                    log(f"OCR ERR {rel[:35]} p{pno}: {str(e)[:50]}", K)
                fh.write(json.dumps({"page": pno, "text": txt}, ensure_ascii=False) + "\n")
                fh.flush()
                new_ocr += 1
                if new_ocr % 50 == 0:
                    log(f"  +{new_ocr} ocr pages (now {rel[:28]} {pno + 1}/{pc})", K)
                if new_ocr >= args.budget:
                    log(f"BUDGET {args.budget} reached — exit for fresh restart", K)
                    try: os.remove(ckpt_path)
                    except Exception: pass
                    sys.exit(0)
        log(f"BOOK DONE {rel[:50]}", K)
    try:
        if os.path.exists(ckpt_path): os.remove(ckpt_path)
    except Exception:
        pass
    open(f"{OCR_DIR}/_shard{K}of{N}{'_text' if args.no_ocr else ''}.done", "w").close()
    log(f"SHARD COMPLETE {mode} {K}/{N}", K)

if __name__ == "__main__":
    main()
