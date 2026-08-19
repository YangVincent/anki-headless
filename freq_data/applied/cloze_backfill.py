#!/usr/bin/env python3
"""Backfill cloze blanks for Vocab words that have a sentence but no SentenceSimplifiedCloze.
Derives the blank deterministically: clean the sentence, replace the first occurrence of the
word with '[ ]'. Fills SentenceSimplifiedCloze (+ Traditional). Updating the note regenerates
the now-eligible Cloze-Recall card; we then route those new cards into 'Vocab Cloze' (suspended,
due = ord0 frequency rank). The daily gate will release them as the words mature.
Not a schema change -> a normal sync suffices. Dry-run unless --apply. Run via anki_op.sh."""
import sys, re
from anki.collection import Collection
APPLY = "--apply" in sys.argv
ROOT = "/home/vincent/anki-headless"
def clean(s): return re.sub(r'<[^>]+>', '', s or '').replace('\xa0', ' ').strip()
def blank(s, w): return s.replace(w, "[ ]", 1) if (s and w and w in s) else None

col = Collection(f"{ROOT}/collection.anki2")
try:
    cv = col.models.by_name("ChineseVocabulary")
    fi = {f['name']: i for i, f in enumerate(cv['flds'])}
    vd = col.decks.id_for_name("Vocab")
    cd = col.decks.id("Vocab Cloze")
    cloze_ord = next(t['ord'] for t in cv['tmpls'] if t['name'] == "Cloze-Recall")

    rows = col.db.all(
        "SELECT n.id, c.due FROM cards c JOIN notes n ON c.nid=n.id "
        "WHERE c.did=? AND c.ord=0 AND n.mid=?", vd, cv['id'])
    ord0_due = dict(rows)

    filled = skipped = 0
    touched = []
    for nid, _due in rows:
        note = col.get_note(nid)
        ss = clean(note.fields[fi['SentenceSimplified']])
        sc = clean(note.fields[fi['SentenceSimplifiedCloze']])
        if not ss or sc:        # no sentence, or already has a cloze blank
            continue
        w = clean(note.fields[fi['Simplified']])
        cz = blank(ss, w)
        if not cz:              # word not literally in its own sentence -> can't blank
            skipped += 1; continue
        note.fields[fi['SentenceSimplifiedCloze']] = cz
        st = clean(note.fields[fi['SentenceTraditional']])
        tw = clean(note.fields[fi['Traditional']]) or w
        czt = blank(st, tw)
        if czt: note.fields[fi['SentenceTraditionalCloze']] = czt
        if APPLY: col.update_note(note)   # regenerates the now-eligible cloze card
        filled += 1; touched.append(nid)

    print(f"{'APPLIED' if APPLY else 'DRY-RUN'}: filled cloze blanks on {filled} notes, skipped {skipped} (word not in sentence)")

    if APPLY and touched:
        # route the freshly generated cloze cards into Vocab Cloze: suspend + freq-order due
        routed = 0
        for nid in touched:
            cid = col.db.scalar("SELECT id FROM cards WHERE nid=? AND ord=?", nid, cloze_ord)
            if not cid: continue
            d = ord0_due.get(nid)
            if col.db.scalar("SELECT did FROM cards WHERE id=?", cid) != cd:
                col.set_deck([cid], cd)
            col.sched.suspend_cards([cid])
            if d is not None:
                col.db.execute("UPDATE cards SET due=?, usn=-1 WHERE id=?", int(d), cid)
            routed += 1
        tot = col.db.scalar("SELECT COUNT(*) FROM cards WHERE did=?", cd)
        print(f"routed {routed} new cloze cards into Vocab Cloze (suspended). Deck now {tot} cards total.")
finally:
    col.close()
