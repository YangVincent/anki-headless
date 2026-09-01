"""Delete the archived duplicate 商谈 note, keeping its audio.

  1708747505321  Archive, both cards suspended, 0 reps, sentence is a subtitle
                 fragment ("什么嘛 区区裸照好好商谈一下的话")            <- delete
  1783527789132  Mined, in learning, 2 reps, has Traditional + CustomFreq  <- keep

The loser carries an Audio reference the keeper lacks. collection.media on this host is
EMPTY (0 files) -- media lives on the synced devices -- so the file cannot be checked
here and must not be assumed dead. Copy the reference across before deleting.

Run through freq_data/anki_op.sh. Dry-run by default; pass --apply to write.
"""
import sys
from anki.collection import Collection

APPLY = "--apply" in sys.argv
DROP, KEEP = 1708747505321, 1783527789132

col = Collection("/home/vincent/anki-headless/collection.anki2")
try:
    drop, keep = col.get_note(DROP), col.get_note(KEEP)
    idx = {f["name"]: i for i, f in enumerate(keep.note_type()["flds"])}
    assert drop.fields[idx["Simplified"]] == "商谈", drop.fields[idx["Simplified"]]
    assert keep.fields[idx["Simplified"]] == "商谈", keep.fields[idx["Simplified"]]

    # Never delete the note that carries the study history.
    drop_reps = col.db.scalar("select coalesce(sum(reps),0) from cards where nid=?", DROP)
    keep_reps = col.db.scalar("select coalesce(sum(reps),0) from cards where nid=?", KEEP)
    print(f"drop {DROP} reps={drop_reps}   keep {KEEP} reps={keep_reps}")
    assert drop_reps == 0 and keep_reps >= drop_reps, "the note being deleted has history"
    live = col.db.scalar(
        "select count(*) from cards where nid=? and queue>=0", DROP)
    assert live == 0, f"{DROP} still has {live} unsuspended card(s)"

    audio = drop.fields[idx["Audio"]].strip()
    if audio and not keep.fields[idx["Audio"]].strip():
        print(f"carrying audio to {KEEP}: {audio[:48]}…")
        keep.fields[idx["Audio"]] = audio
        if APPLY:
            col.update_note(keep)
    print(f"deleting note {DROP} and its {len(drop.cards())} card(s)")

    if APPLY:
        col.remove_notes([DROP])
        assert col.db.scalar("select count(*) from notes where id=?", DROP) == 0
        again = col.get_note(KEEP)
        print(f"verify: {DROP} gone; keeper Audio = {again.fields[idx['Audio']][:48]}…")
        left = col.db.scalar(
            "select count(*) from notes where mid=? and flds like ?",
            keep.mid, "商谈\x1f%")
        print(f"verify: notes with Simplified 商谈 remaining = {left}")
        assert left == 1
        print("APPLIED")
    else:
        print("DRY-RUN (pass --apply to write)")
finally:
    col.close()
