#!/usr/bin/env python3
"""Suspend active Vocab cards for the words marked SUSPEND in frag_triage.csv.
Segmentation-fragment false positives (jieba splits them; wordfreq inflated their zipf)."""
import csv, re
from anki.collection import Collection

ROOT = "/home/vincent/anki-headless"
words = set()
with open(f"{ROOT}/freq_data/frag_triage.csv") as fh:
    for row in csv.DictReader(fh):
        if row["label"] == "SUSPEND":
            words.add(row["word"])
print(f"target words: {len(words)}")

col = Collection(f"{ROOT}/collection.anki2")
cv = next(m for m in col.models.all() if m["name"] == "ChineseVocabulary")
fi = {f["name"]: i for i, f in enumerate(cv["flds"])}
vd = col.decks.id_for_name("Vocab")
rows = col.db.all("SELECT n.id,n.flds FROM cards c JOIN notes n ON c.nid=n.id "
                  "WHERE c.did=? AND n.mid=? AND c.queue!=-1", vd, cv["id"])
to_suspend, matched = [], set()
for nid, flds in rows:
    f = flds.split(chr(31))
    w = re.sub(r"<[^>]+>", "", f[fi["Simplified"]]).strip()
    if w in words:
        note = col.get_note(nid)
        to_suspend += [c.id for c in note.cards() if c.queue != -1]
        matched.add(w)

missing = words - matched
print(f"matched {len(matched)} words -> {len(to_suspend)} active cards")
if missing:
    print("NOT FOUND (already suspended / not active):", " ".join(sorted(missing)))
if to_suspend:
    col.sched.suspend_cards(to_suspend)

# verify
still = col.db.scalar(
    "SELECT COUNT(*) FROM cards c JOIN notes n ON c.nid=n.id "
    "WHERE c.did=? AND n.mid=? AND c.queue!=-1 AND " +
    "REPLACE(n.flds,'','')<>n.flds", vd, cv["id"]) if False else None
remaining = 0
for nid, flds in rows:
    f = flds.split(chr(31))
    w = re.sub(r"<[^>]+>", "", f[fi["Simplified"]]).strip()
    if w in matched:
        note = col.get_note(nid)
        remaining += sum(1 for c in note.cards() if c.queue != -1)
print(f"active cards remaining among matched words: {remaining}")
col.close()
print("done")
