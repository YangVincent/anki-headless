"""Remove the `demoted` tag accidentally applied to 〇.

It came from a test: `resort_hsk_queue.py --db <scratch copy> --apply` tags nothing
itself, but --apply SYNCS, and it synced the scratch collection's state to AnkiWeb. The
live collection then pulled the test tag down. 〇's ord0 card is suspended, so its queue
position was never in play; only the tag needs undoing.

人中 keeps its tag -- that one is deliberate and predates this.
"""
import sys
from anki.collection import Collection

APPLY = "--apply" in sys.argv
NID = 1785790496820

col = Collection("/home/vincent/anki-headless/collection.anki2")
try:
    n = col.get_note(NID)
    idx = {f["name"]: i for i, f in enumerate(n.note_type()["flds"])}
    assert n.fields[idx["Simplified"]] == "〇", n.fields[idx["Simplified"]]
    print("tags before:", n.tags)
    n.tags = [t for t in n.tags if t.lower() != "demoted"]
    print("tags after :", n.tags)
    if APPLY:
        col.update_note(n)
        assert "demoted" not in [t.lower() for t in col.get_note(NID).tags]
        left = col.db.list("SELECT id FROM notes WHERE tags LIKE '% demoted %'")
        print(f"notes still tagged demoted: {left} (expect only 人中)")
        assert left == [1537328239534]
        print("APPLIED")
    else:
        print("DRY-RUN")
finally:
    col.close()
