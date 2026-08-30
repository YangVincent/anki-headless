"""Park the duplicate 有用 note.

freq_data/lint_cards.py rule duplicate-headword found one word with two LIVE notes:

  1537328241277  有用    HSK1, mnemonic, mature at a 376-day interval   <- keep
  1537328243302  有用＃  no Notes, never studied, ord0 new in non-HSK    <- park

The ＃ was added to get past Anki's duplicate check, so the two have coexisted unnoticed.
The other 10 duplicate pairs in this collection are already handled this way -- the loser
sits suspended -- so this follows the established practice rather than inventing one.

SUSPEND, NOT DELETE. Suspending is reversible and loses no history; deleting is neither,
and it is the user's call, not a script's.

Run through freq_data/anki_op.sh. Dry-run by default; pass --apply to write.
"""
import sys
from anki.collection import Collection

APPLY = "--apply" in sys.argv
KEEP = 1537328241277
PARK = 1537328243302

col = Collection("/home/vincent/anki-headless/collection.anki2")
try:
    keep, park = col.get_note(KEEP), col.get_note(PARK)
    idx = {f["name"]: i for i, f in enumerate(park.note_type()["flds"])}
    assert keep.fields[idx["Simplified"]] == "有用", keep.fields[idx["Simplified"]]
    assert park.fields[idx["Simplified"]] == "有用＃", park.fields[idx["Simplified"]]

    # Never park the note that carries the study history.
    keep_reps = col.db.scalar("select coalesce(sum(reps),0) from cards where nid = ?", KEEP)
    park_reps = col.db.scalar("select coalesce(sum(reps),0) from cards where nid = ?", PARK)
    print(f"keep {KEEP} reps={keep_reps}   park {PARK} reps={park_reps}")
    assert keep_reps >= park_reps, "the note being parked has more history; check by hand"

    cids = [c.id for c in park.cards()]
    for c in park.cards():
        print(f"    card ord={c.ord} queue={c.queue} -> suspended")
    tags = "duplicate"
    print(f"    tags {park.tags} -> +{tags}")
    if APPLY:
        col.sched.suspend_cards(cids)
        if tags not in park.tags:
            park.tags.append(tags)
            col.update_note(park)
        left = col.db.scalar(
            "select count(*) from cards where nid = ? and queue >= 0", PARK)
        print(f"    verify: live cards left on {PARK} = {left}")
        assert left == 0
        print("APPLIED")
    else:
        print("DRY-RUN (pass --apply to write)")
finally:
    col.close()
