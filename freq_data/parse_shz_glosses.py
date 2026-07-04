#!/usr/bin/env python3
"""Parse the 水浒传 (Rainbow Bridge L5) per-page 生词 glosses: word, pinyin, POS,
English, and example sentence. Dedupe by word. Filter to words genuinely new for
Vincent (not common by Zipf>=3.3, not already studied/in deck). Read-only; writes a
JSON mine-list to /tmp. Reports counts + sample."""
import fitz, glob, re, json, sys
from wordfreq import zipf_frequency
from anki.collection import Collection
ROOT = "/home/vincent/anki-headless"
HAN = '[一-鿿]'

f = [x for x in glob.glob(f"{ROOT}/freq_data/books/*.pdf") if "Three Kingdoms" in x][0]
d = fitz.open(f)
full = "\n".join(d[i].get_text() for i in range(d.page_count))

# gloss entry: <letter>\t 词(pinyin) <pos+english> e.g., <sentence>
# stop at next gloss letter, a page number line, or end
pat = re.compile(
    r'(?m)^([a-z])\t\s*(' + HAN + r'+?)\s*\(([^)]*)\)\s*(.*?)\s*e\.g\.,\s*(.*?)'
    r'(?=\n[a-z]\t|\n[A-Za-z一-鿿]{0,3}\n\d|\Z)', re.S)

raw = []
for m in pat.finditer(full):
    word = m.group(2).strip()
    pinyin = m.group(3).strip()
    pos_eng = re.sub(r'\s+', ' ', m.group(4)).strip()
    sent = re.sub(r'\s+', '', m.group(5)).strip()       # chinese sentence: drop internal whitespace
    sent = re.sub(r'(' + HAN + r')\s+(' + HAN + r')', r'\1\2', sent)
    if word and HAN[0] and re.search(HAN, word):
        raw.append(dict(word=word, pinyin=pinyin, pos_eng=pos_eng, sent=sent))

# dedupe by word (keep first, richest)
seen = {}
for e in raw:
    if e['word'] not in seen and len(e['word']) >= 1:
        seen[e['word']] = e
print(f"glossed entries parsed: {len(raw)}  | unique words: {len(seen)}")

# filter vs Vincent's knowledge
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

mine = []; known = []; already = []
for w, e in seen.items():
    if w in deck:
        already.append(w); continue
    if zipf_frequency(w, 'zh') >= 3.3 or w in studied:
        known.append(w); continue
    mine.append(e)
mine.sort(key=lambda e: -zipf_frequency(e['word'], 'zh'))   # commonest-first
print(f"  already in your deck: {len(already)}")
print(f"  too common / known (skip): {len(known)}")
print(f"  -> GENUINELY NEW to mine: {len(mine)}")
json.dump(mine, open("/tmp/shz_mine.json", "w"), ensure_ascii=False, indent=1)
print("\nsample of mine-list (word | pinyin | english | book sentence):")
for e in mine[:25]:
    print(f"  {e['word']}  {e['pinyin']}  — {e['pos_eng'][:40]}  | {e['sent'][:34]}")
