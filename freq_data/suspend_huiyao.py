#!/usr/bin/env python3
"""One-off: suspend the active Vocab card for 会要 (huìyào), nid 1708747501488.
Mislabeled zipf 5.2 (segmentation-fragment false positive); actually rare specialist vocab."""
from anki.collection import Collection

NID = 1708747501488
col = Collection("collection.anki2")
note = col.get_note(NID)
assert note["Simplified"] == "会要", f"unexpected note: {note['Simplified']!r}"

active = [c for c in note.cards() if c.queue != -1]
print("active cards before:", [(c.id, col.decks.name(c.did)) for c in active])
if active:
    col.sched.suspend_cards([c.id for c in active])

# verify in the same window
note = col.get_note(NID)
for c in note.cards():
    print(f"card {c.id}: deck={col.decks.name(c.did)} queue={c.queue} suspended={c.queue==-1}")
col.close()
print("done")
