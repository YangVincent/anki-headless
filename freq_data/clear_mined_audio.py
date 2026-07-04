#!/usr/bin/env python3
"""Silence mined cards: clear the Audio and SentenceAudio fields on every mined note
(they auto-play on the answer side via the template's {{Audio}}/{{SentenceAudio}}).
Targeted — only touches mined notes, so all other cards keep their audio. The media
files stay in the collection (just unlinked), so it's reversible. Dry-run unless --apply.
Run via anki_op.sh."""
import sys, re
from anki.collection import Collection
APPLY = "--apply" in sys.argv
ROOT = "/home/vincent/anki-headless"
def clean(s): return re.sub(r'<[^>]+>', '', s or '').strip()

col = Collection(f"{ROOT}/collection.anki2")
try:
    cv = col.models.by_name("ChineseVocabulary"); SEP = chr(31)
    fi = {f['name']: i for i, f in enumerate(cv['flds'])}
    vd = col.decks.id_for_name("Vocab"); md = col.decks.id_for_name("Mined")
    afld = fi['Audio']; sfld = fi.get('SentenceAudio')

    nids = col.db.list("SELECT DISTINCT n.id FROM cards c JOIN notes n ON c.nid=n.id "
                       "WHERE c.ord=0 AND n.mid=? AND n.tags LIKE '%mined%' AND c.did IN (?,?)",
                       cv['id'], vd, md)
    cleared = 0
    for nid in nids:
        note = col.get_note(nid)
        had = bool(clean(note.fields[afld])) or (sfld is not None and bool(clean(note.fields[sfld])))
        if not had:
            continue
        note.fields[afld] = ""
        if sfld is not None: note.fields[sfld] = ""
        if APPLY: col.update_note(note)
        cleared += 1
    print(f"mined notes: {len(nids)} | had audio -> cleared: {cleared}")
    print("APPLIED." if APPLY else "DRY-RUN (use --apply)")
finally:
    col.close()
