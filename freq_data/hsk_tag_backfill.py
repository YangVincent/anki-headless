#!/usr/bin/env python3
"""HSK 3.0 integration for the Vocab deck:
  (#1) tag every matched note with HSK::<level>
  (#3) backfill ONLY-empty Meaning / PartOfSpeech from the official HSK list,
       and write a report of glosses that disagree with the official one (no edit).
Dry-run unless --apply. Run via anki_op.sh. Verifies before exit."""
import json, re, sys
from anki.collection import Collection

ROOT = "/home/vincent/anki-headless"
APPLY = "--apply" in sys.argv
HSK = {r["word"]: r for r in json.load(open(f"{ROOT}/freq_data/hsk3_vocab.json"))}
POSMAP = {"名":"noun","动":"verb","形":"adjective","副":"adverb","数":"numeral",
          "量":"measure word","代":"pronoun","介":"preposition","连":"conjunction",
          "助":"particle","叹":"interjection","拟":"onomatopoeia","区":"attributive",
          "头":"prefix","尾":"suffix","短语":"phrase"}
def map_pos(cn):
    parts = [POSMAP.get(p.strip()) for p in re.split(r"[、,]", cn) if p.strip()]
    return ", ".join(p for p in parts if p)

def norm(s):  # crude gloss-similarity normalization
    return set(re.findall(r"[a-z]+", re.sub(r"<[^>]+>","",s).lower()))

col = Collection(f"{ROOT}/collection.anki2")
cv = next(m for m in col.models.all() if m["name"]=="ChineseVocabulary")
fi = {f["name"]:i for i,f in enumerate(cv["flds"])}
vd = col.decks.id_for_name("Vocab")
nids = col.db.list("SELECT DISTINCT n.id FROM cards c JOIN notes n ON c.nid=n.id WHERE c.did=? AND n.mid=?", vd, cv["id"])

tagged=mean_fill=pos_fill=disagree=0
disagreements=[]
for nid in nids:
    note = col.get_note(nid)
    w = re.sub(r"<[^>]+>","",note.fields[fi["Simplified"]]).strip()
    r = HSK.get(w)
    if not r: continue
    tag = f"HSK::{r['level']}"
    if not note.has_tag(tag):
        note.add_tag(tag); tagged+=1
    # backfill empties only
    if not note.fields[fi["Meaning"]].strip() and r["gloss"]:
        note.fields[fi["Meaning"]] = r["gloss"]; mean_fill+=1
    elif r["gloss"] and note.fields[fi["Meaning"]].strip():
        a,b = norm(note.fields[fi["Meaning"]]), norm(r["gloss"])
        if a and b and not (a & b):           # zero shared content words -> flag
            disagree+=1
            if len(disagreements)<400:
                disagreements.append({"word":w,"level":r["level"],
                    "deck":re.sub(r'<[^>]+>','',note.fields[fi['Meaning']])[:60],"hsk":r["gloss"][:60]})
    if not note.fields[fi["PartOfSpeech"]].strip():
        mp = map_pos(r["pos"])
        if mp: note.fields[fi["PartOfSpeech"]]=mp; pos_fill+=1
    if APPLY: col.update_note(note)

print(f"matched HSK notes (tag candidates): tagged+={tagged}")
print(f"empty Meaning backfilled: {mean_fill}")
print(f"empty PartOfSpeech backfilled: {pos_fill}")
print(f"gloss disagreements flagged (NOT changed): {disagree}")
json.dump(disagreements, open(f"{ROOT}/freq_data/hsk_gloss_disagreements.json","w"), ensure_ascii=False, indent=1)
print(f"-> freq_data/hsk_gloss_disagreements.json (sample {len(disagreements)})")
if APPLY:
    # verify a tag landed
    from collections import Counter
    lc=Counter()
    for nid in nids:
        for t in col.get_note(nid).tags:
            if t.startswith("HSK::"): lc[t]+=1
    print("APPLIED. tag counts:", dict(sorted(lc.items())))
else:
    print("DRY-RUN (no changes). re-run with --apply via anki_op.sh")
col.close()