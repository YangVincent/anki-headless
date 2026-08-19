#!/usr/bin/env python3
"""Create Vocab cards for the multi-character HSK 4-9 words missing from the deck.
Forward (ord0) active in Vocab; reverse (ord1) suspended; cloze (ord2) -> Vocab Cloze
suspended. Tagged HSK3.0::<level> + 'hsk-gap-add' (rollback handle) + 'chinese'.
Frequency-ordering is done afterwards by resort_vocab.py. Dry-run unless --apply."""
import json, re, sys, time
from anki.collection import Collection
from wordfreq import zipf_frequency
try:
    import opencc; _s2t = opencc.OpenCC("s2t.json"); s2t = lambda w: _s2t.convert(w)
except Exception:
    s2t = lambda w: w

ROOT = "/home/vincent/anki-headless"
APPLY = "--apply" in sys.argv
POSMAP = {"名":"noun","动":"verb","形":"adjective","副":"adverb","数":"numeral",
          "量":"measure word","代":"pronoun","介":"preposition","连":"conjunction",
          "助":"particle","叹":"interjection","拟":"onomatopoeia","区":"attributive",
          "头":"prefix","尾":"suffix","短语":"phrase"}
def map_pos(cn): return ", ".join(p for p in (POSMAP.get(x.strip()) for x in re.split(r"[、,]",cn)) if p)
def badge(w):
    z = zipf_frequency(w,"zh")
    t = ("very common",5) if z>=5 else ("common",4) if z>=4 else ("mid",3) if z>=3.5 else ("uncommon",2) if z>0 else ("rare",1)
    return f"{'★'*t[1]} {t[0]} · zipf {z:.1f}"

HSK = {r["word"]:r for r in json.load(open(f"{ROOT}/freq_data/hsk3_vocab.json"))}
col = Collection(f"{ROOT}/collection.anki2")
cv = next(m for m in col.models.all() if m["name"]=="ChineseVocabulary")
fi = {f["name"]:i for i,f in enumerate(cv["flds"])}
vd = col.decks.id_for_name("Vocab")
cloze_did = col.decks.id("Vocab Cloze")
cloze_ord = next((t["ord"] for t in cv["tmpls"] if t["name"]=="Cloze-Recall"), None)

# current deck words (any deck, this notetype) to avoid dupes
have = set()
for (flds,) in col.db.all("SELECT flds FROM notes WHERE mid=?", cv["id"]):
    w = re.sub(r"<[^>]+>","",flds.split(chr(31))[0]).strip()
    if w: have.add(w)

# target: multi-char, HSK 4-9, missing from deck
targets = [r for w,r in HSK.items()
           if len(w)>1 and r["level"] in ("4","5","6","7-9") and w not in have]
print(f"target multi-char HSK4-9 words missing from deck: {len(targets)}")

created=0; rev_susp=0; clz=0
for r in targets:
    w = r["word"]
    if not APPLY: continue
    note = col.new_note(cv)
    note.fields[fi["Simplified"]] = w
    note.fields[fi["Traditional"]] = s2t(w)
    note.fields[fi["Pinyin"]] = r["pinyin"]
    note.fields[fi["Meaning"]] = r["gloss"]
    if "PartOfSpeech" in fi: note.fields[fi["PartOfSpeech"]] = map_pos(r["pos"])
    if "CustomFreq" in fi: note.fields[fi["CustomFreq"]] = badge(w)
    note.tags = ["chinese", "hsk-gap-add", f"HSK3.0::{r['level']}"]
    col.add_note(note, vd)
    for c in note.cards():
        if c.ord == 1: col.sched.suspend_cards([c.id]); rev_susp+=1
        elif cloze_ord is not None and c.ord == cloze_ord:
            col.set_deck([c.id], cloze_did); col.sched.suspend_cards([c.id]); clz+=1
    created += 1

if APPLY:
    print(f"created {created} notes | reverse suspended {rev_susp} | cloze routed {clz}")
    # verify
    n = len(col.find_notes("tag:hsk-gap-add"))
    act = len(col.find_cards("deck:Vocab tag:hsk-gap-add -is:suspended"))
    print(f"VERIFY: notes tagged hsk-gap-add={n}, active forward cards in Vocab={act}")
    print("sample:", [re.sub(r'<[^>]+>','',col.get_note(x).fields[0]) for x in col.find_notes("tag:hsk-gap-add")[:8]])
else:
    print("DRY-RUN. sample of what would be created:")
    for r in targets[:10]:
        print(f"  {r['word']} (HSK{r['level']}) {r['pinyin']} [{map_pos(r['pos'])}] — {r['gloss'][:40]} | {badge(r['word'])}")
col.close()