#!/usr/bin/env python3
"""Sweep up any Cloze-Recall (ord 2) cards that aren't in 'Vocab Cloze'.
 - if the note has an ord-0 card in Vocab -> move to Vocab Cloze, suspend, due=ord0 rank
 - otherwise (archive/orphan) -> delete the stray cloze card
Leaves Default empty so it disappears. Dry-run unless --apply. Run via anki_op.sh."""
import sys
from anki.collection import Collection
APPLY = "--apply" in sys.argv
ROOT = "/home/vincent/anki-headless"

col = Collection(f"{ROOT}/collection.anki2")
try:
    cv = col.models.by_name("ChineseVocabulary")
    vd = col.decks.id_for_name("Vocab")
    cd = col.decks.id_for_name("Vocab Cloze")
    cloze_ord = next(t['ord'] for t in cv['tmpls'] if t['name'] == "Cloze-Recall")
    ord0_due = dict(col.db.all(
        "SELECT n.id, c.due FROM cards c JOIN notes n ON c.nid=n.id WHERE c.did=? AND c.ord=0 AND n.mid=?", vd, cv['id']))
    vocab_nids = set(ord0_due)

    strays = col.db.all(
        "SELECT c.id, c.nid, c.did FROM cards c JOIN notes n ON c.nid=n.id "
        "WHERE c.ord=? AND n.mid=? AND c.did<>?", cloze_ord, cv['id'], cd)
    by_deck = {}
    for cid, nid, did in strays:
        by_deck.setdefault(col.decks.name(did), 0)
        by_deck[col.decks.name(did)] += 1
    print(f"stray cloze cards (ord {cloze_ord}) outside Vocab Cloze: {len(strays)}")
    for dn, n in by_deck.items(): print(f"   in '{dn}': {n}")

    if APPLY and strays:
        routed = deleted = 0
        for cid, nid, did in strays:
            if nid in vocab_nids:
                col.set_deck([cid], cd)
                col.sched.suspend_cards([cid])
                d = ord0_due.get(nid)
                if d is not None:
                    col.db.execute("UPDATE cards SET due=?, usn=-1 WHERE id=?", int(d), cid)
                routed += 1
            else:
                col.remove_cards_and_orphaned_notes([cid]); deleted += 1
        print(f"APPLIED: routed {routed} to Vocab Cloze (suspended), deleted {deleted} orphan/archive")
    elif not APPLY:
        print("DRY-RUN (use --apply)")

    # report Default emptiness
    dd = col.decks.id_for_name("Default")
    if dd is not None:
        print("cards left in Default:", col.db.scalar("SELECT COUNT(*) FROM cards WHERE did=?", dd))
finally:
    col.close()
