#!/usr/bin/env python3
"""Mark words you want sooner: tag `liked` and push them to the FRONT of their own deck.

The mirror of freq_data/demote.py. Same two design rules, learned the same way:

  * THE DECK COMES FROM THE CARD. A card lives in exactly one deck, so a word is
    promoted inside HSK, Mined or wherever it already is. Moving it to a "words I like"
    deck would take it OUT of HSK, and resort_hsk_queue.py selects `WHERE c.did = ?` --
    a moved card stops being ordered, and the HSK coverage count silently drops.

  * IT PICKS THE LIVE NOTE. Several words have an archived duplicate beside the studied
    one, so a bare lookup can land on the suspended copy and do nothing visible.

Durability: resort_hsk_queue.py honours `liked` (sorts first) and `demoted` (sorts last),
so the next resort keeps the order rather than undoing it. Nothing re-sorts Mined, so a
pushed position there simply stays.

  bash freq_data/anki_op.sh like freq_data/like.py --apply 焦虑 内疚 …
  bash freq_data/anki_op.sh like freq_data/like.py --apply --unlike 焦虑
"""
import sys

from anki.collection import Collection

APPLY = "--apply" in sys.argv
UNLIKE = "--unlike" in sys.argv
WORDS = [a for a in sys.argv[1:] if not a.startswith("-")]
ROOT = "/home/vincent/anki-headless"
SEP = chr(31)

if not WORDS:
    sys.exit("give one or more words, e.g. like.py --apply 焦虑 内疚")

col = Collection(f"{ROOT}/collection.anki2")
try:
    cv = col.models.by_name("ChineseVocabulary")
    front = {}

    def frontmost(did):
        """One position ahead of the current front of this deck's new queue."""
        if did not in front:
            lo = col.db.scalar(
                "SELECT MIN(due) FROM cards WHERE did=? AND type=0 AND ord=0", did)
            front[did] = (lo if lo is not None else 1) - 1
        return front[did]

    done = failed = 0
    for w in WORDS:
        nids = col.db.list("SELECT id FROM notes WHERE mid=? AND flds LIKE ?",
                           cv["id"], w + SEP + "%")
        if not nids:
            print(f"{w}: not found"); failed += 1; continue
        ranked = []
        for nid in nids:
            row = col.db.first(
                "SELECT id, did, type, due, queue FROM cards WHERE nid=? AND ord=0", nid)
            if row:
                ranked.append((row[4] >= 0, nid, row))
        if not ranked:
            print(f"{w}: has no ord0 card"); failed += 1; continue
        ranked.sort(key=lambda x: not x[0])
        live, nid, (cid, did, typ, due, queue) = ranked[0]
        note = col.get_note(nid)
        dname = col.decks.name(did)
        tagged = "liked" in [t.lower() for t in note.tags]

        if UNLIKE:
            print(f"{w}: deck={dname} liked={tagged} -> removing the tag")
            if APPLY and tagged:
                note.tags = [t for t in note.tags if t.lower() != "liked"]
                col.update_note(note)
                done += 1
            continue

        print(f"{w}: deck={dname} type={typ}(0=new) due={due} liked={tagged}"
              f"{'' if live else '  [all copies suspended]'}")
        if APPLY:
            if not tagged:
                note.tags.append("liked")
                col.update_note(note)
            if queue == -1:
                col.sched.unsuspend_cards([cid])
                print("  -> unsuspended")
            if typ == 0:
                c = col.get_card(cid)
                c.due = frontmost(did)
                col.update_card(c)
                front[did] -= 1
                print(f"  -> tagged 'liked', moved to due {c.due} (front of {dname})")
            else:
                print(f"  -> tagged 'liked' (already studied in {dname}; position N/A)")
            done += 1

    if APPLY:
        print(f"\n{done} changed, {failed} not found")
        for w in WORDS:
            nid = col.db.scalar("SELECT id FROM notes WHERE mid=? AND flds LIKE ? "
                                "AND tags LIKE '% liked %'", cv["id"], w + SEP + "%")
            if UNLIKE and nid is not None:
                sys.exit(f"ABORT: {w} is still tagged after --unlike")
            if not UNLIKE and nid is None and failed == 0:
                sys.exit(f"ABORT: {w} is not tagged after the write")
        print("APPLIED")
    else:
        print("\nDRY-RUN (use --apply)")
finally:
    col.close()
