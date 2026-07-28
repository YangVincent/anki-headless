#!/usr/bin/env python3
"""Render a photographed book page with its marked words highlighted in place.

Takes the photo Vincent already sent, OCRs it for line positions, locates each word he
underlined, and writes a local HTML page: the photo with a clickable overlay on every
marked word (pinyin, definition, times-it-recurs, study verdict) plus a side list in
page order. It is the page-level view of the same data page_marks.py tabulates.

The marked words come from reading_marks.json, so this never re-asks what was marked —
run page_marks.py first, then this.

LOCAL ONLY, deliberately: these are photographs of a copyrighted novel. They go to
generated/pageview/ on disk, not into webroot, which is currently served without auth.
Move them under the report site only once that path is password-protected.

Positioning: PaddleOCR returns a quadrilateral per text LINE, not per character. For a
word at character offset i of an n-character line, we interpolate along the top and
bottom edges between i/n and (i+len)/n. That tracks page rotation and mild perspective,
because it follows the line's own corners rather than assuming level text.

  page_view.py --page 006 --photo /path/to/photo.jpeg
  page_view.py --index                       # rebuild the contents page
"""
import argparse
import base64
import html
import json
import os
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, "/home/vincent/chinese-projects/ebooks")
sys.path.insert(0, "/home/vincent/chinese-projects/dong-chinese/server")

OUT = Path("/home/vincent/anki-headless/generated/pageview")
STORE = Path("/home/vincent/anki-headless/reading_marks.json")
BOOK_TXT = "/home/vincent/chinese-projects/ebooks/shiri_zhongyan_vol1.txt"
HAN = re.compile(r"[一-鿿]")
MAXPX = 1400          # OCR OOMs on a full 3024x4032 phone photo; this is ample for text
PY_FIX = {"散发": "sàn fā", "打量": "dǎ liang", "晕染": "yùn rǎn", "膻腥": "shān xīng"}
GLOSS_FIX = {"钨丝": "tungsten filament", "膻腥": "rank, gamey smell (of sheep/goat)",
             "嘀嗒": "tick-tock", "冚家铲": "(Cantonese) strong profanity",
             "粉肠": "(Cantonese) idiot, fool", "戴": "to wear (mask, hat, glasses)",
             "仰": "to lean back, face upward", "容": "to allow, permit",
             "一怔": "to be startled", "聚": "to gather, assemble",
             "补天": "to patch the sky (Nüwa myth)", "收走": "to take away",
             "晚睡": "to stay up late", "闷响": "a muffled thud",
             "撞碎": "to smash to pieces", "赢下": "to win (a match)"}


def band(n):
    return ("substantial", "#0C5A61") if n >= 10 else \
           ("middling", "#B96C12") if n >= 3 else ("disregard", "#847E70")


def ocr_lines(img_path):
    from paddleocr import PaddleOCR
    ocr = PaddleOCR(lang="ch", enable_mkldnn=False)   # oneDNN path crashes in this build
    out = []
    for page in ocr.predict(str(img_path)):
        texts = page.get("rec_texts", [])
        polys = page.get("rec_polys", page.get("dt_polys", []))
        scores = page.get("rec_scores", [1.0] * len(texts))
        for t, p, s in zip(texts, polys, scores):
            pts = [(float(q[0]), float(q[1])) for q in p]
            if len(pts) == 4 and HAN.search(t):
                out.append({"text": t, "quad": pts, "score": float(s)})
    return out


def word_quad(line, start, length):
    """Quad to highlight for a word found in this OCR line — the WHOLE line.

    An earlier version interpolated a sub-quad for characters [start, start+length)
    assuming uniform character width. Verified against the photo, that lands wrong:
    OCR's recognized string doesn't align character-for-character with the printed line
    (dropped/added glyphs, and full-width punctuation and quote marks are not one hanzi
    wide), so the x-offset drifts and boxes end up on the wrong words or in the margin.

    Line boxes, by contrast, track the printed lines accurately even with the photo's
    perspective. So we highlight the line and let the side panel name the word — honest
    about the precision we actually have.
    """
    return list(line["quad"])


CEDICT_PATH = "/home/vincent/chinese-projects/dong-chinese/Resources/cedict_ts.u8"
HSK_TSV = "/home/vincent/chinese-projects/dong-chinese/server/app/data/hsk30.tsv"


def load_dicts():
    """Local CC-CEDICT + HSK loaders.

    Deliberately NOT report_data.load_maps(): that pulls app.services.vocab, which needs
    sqlalchemy from the dong venv, while PaddleOCR lives in the anki venv. This tool only
    needs glosses, pinyin and HSK levels, so it stays self-contained and runs anywhere.
    """
    ced = {}
    for line in open(CEDICT_PATH, encoding="utf-8"):
        if line.startswith("#"):
            continue
        m = re.match(r"(\S+)\s+(\S+)\s+\[[^\]]*\]\s+/(.+)/", line)
        if m and m.group(2) not in ced:
            ced[m.group(2)] = m.group(3).split("/")[0].strip()[:60]
    hskw = {}
    for line in open(HSK_TSV, encoding="utf-8"):
        w, _, lv = line.rstrip("\n").partition("\t")
        if lv.isdigit():
            hskw[w] = int(lv)
    return hskw, ced


def subgloss(w, ced):
    out, i = [], 0
    while i < len(w):
        for j in range(min(len(w), i + 4), i, -1):
            if w[i:j] in ced:
                out.append(ced[w[i:j]]); i = j; break
        else:
            out.append(ced.get(w[i], "?")); i += 1
    return " + ".join(out)[:60]


def build(page, photo, book):
    from PIL import Image
    from pypinyin import pinyin as _py, Style

    OUT.mkdir(parents=True, exist_ok=True)
    store = json.loads(STORE.read_text(encoding="utf-8"))
    src = next((s for s in store["sources"] if s["page"] == page), None)
    if not src:
        sys.exit(f"page {page} not in reading_marks.json — run page_marks.py for it first")
    marked = src["marked"]

    im = Image.open(photo)
    if im.width > im.height:                 # photos come in sideways
        im = im.rotate(-90, expand=True)
    im.thumbnail((MAXPX, MAXPX), Image.LANCZOS)
    img_file = OUT / f"page-{page}.png"
    im.save(img_file)

    lines = ocr_lines(img_file)
    raw = len(lines)
    # Keep only printed body lines. The photos have handwritten pinyin in the margins,
    # which OCR happily returns as short, low-confidence, mostly-latin "lines" — matching
    # a marked word against those puts a highlight box out in the margin on nothing.
    def is_body(ln):
        xs = [p[0] for p in ln["quad"]]
        width = max(xs) - min(xs)
        cjk = len(HAN.findall(ln["text"])) / max(len(ln["text"]), 1)
        return ln["score"] >= 0.90 and cjk >= 0.6 and width >= 0.25 * im.width
    lines = [l for l in lines if is_body(l)]
    # reading order, so "first occurrence" means the first one on the page
    lines.sort(key=lambda l: (min(p[1] for p in l["quad"]), min(p[0] for p in l["quad"])))
    print(f"OCR: {raw} lines detected, {len(lines)} kept as body text")

    import jieba
    counts = Counter(w for w in jieba.cut(Path(BOOK_TXT).read_text(encoding="utf-8"))
                     if HAN.search(w))
    hskw, ced = load_dicts()
    py = lambda w: PY_FIX.get(w) or " ".join(s[0] for s in _py(w, style=Style.TONE))
    gl = lambda w: GLOSS_FIX.get(w) or ced.get(w) or subgloss(w, ced)

    # First occurrence in reading order only. Highlighting every match scattered boxes
    # across the page for common single characters (顿, 皱, 聚 each match many lines);
    # one box per marked word is what the side list expects anyway.
    hits, missing = [], []
    for w in marked:
        spot = next(((ln, m.start()) for ln in lines
                     for m in [re.search(re.escape(w), ln["text"])] if m), None)
        if spot:
            ln, at = spot
            hits.append({"w": w, "quad": word_quad(ln, at, len(w))})
        else:
            missing.append(w)

    n = lambda w: counts.get(w, 0)
    meta = {w: {"py": py(w), "gl": gl(w), "n": n(w), "band": band(n(w))[0],
                "col": band(n(w))[1], "hsk": hskw.get(w)} for w in marked}

    poly = lambda q: " ".join(f"{x:.1f},{y:.1f}" for x, y in q)
    shapes = "\n".join(
        f'<polygon points="{poly(h["quad"])}" class="mk" data-w="{html.escape(h["w"])}" '
        f'style="--c:{meta[h["w"]]["col"]}"><title>{html.escape(h["w"])} · '
        f'{html.escape(meta[h["w"]]["py"])} · ×{meta[h["w"]]["n"]}</title></polygon>'
        for h in hits)

    rows = "\n".join(
        f'<li data-w="{html.escape(w)}" class="{meta[w]["band"]}">'
        f'<span class="i">{i}</span><b class="zh">{html.escape(w)}</b>'
        f'<span class="py">{html.escape(meta[w]["py"])}</span>'
        f'<span class="gl">{html.escape(meta[w]["gl"])}</span>'
        f'<span class="n" style="color:{meta[w]["col"]}">×{meta[w]["n"]} {meta[w]["band"]}</span></li>'
        for i, w in enumerate(marked, 1))

    tally = Counter(meta[w]["band"] for w in marked)
    warn = (f'<p class="warn">{len(missing)} marked words could not be located by OCR '
            f'(listed but not highlighted): {" ".join(html.escape(x) for x in missing)}</p>'
            if missing else "")

    doc = TEMPLATE.replace("__PAGE__", html.escape(page)) \
        .replace("__BOOK__", html.escape(book)) \
        .replace("__IMG__", img_file.name) \
        .replace("__W__", str(im.width)).replace("__H__", str(im.height)) \
        .replace("__SHAPES__", shapes).replace("__ROWS__", rows).replace("__WARN__", warn) \
        .replace("__SUB__", f'{len(marked)} marked · {tally["substantial"]} substantial · '
                            f'{tally["middling"]} middling · {tally["disregard"]} disregard')
    (OUT / f"page-{page}.html").write_text(doc, encoding="utf-8")
    print(f"placed {len(hits)} highlights for {len(marked)-len(missing)}/{len(marked)} words")
    print(f"-> {OUT}/page-{page}.html")


def index():
    pages = sorted(p.stem.split("-")[1] for p in OUT.glob("page-*.html"))
    # Manifest the page templates read at run time to build prev/next.
    (OUT / "pages.json").write_text(json.dumps(pages), encoding="utf-8")
    store = json.loads(STORE.read_text(encoding="utf-8")) if STORE.exists() else {"sources": []}
    by = {s["page"]: s for s in store["sources"]}
    items = "\n".join(
        f'<li><a href="page-{p}.html">Page {p}</a>'
        f'<span>{len(by.get(p,{}).get("marked",[]))} marked</span></li>' for p in pages)
    (OUT / "index.html").write_text(
        INDEX.replace("__ITEMS__", items).replace("__N__", str(len(pages))), encoding="utf-8")
    print(f"-> {OUT}/index.html ({len(pages)} pages)")


TEMPLATE = """<meta charset="utf-8"><title>Page __PAGE__ · marked words</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
:root{--paper:#F1EEE7;--card:#F8F6F1;--ink:#211F1A;--ink2:#4A463D;--muted:#847E70;--line:#DED9CD;--brand:#0C5A61;
 --sans:ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,Arial,sans-serif;--mono:ui-monospace,Menlo,Consolas,monospace;
 --cjk:"PingFang SC","Hiragino Sans GB","Noto Sans CJK SC","Microsoft YaHei",sans-serif}
@media (prefers-color-scheme:dark){:root{--paper:#16181A;--card:#1E2124;--ink:#ECE9E2;--ink2:#B8B3A8;--muted:#8A857A;--line:#2C2F33;--brand:#48A7AD}}
*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font-family:var(--sans)}
.wrap{max-width:1500px;margin:0 auto;padding:22px clamp(12px,3vw,28px) 60px}
h1{font-size:22px;margin:0 0 2px;font-family:var(--cjk)}
.sub{color:var(--muted);font-size:13px;font-family:var(--mono);margin-bottom:16px}
.grid{display:grid;grid-template-columns:minmax(0,1.15fr) minmax(320px,.85fr);gap:22px;align-items:start}
@media(max-width:900px){.grid{grid-template-columns:1fr}}
.stage{position:relative;border:1px solid var(--line);border-radius:12px;overflow:hidden;background:var(--card)}
.stage img{display:block;width:100%;height:auto}
svg{position:absolute;inset:0;width:100%;height:100%}
/* Highlights mark the LINE a word occurs on (see word_quad). Showing all of them at
   once would blanket the page, so they're invisible until a word is picked. */
.mk{fill:var(--c);fill-opacity:0;stroke:var(--c);stroke-width:0;cursor:pointer;transition:fill-opacity .12s,stroke-width .12s}
.mk:hover{fill-opacity:.10;stroke-width:1.4}
.mk.on{fill-opacity:.30;stroke-width:2.4}
ol{list-style:none;margin:0;padding:0;max-height:82vh;overflow:auto;border:1px solid var(--line);border-radius:12px;background:var(--card)}
li{display:grid;grid-template-columns:30px auto 1fr auto;gap:8px;align-items:baseline;padding:7px 12px;border-bottom:1px solid var(--line);cursor:pointer;font-size:13px}
li:last-child{border-bottom:none}
li:hover,li.on{background:color-mix(in srgb,var(--brand) 12%,transparent)}
.i{font-family:var(--mono);color:var(--muted);font-size:11px}
.zh{font-family:var(--cjk);font-size:17px;font-weight:650}
.py{font-family:var(--mono);color:var(--brand);font-size:12px}
.gl{color:var(--ink2);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.n{font-family:var(--mono);font-size:11px;white-space:nowrap}
.warn{background:#B96C1218;border:1px solid #B96C1240;border-radius:8px;padding:9px 12px;font-size:12.5px;color:var(--ink2);margin:14px 0 0}
.note{font-size:12.5px;color:var(--muted);margin:0 0 14px;max-width:75ch}
nav{display:flex;align-items:center;gap:14px;margin:0 0 14px}
.pg{font-family:var(--mono);font-size:13px;text-decoration:none;background:var(--card);
    border:1px solid var(--line);border-radius:100px;padding:6px 14px;color:var(--brand)}
.pg:hover{border-color:var(--brand)}
#pos{font-family:var(--mono);font-size:12px;color:var(--muted)}
a{color:var(--brand)}
</style>
<div class="wrap">
  <h1>__BOOK__ · page __PAGE__</h1>
  <div class="sub">__SUB__ &nbsp;·&nbsp; <a href="index.html">all pages</a></div>
  <nav id="nav"><a id="prev" class="pg" hidden>‹ prev</a>
    <span id="pos"></span><a id="next" class="pg" hidden>next ›</a></nav>
  <p class="note">Click a word to highlight <b>the line it appears on</b>. Placement is
  line-accurate, not character-accurate — OCR's text doesn't align glyph-for-glyph with
  the print, so an exact box on the word itself would often sit on the wrong one.</p>
  <div class="grid">
    <div class="stage"><img src="__IMG__" alt="page __PAGE__">
      <svg viewBox="0 0 __W__ __H__" preserveAspectRatio="none">__SHAPES__</svg></div>
    <ol id="list">__ROWS__</ol>
  </div>
  __WARN__
</div>
<script>
const sel=w=>{
  document.querySelectorAll('.mk,li').forEach(e=>e.classList.remove('on'));
  document.querySelectorAll(`[data-w="${CSS.escape(w)}"]`).forEach(e=>e.classList.add('on'));
};
document.querySelectorAll('.mk').forEach(p=>p.onclick=()=>{
  sel(p.dataset.w);
  document.querySelector(`li[data-w="${CSS.escape(p.dataset.w)}"]`)
    ?.scrollIntoView({block:'center',behavior:'smooth'});
});
document.querySelectorAll('li').forEach(li=>li.onclick=()=>sel(li.dataset.w));

// Prev/next is resolved at run time from pages.json rather than baked in, so adding a
// new page only means regenerating that manifest — no rebuilding every sibling page.
(async()=>{
  try{
    const pages=await (await fetch('pages.json',{cache:'no-store'})).json();
    const here="__PAGE__", i=pages.indexOf(here);
    if(i<0) return;
    document.getElementById('pos').textContent=`page ${i+1} of ${pages.length}`;
    const wire=(el,p)=>{ if(!p) return; el.href=`page-${p}.html`; el.hidden=false;
                         el.textContent=el.id==='prev'?`‹ ${p}`:`${p} ›`; };
    wire(document.getElementById('prev'), pages[i-1]);
    wire(document.getElementById('next'), pages[i+1]);
    addEventListener('keydown',e=>{
      if(e.target.matches('input,textarea')) return;
      if(e.key==='ArrowLeft'&&pages[i-1]) location.href=`page-${pages[i-1]}.html`;
      if(e.key==='ArrowRight'&&pages[i+1]) location.href=`page-${pages[i+1]}.html`;
    });
  }catch(e){ /* opened via file:// — fetch is blocked; nav just stays hidden */ }
})();
</script>
"""

INDEX = """<meta charset="utf-8"><title>Marked pages</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>body{margin:0;background:#F1EEE7;color:#211F1A;font-family:ui-sans-serif,system-ui,Arial}
@media(prefers-color-scheme:dark){body{background:#16181A;color:#ECE9E2}}
.wrap{max-width:640px;margin:0 auto;padding:40px 20px}h1{font-size:22px}
ul{list-style:none;padding:0;border:1px solid #DED9CD;border-radius:12px;overflow:hidden}
li{display:flex;justify-content:space-between;padding:11px 14px;border-bottom:1px solid #DED9CD}
li:last-child{border-bottom:none}a{color:#0C5A61;text-decoration:none;font-weight:600}
span{color:#847E70;font-size:13px;font-family:ui-monospace,Menlo,monospace}
.up{display:inline-block;margin-bottom:18px;background:#0C5A61;color:#fff;border-radius:100px;
    padding:10px 22px;text-decoration:none;font-weight:600;font-size:14px}</style>
<div class="wrap"><h1>Marked pages (__N__)</h1>
<a class="up" href="upload.html">+ Upload a page</a>
<ul>__ITEMS__</ul></div>
"""

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--page"); ap.add_argument("--photo")
    ap.add_argument("--book", default="十日终焉·囚笼")
    ap.add_argument("--index", action="store_true")
    a = ap.parse_args()
    if a.index:
        index()
    else:
        build(a.page, a.photo, a.book)
        index()
