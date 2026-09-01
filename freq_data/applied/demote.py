#!/usr/bin/env python3
"""Durably demote words whose corpus frequency overstates their usefulness.

Tag them `demoted` and push their ord0 card to the back of ITS OWN deck's new queue.

WHAT CHANGED FROM THE 2026-06 VERSION. That one hardcoded `col.decks.id_for_name("Vocab")`
for both the lookup and the "back of the queue" position. The Vocab deck no longer holds
any cards — the live decks are HSK, HSK7-9, Mined, non-HSK and Archive — so it computed a
depth from an empty deck and demoted into nowhere. The deck now comes from the card.

IT PICKS THE LIVE NOTE. Several words have an archived duplicate beside the studied one
(商谈 and 办妥 both did). The old `SELECT id FROM notes ... flds LIKE ?` returned whichever
row came first, so a demote could land on the suspended copy and do nothing visible.
This prefers the note whose ord0 card is unsuspended, and says so when it has to choose.

DURABILITY. The tag only holds if a sorter honours it. resort_hsk_queue.py does (HSK and
HSK7-9). Nothing currently re-sorts Mined, so the pushed position simply stays.

  bash freq_data/anki_op.sh demote freq_data/demote.py --apply 办妥 人中 …
"""
import sys

from anki.collection import Collection

APPLY = "--apply" in sys.argv
# A card already in learning/review has no new-queue position, so tagging alone does not
# get it out of your way. --reset forgets it back to new first, then pushes it to the
# back. It discards that card's scheduling (not the revlog), so it is opt-in.
RESET = "--reset" in sys.argv
WORDS = [a for a in sys.argv[1:] if not a.startswith("-")]
ROOT = "/home/vincent/anki-headless"
SEP = chr(31)

if not WORDS:
    sys.exit("give one or more words, e.g. demote.py --apply 办妥 人中")

col = Collection(f"{ROOT}/collection.anki2")
try:
    cv = col.models.by_name("ChineseVocabulary")
    deep_by_deck = {}                      # deck id -> next free position at the back

    def deepest(did):
        if did not in deep_by_deck:
            deep_by_deck[did] = (col.db.scalar(
                "SELECT MAX(due) FROM cards WHERE did=? AND type=0 AND ord=0", did)
                or 16000) + 1
        return deep_by_deck[did]

    done = failed = 0
    for w in WORDS:
        nids = col.db.list("SELECT id FROM notes WHERE mid=? AND flds LIKE ?",
                           cv["id"], w + SEP + "%")
        if not nids:
            print(f"{w}: not found"); failed += 1; continue
        # Prefer the note whose forward card is actually in rotation.
        ranked = []
        for nid in nids:
            row = col.db.first(
                "SELECT id, did, type, due, queue FROM cards WHERE nid=? AND ord=0", nid)
            if row:
                ranked.append((row[4] >= 0, nid, row))      # unsuspended first
        if not ranked:
            print(f"{w}: has no ord0 card"); failed += 1; continue
        ranked.sort(key=lambda x: not x[0])
        live, nid, (cid, did, typ, due, queue) = ranked[0]
        if len(ranked) > 1:
            print(f"{w}: {len(ranked)} notes; chose {nid} "
                  f"({'unsuspended' if live else 'all suspended'})")

        note = col.get_note(nid)
        dname = col.decks.name(did)
        tagged = "demoted" in [t.lower() for t in note.tags]
        print(f"{w}: deck={dname} type={typ}(0=new) due={due} demoted-tagged={tagged}")
        if APPLY:
            if not tagged:
                note.tags.append("demoted")
                col.update_note(note)
            if typ != 0 and RESET:
                col.sched.schedule_cards_as_new([cid])
                typ = 0
                print("  -> forgotten back to new (--reset)")
            if typ == 0:
                c = col.get_card(cid)
                c.due = deepest(did)
                col.update_card(c)
                deep_by_deck[did] += 1
                print(f"  -> tagged 'demoted', pushed to due {c.due} (back of {dname})")
            else:
                print(f"  -> tagged 'demoted' (in learning/review in {dname}; "
                      f"pass --reset to also push it back)")
            done += 1

    if APPLY:
        print(f"\nverify: {done} demoted, {failed} not found")
        for w in WORDS:
            nid = col.db.scalar("SELECT id FROM notes WHERE mid=? AND flds LIKE ? "
                                "AND tags LIKE '% demoted %'", cv["id"], w + SEP + "%")
            if nid is None and failed == 0:
                sys.exit(f"ABORT: {w} is not tagged after the write")
        print("APPLIED")
    else:
        print("\nDRY-RUN (use --apply)")
finally:
    col.close()
