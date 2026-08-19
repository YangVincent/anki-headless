#!/usr/bin/env python3
"""Read-only snapshot of the Vocab deck — safe to run through anki_op.sh."""
import re, collections
from anki.collection import Collection
from wordfreq import zipf_frequency

col = Collection("/home/vincent/anki-headless/collection.anki2")
try:
    SEP = chr(31)
    nt = {m["id"]: {f["name"]: i for i, f in enumerate(m["flds"])} for m in col.models.all()}
    def word(nid):
        mid, flds = col.db.first("SELECT mid,flds FROM notes WHERE id=?", nid)
        return re.sub(r"<[^>]+>", "", flds.split(SEP)[nt[mid].get("Simplified", 0)]).strip()

    vd = col.decks.id_for_name("Vocab")
    tc = collections.Counter(col.db.list("SELECT type FROM cards WHERE did=?", vd))
    print("Vocab card types (0=new,1=learn,2=review,3=relearn):", dict(tc))

    new = col.db.all("SELECT id,nid FROM cards WHERE did=? AND type=0 ORDER BY due", vd)
    print(f"new-card queue length: {len(new):,}")
    print("first 10:", " ".join(word(nid) for _, nid in new[:10]))
    print("last 10 :", " ".join(word(nid) for _, nid in new[-10:]))
finally:
    col.close()
