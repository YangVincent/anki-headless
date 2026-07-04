#!/usr/bin/env python3
"""PERMANENT fix for the resurrecting archive cloze cards: clear the cloze trigger
fields (SentenceSimplifiedCloze / SentenceTraditionalCloze) on every ChineseVocabulary
note that is NOT in the Vocab deck. With an empty trigger field, Anki never generates a
Cloze-Recall card for them again — so update_dict() can no longer resurrect strays into
Default/Archive/Personal. Updating the note also removes any currently-existing stray.
Dry-run unless --apply. Run via anki_op.sh."""
import sys, re
from anki.collection import Collection
APPLY = "--apply" in sys.argv
ROOT = "/home/vincent/anki-headless"
def clean(s): return re.sub(r'<[^>]+>', '', s or '').strip()

col = Collection(f"{ROOT}/collection.anki2")
try:
    cv = col.models.by_name("ChineseVocabulary"); SEP = chr(31)
    fi = {f['name']: i for i, f in enumerate(cv['flds'])}
    vd = col.decks.id_for_name("Vocab")
    csc, ctc = fi['SentenceSimplifiedCloze'], fi.get('SentenceTraditionalCloze')

    vocab_nids = set(col.db.list(
        "SELECT n.id FROM cards c JOIN notes n ON c.nid=n.id WHERE c.did=? AND c.ord=0 AND n.mid=?", vd, cv['id']))

    to_clear = []
    for nid, flds in col.db.all("SELECT id, flds FROM notes WHERE mid=?", cv['id']):
        if nid in vocab_nids:
            continue
        f = flds.split(SEP)
        if clean(f[csc]) or (ctc is not None and clean(f[ctc])):
            to_clear.append(nid)

    dd = col.decks.id_for_name("Default")
    default_before = col.db.scalar("SELECT COUNT(*) FROM cards WHERE did=?", dd) if dd else 0
    print(f"non-Vocab notes with cloze fields to clear: {len(to_clear)}")
    print(f"cards currently in Default: {default_before}")

    if APPLY and to_clear:
        for nid in to_clear:
            note = col.get_note(nid)
            note.fields[csc] = ""
            if ctc is not None: note.fields[ctc] = ""
            col.update_note(note)   # empties trigger -> removes the cloze card
        cloze_ord = next((t['ord'] for t in cv['tmpls'] if t['name'] == "Cloze-Recall"), None)
        strays = col.db.scalar(
            "SELECT COUNT(*) FROM cards WHERE ord=? AND nid IN (SELECT id FROM notes WHERE mid=?) AND did<>?",
            cloze_ord, cv['id'], col.decks.id_for_name("Vocab Cloze"))
        dd = col.decks.id_for_name("Default")
        print(f"APPLIED: cleared {len(to_clear)} notes.")
        print(f"  stray cloze cards outside Vocab Cloze now: {strays}")
        print(f"  cards in Default now: {col.db.scalar('SELECT COUNT(*) FROM cards WHERE did=?', dd) if dd else 0}")
    elif not APPLY:
        print("DRY-RUN (use --apply)")
finally:
    col.close()
