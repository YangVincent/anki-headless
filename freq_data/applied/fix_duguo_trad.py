"""Fill the Traditional field on 渡过.

Not a consistency fix -- an empty Traditional is the majority in HSK7-9 (2827 of 5041).
The reason is local to the pair: 度过 shows 度過 on its back and 渡过 shows nothing,
so the two halves of the pair we just separated do not present the same way.

Pinyin spacing is deliberately NOT touched. HSK prefers the joined form (2191 v 813)
and HSK7-9 prefers the spaced form (2328 v 1582). Both cards already match their deck.

Run through freq_data/anki_op.sh. Dry-run by default; pass --apply to write.
"""
import sys
from anki.collection import Collection

APPLY = "--apply" in sys.argv
NID = 1708747494414  # 渡过

col = Collection("/home/vincent/anki-headless/collection.anki2")
try:
    note = col.get_note(NID)
    idx = {f["name"]: i for i, f in enumerate(note.note_type()["flds"])}
    assert note.fields[idx["Simplified"]] == "渡过", note.fields[idx["Simplified"]]
    old = note.fields[idx["Traditional"]]
    print(f"=== note {NID} 渡过")
    print(f"    Traditional was: {old!r}")
    if old.strip():
        print("    already filled; nothing to do")
    else:
        note.fields[idx["Traditional"]] = "渡過"
        print(f"    Traditional now: {note.fields[idx['Traditional']]!r}")
        if APPLY:
            col.update_note(note)
            got = col.get_note(NID).fields[idx["Traditional"]]
            print(f"    verify re-read: {got!r}")
            assert got == "渡過", got
            print("APPLIED")
        else:
            print("DRY-RUN (pass --apply to write)")
finally:
    col.close()
