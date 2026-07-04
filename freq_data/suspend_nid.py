#!/usr/bin/env python3
"""Suspend all active cards for a ChineseVocabulary note by nid.
Usage: suspend_nid.py <nid> <expected_simplified>"""
import sys
from anki.collection import Collection

NID = int(sys.argv[1])
EXPECT = sys.argv[2]
col = Collection("collection.anki2")
note = col.get_note(NID)
assert note["Simplified"] == EXPECT, f"unexpected note: {note['Simplified']!r}"

active = [c for c in note.cards() if c.queue != -1]
print("active cards before:", [(c.id, col.decks.name(c.did)) for c in active])
if active:
    col.sched.suspend_cards([c.id for c in active])

note = col.get_note(NID)
for c in note.cards():
    print(f"card {c.id}: deck={col.decks.name(c.did)} queue={c.queue} suspended={c.queue==-1}")
col.close()
print("done")
