#!/usr/bin/env python3
"""Coverage analysis of the uploaded graded readers vs Vincent's deck + a frequency
(heritage-known) model. For each book: token coverage (comprehension proxy), new-word
density, and the top unknown words to mine. Read-only on the collection."""
import re, glob, sys, time, os, tempfile
import jieba
from wordfreq import zipf_frequency
from anki.collection import Collection
ROOT = "/home/vincent/anki-headless"
HAN = re.compile(r'[一-鿿]')

def extract_pdf(path):
    import fitz
    d = fitz.open(path)
    return "\n".join(d[i].get_text() for i in range(d.page_count)), d.page_count

def extract_azw3(path):
    import mobi, zipfile
    from bs4 import BeautifulSoup
    td, fp = mobi.extract(path)
    z = zipfile.ZipFile(fp)
    htmls = [n for n in z.namelist() if n.lower().endswith((".xhtml", ".html", ".htm"))]
    txt = [BeautifulSoup(z.read(n).decode("utf-8", "replace"), "html.parser").get_text("\n") for n in htmls]
    return "\n".join(txt), None

import jieba.posseg as pseg
PROP = ('nr', 'ns', 'nt', 'nz')  # person / place / org / other proper noun
def words_of(text):
    """returns list of (word, is_proper) for Chinese words"""
    out = []
    for w, flag in pseg.cut(text):
        if HAN.search(w):
            out.append((w, flag.startswith(PROP)))
    return out

# ---- build known sets from the deck ----
col = Collection(f"{ROOT}/collection.anki2")
try:
    cv = col.models.by_name("ChineseVocabulary"); SEP = chr(31)
    fi = {f['name']: i for i, f in enumerate(cv['flds'])}
    vd = col.decks.id_for_name("Vocab")
    deck_words = set(); studied_words = set()
    for flds, ctype in col.db.all(
        "SELECT n.flds, c.type FROM cards c JOIN notes n ON c.nid=n.id WHERE c.did=? AND c.ord=0 AND n.mid=?", vd, cv['id']):
        w = re.sub(r'<[^>]+>', '', flds.split(SEP)[fi['Simplified']]).strip()
        if w:
            deck_words.add(w)
            if ctype in (1, 2): studied_words.add(w)
finally:
    col.close()
print(f"deck words: {len(deck_words)} | studied: {len(studied_words)}\n")

_zc = {}
def zf(w):
    if w not in _zc: _zc[w] = zipf_frequency(w, 'zh')
    return _zc[w]
# T is calibrated below so Mandarin Companion L2 ~= 98% (Vincent's own report)
def known(w, is_prop, T):
    return is_prop or (w in studied_words) or zf(w) >= T

BOOKS = []
for p in sorted(glob.glob(f"{ROOT}/freq_data/books/*")):
    name = os.path.basename(p)
    if name.endswith(".pdf"): BOOKS.append((name, p, extract_pdf))
    elif name.endswith(".azw3"): BOOKS.append((name, p, extract_azw3))

def short(name):
    if "Center of the Earth" in name: return "Journey-Center (Mandarin Companion L2, 450)"
    if "Three Kingdoms" in name: return "Three Kingdoms (Rainbow Bridge L5, 1500)"
    if "如果没有你" in name: return "如果没有你 (Chinese Breeze)"
    if "作为方法" in name: return "把自己作为方法 (项飙, NATIVE non-fiction)"
    return name[:40]

from collections import Counter
# extract all books once
EX = {}
for name, path, fn in BOOKS:
    try:
        toks = words_of(fn(path)[0])
    except Exception as e:
        print(f"!! {short(name)}: extract failed: {e}"); continue
    if len(toks) < 200:
        print(f"!! {short(name)}: too little text ({len(toks)} tokens)"); continue
    EX[short(name)] = toks

# ---- calibrate T so Mandarin Companion L2 ~= 98% ----
anchor = next((k for k in EX if "Mandarin Companion" in k), None)
def cov_at(toks, T):
    return 100 * sum(1 for w, p in toks if known(w, p, T)) / len(toks)
T = 4.0
if anchor:
    best = None
    for i in range(20, 56):
        t = i / 10
        c = cov_at(EX[anchor], t)
        if best is None or abs(c - 98) < abs(best[1] - 98): best = (t, c)
    T = best[0]
print(f"calibrated heritage-known threshold: Zipf >= {T}  (anchored to {anchor} = {cov_at(EX[anchor],T):.1f}%)\n")

results = []
for nm, toks in EX.items():
    ntok = len(toks)
    types = {w for w, p in toks}
    propers = {w for w, p in toks if p}
    cov = cov_at(toks, T)
    unknown_types = {w for w, p in toks if not known(w, p, T)}
    new_not_in_deck = {w for w in unknown_types if w not in deck_words}
    cnt = Counter(w for w, p in toks if w in unknown_types)
    top = cnt.most_common(20)
    unk_per_1k = 1000 * len(unknown_types) / ntok
    results.append(dict(name=nm, ntok=ntok, ntype=len(types), nproper=len(propers),
                        cov=cov, unk_types=len(unknown_types),
                        new_not_deck=len(new_not_in_deck), unk_per_1k=unk_per_1k, top=top))

results.sort(key=lambda r: -r['cov'])
def zone(c):
    return "fluency/easy" if c >= 97 else "LEARNING (sweet spot)" if c >= 94 else "intensive" if c >= 90 else "very hard"
print("="*78)
print(f"{'BOOK':<40}{'comp%':>7}{'zone':<22}{'new/1k':>7}")
print("-"*78)
for r in results:
    print(f"{r['name']:<40}{r['cov']:>6.1f}% {zone(r['cov']):<22}{r['unk_per_1k']:>6.1f}")
print("="*78)
for r in results:
    print(f"\n### {r['name']}")
    print(f"  tokens={r['ntok']:,}  unique words={r['ntype']:,}  proper-name types={r['nproper']:,}")
    print(f"  comprehension: {r['cov']:.1f}%  ->  {zone(r['cov'])}")
    print(f"  distinct unknown (non-name) words: {r['unk_types']:,}  ({r['new_not_deck']:,} not yet in your deck)")
    print(f"  density: {r['unk_per_1k']:.1f} distinct unknowns / 1000 tokens (~{r['unk_per_1k']*0.35:.0f}/page)")
    print(f"  mine these (most frequent unknowns): " + " ".join(f"{w}({c})" for w, c in r['top']))
