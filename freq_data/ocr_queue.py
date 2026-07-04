#!/usr/bin/env python3
"""Priority-ordered OCR of the whole textbook corpus. Loads PaddleOCR ONCE, walks
books in priority order, OCRs each page (3x render), writes per-book JSONL to
freq_data/ocr/<slug>.jsonl. Fully resumable at book + page level. Skips the
Indonesian glossaries. Designed to run for days under a restart wrapper.
mkldnn off (paddle 3.x CPU bug). One page in memory at a time."""
import os
os.environ["FLAGS_use_mkldnn"] = "0"
import sys, json, time, glob, re, hashlib, fitz
from paddleocr import PaddleOCR

ROOT = "/home/vincent/anki-headless"
TB = f"{ROOT}/freq_data/textbooks/Learning Mandarin Material (DO NOT SELL) @binkybing"
OCR_DIR = f"{ROOT}/freq_data/ocr"
os.makedirs(OCR_DIR, exist_ok=True)
PROGRESS = f"{OCR_DIR}/_queue_progress.log"

def log(m):
    line = f"[{int(time.time())}] {m}"
    print(line, flush=True)
    with open(PROGRESS, "a") as f: f.write(line + "\n")

def tier(path):
    p = path.lower()
    fn = os.path.basename(path).lower()          # filename only — level lives here
    is_wb = ("workbook" in p or "练习" in p)
    # level of an HSK standard-course volume, read from the FILENAME (not the "1-6" folder)
    m = (re.search(r"标准教程\s*([1-6])", fn) or re.search(r"standard course\s*([1-6])", fn)
         or re.search(r"\bhsk\s*([1-6])[ab]?\b", fn))
    hsk_lvl = int(m.group(1)) if m else None
    # Tier 1 — your level: upper-int/advanced cores
    if "boya" in p and ("intermediate" in p or "advanced" in p): return 1
    if "developing" in p and ("intermediate" in p or "advanced" in p): return 1
    if ("standard course" in p or "标准教程" in p) and hsk_lvl in (5, 6) and not is_wb: return 1
    # Tier 2 — specialized picks + business
    if any(k in p for k in ("logistics", "物流", "adverb", "副词", "synonym", "同义", "idiom", "成语", "chengyu")): return 2
    if any(k in p for k in ("silk road", "丝路", "bct", "business", "商务", "经贸", "经理", "managers")): return 2
    # Tier 3 — other real textbooks (reading, jiaocheng, integrated, npcr)
    if any(k in p for k in ("jiaocheng", "整合", "integrated chinese", "practical chinese reader", "yuedu", "阅读")): return 3
    # Tier 4 — elementary / heritage textbook series
    if any(k in p for k in ("boya", "developing", "go for chinese", "目标汉语", "zhongwen", "中文", "/hanyu ", "汉语第", "new practical")): return 4
    # Tier 5 — HSK supplementary + grammar + hanzi + vocab
    if any(k in p for k in ("hsk", "grammar", "语法", "hanzi", "vocab", "词")): return 5
    return 6  # picture dictionaries + misc

def slug(relpath):
    base = re.sub(r"[^\w]+", "_", os.path.splitext(relpath)[0])[:60].strip("_")
    h = hashlib.sha1(relpath.encode()).hexdigest()[:6]
    return f"{base}_{h}"

# build priority-ordered work list (skip Indonesian glossaries)
pdfs = []
for fp in glob.glob(f"{TB}/**/*.pdf", recursive=True):
    rel = os.path.relpath(fp, TB)
    if "kosakata" in rel.lower(): continue
    try: pc = fitz.open(fp).page_count
    except Exception: continue
    pdfs.append((tier(rel), pc, rel, fp))
pdfs.sort(key=lambda x: (x[0], x[1]))   # tier asc, then small books first
log(f"QUEUE START: {len(pdfs)} books, {sum(p[1] for p in pdfs):,} pages")

ocr = None
def get_ocr():
    global ocr
    if ocr is None:
        try: ocr = PaddleOCR(lang="ch", enable_mkldnn=False)
        except Exception: ocr = PaddleOCR(lang="ch")
    return ocr

MEM_FLOOR_MB = 1500   # if available RAM drops below this, back off (no swap on this box)
def mem_avail_mb():
    try:
        for ln in open("/proc/meminfo"):
            if ln.startswith("MemAvailable:"):
                return int(ln.split()[1]) // 1024
    except Exception: pass
    return 99999

def page_text(d, pno):
    pix = d[pno].get_pixmap(matrix=fitz.Matrix(2, 2))   # 2x: lower peak RAM/CPU than 3x
    png = f"/tmp/_q_{os.getpid()}.png"; pix.save(png)
    try: res = get_ocr().predict(png)
    except Exception:
        try: res = get_ocr().ocr(png)
        except Exception: res = []
    try: os.remove(png)
    except Exception: pass
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

MAX_PAGES_PER_RUN = 800   # exit after this many new pages so the wrapper restarts
                          # fresh (bounds any PaddleOCR memory growth); fully resumable
run_new = 0
for ti, pc, rel, fp in pdfs:
    out = f"{OCR_DIR}/{slug(rel)}.jsonl"
    done = set()
    if os.path.exists(out):
        for ln in open(out):
            try: done.add(json.loads(ln)["page"])
            except Exception: pass
    if len(done) >= pc:
        continue  # book complete
    d = fitz.open(fp)
    log(f"BOOK t{ti} [{len(done)}/{pc} done] {rel}")
    t0 = time.time(); n = 0
    with open(out, "a") as fh:
        for pno in range(pc):
            if pno in done: continue
            if mem_avail_mb() < MEM_FLOOR_MB:      # box under pressure — yield, wrapper resumes later
                log(f"RAM low ({mem_avail_mb()}MB < {MEM_FLOOR_MB}) — backing off, exiting for restart")
                sys.exit(3)
            try:
                txt = page_text(d, pno)
            except Exception:
                txt = ""
            fh.write(json.dumps({"page": pno, "text": txt}, ensure_ascii=False) + "\n"); fh.flush()
            n += 1; run_new += 1
            if n % 25 == 0:
                log(f"  {rel[:40]} {pno+1}/{pc} ({(time.time()-t0)/n:.1f}s/pg)")
            if run_new >= MAX_PAGES_PER_RUN:
                log(f"RUN BUDGET {MAX_PAGES_PER_RUN} reached — exiting for fresh restart")
                sys.exit(0)
    log(f"BOOK DONE {rel} (+{n} pages)")
log("QUEUE COMPLETE")
