#!/usr/bin/env python3
"""Durably demote words whose corpus frequency overstates their usefulness (e.g. 人中):
tag them 'demoted' (so resort_vocab.py keeps them at the back of the queue forever) and
push their forward card deep right now. Words passed after flags. Dry-run unless --apply.
  bash anki_op.sh demote freq_data/demote.py --apply 人中 ...
Run via anki_op.sh."""
import sys, re
from anki.collection import Collection
APPLY = "--apply" in sys.argv
WORDS = [a for a in sys.argv[1:] if not a.startswith("-")] or ["人中"]
ROOT = "/home/vincent/anki-headless"

col = Collection(f"{ROOT}/collection.anki2")
try:
    cv = col.models.by_name("ChineseVocabulary"); SEP = chr(31)
    vd = col.decks.id_for_name("Vocab")
    deep = (col.db.scalar("SELECT MAX(due) FROM cards WHERE did=? AND type=0 AND ord=0", vd) or 16000) + 1
    for w in WORDS:
        nid = col.db.scalar("SELECT id FROM notes WHERE mid=? AND flds LIKE ?", cv['id'], w + SEP + "%")
        if not nid:
            print(f"{w}: not found"); continue
        note = col.get_note(nid)
        cid = col.db.scalar("SELECT id FROM cards WHERE nid=? AND ord=0", nid)
        typ, due = col.db.first("SELECT type, due FROM cards WHERE id=?", cid)
        tagged = "demoted" in [t.lower() for t in note.tags]
        print(f"{w}: ord0 type={typ}(0=new) current due={due} | demoted-tagged={tagged}")
        if APPLY:
            if not tagged:
                note.tags.append("demoted"); col.update_note(note)
            if typ == 0:
                c = col.get_card(cid); c.due = deep; col.update_card(c); deep += 1
                print(f"  -> tagged 'demoted', pushed to due {c.due} (back of queue)")
            else:
                print("  -> tagged 'demoted' (already studied; position N/A)")
    print("APPLIED." if APPLY else "DRY-RUN (use --apply)")
finally:
    col.close()
