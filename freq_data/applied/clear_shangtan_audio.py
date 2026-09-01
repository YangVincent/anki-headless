"""Undo the Audio carried onto the 商谈 keeper. Vincent does not want audio.

The delete script preserved the dead note's Audio reference on principle (never discard
data you cannot verify). Vincent's answer: he does not need audio. Clear it.
"""
import sys
from anki.collection import Collection

APPLY = "--apply" in sys.argv
NID = 1783527789132

col = Collection("/home/vincent/anki-headless/collection.anki2")
try:
    n = col.get_note(NID)
    idx = {f["name"]: i for i, f in enumerate(n.note_type()["flds"])}
    assert n.fields[idx["Simplified"]] == "商谈"
    print(f"Audio was: {n.fields[idx['Audio']][:60]!r}")
    n.fields[idx["Audio"]] = ""
    if APPLY:
        col.update_note(n)
        assert col.get_note(NID).fields[idx["Audio"]] == ""
        print("Audio now: '' — APPLIED")
    else:
        print("DRY-RUN")
finally:
    col.close()
