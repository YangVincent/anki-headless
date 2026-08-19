#!/usr/bin/env python3
"""Compare the book's OWN 生词 gloss list (publisher's expert curation) against my
algorithmic coverage-analysis unknowns for 水浒传. Shows agreement and where each
method wins. Read-only."""
import fitz, glob, re
import jieba.posseg as pseg
from wordfreq import zipf_frequency
from anki.collection import Collection
ROOT = "/home/vincent/anki-headless"
HANs = '一-鿿'; HAN = re.compile(f'[{HANs}]')

f = [x for x in glob.glob(f"{ROOT}/freq_data/books/*.pdf") if "Three Kingdoms" in x][0]
d = fitz.open(f)
full = "\n".join(d[i].get_text() for i in range(d.page_count))

# --- robust gloss parse: split on gloss-start markers ^<letter>\t<hanzi>(<pinyin>) ---
starts = list(re.finditer(rf'(?m)^[a-z]\t\s*([{HANs}]+?)\s*\(', full))
gloss = {}
for i, m in enumerate(starts):
    word = m.group(1)
    chunk = full[m.end(): starts[i+1].start() if i+1 < len(starts) else m.end()+400]
    sm = re.search(r'e\.g\.,\s*(.*?[。！？])', chunk, re.S)
    sent = re.sub(r'\s+', '', sm.group(1)) if sm else ''
    if word not in gloss:
        gloss[word] = sent
book_words = set(gloss)

# --- my algorithmic unknowns for the same book ---
toks = [(w, fl) for w, fl in pseg.cut(full) if HAN.search(w)]
col = Collection(f"{ROOT}/collection.anki2")
try:
    cv = col.models.by_name("ChineseVocabulary"); SEP = chr(31)
    fi = {fl['name']: i for i, fl in enumerate(cv['flds'])}
    vd = col.decks.id_for_name("Vocab")
    deck = set(); studied = set()
    for flds, t in col.db.all("SELECT n.flds,c.type FROM cards c JOIN notes n ON c.nid=n.id WHERE c.did=? AND c.ord=0 AND n.mid=?", vd, cv['id']):
        w = re.sub(r'<[^>]+>', '', flds.split(SEP)[fi['Simplified']]).strip()
        deck.add(w)
        if t in (1, 2): studied.add(w)
finally:
    col.close()
PROP = ('nr', 'ns', 'nt', 'nz')
algo_unknown = {w for w, fl in toks if not fl.startswith(PROP) and w not in studied and zipf_frequency(w, 'zh') < 3.3}

both = book_words & algo_unknown
book_only = book_words - algo_unknown
algo_only = algo_unknown - book_words
def z(w): return zipf_frequency(w, 'zh')

print(f"book's official 生词 (unique):     {len(book_words)}")
print(f"my algorithmic unknowns (Zipf<3.3, non-name, unstudied): {len(algo_unknown)}")
print(f"  AGREE (both flag as new):        {len(both)}  ({100*len(both)/len(book_words):.0f}% of book's list)")
print(f"  book glossed, my algo called KNOWN: {len(book_only)}  (publisher cautious / common words)")
print(f"  my algo flagged, book did NOT gloss: {len(algo_only)}  (over-flag: rare-but-known, OCR junk, untagged names)")
print()
print("BOOK glossed but I'd skip as known (everyday words, Zipf>=3.3):")
print("  " + "  ".join(f"{w}({z(w):.1f})" for w in sorted(book_only, key=z, reverse=True)[:24]))
print()
print("MY algo flagged but book left ungloss'd (sample, commonest first):")
print("  " + "  ".join(f"{w}" for w in sorted(algo_only, key=z, reverse=True)[:30]))
print()
print("AGREED-new words (both methods) — the high-confidence mine set:")
print("  " + "  ".join(sorted(both, key=z, reverse=True)))
