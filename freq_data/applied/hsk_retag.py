#!/usr/bin/env python3
"""Move my just-added HSK 3.0 tags out of the HSK:: namespace (which already holds
the user's old HSK 2.0 tags HSK::HSK1..6) into a clean HSK3.0:: namespace.
Only touches the exact tags I created (HSK::1..6, HSK::7-9). Run via anki_op.sh."""
from anki.collection import Collection
col = Collection("/home/vincent/anki-headless/collection.anki2")
MINE = ["1","2","3","4","5","6","7-9"]
moved = 0
for lvl in MINE:
    old, new = f"HSK::{lvl}", f"HSK3.0::{lvl}"
    nids = col.find_notes(f'tag:{old}')
    for nid in nids:
        note = col.get_note(nid)
        if note.has_tag(old):
            note.remove_tag(old); note.add_tag(new); col.update_note(note); moved += 1
col.tags.clear_unused_tags()
from collections import Counter
lc = Counter()
for nid in col.find_notes('deck:Vocab'):
    for t in col.get_note(nid).tags:
        if t.startswith("HSK"): lc[t.split('::')[0]+'::*' if '::' in t else t]+=1
print(f"moved {moved} tag-instances HSK::N -> HSK3.0::N")
print("namespace counts:", dict(lc))
# explicit per-tag to confirm clean split
pc = Counter()
for nid in col.find_notes('deck:Vocab'):
    for t in col.get_note(nid).tags:
        if t.startswith("HSK"): pc[t]+=1
print("HSK3.0 tags:", {k:v for k,v in sorted(pc.items()) if k.startswith("HSK3.0")})
print("old HSK tags:", {k:v for k,v in sorted(pc.items()) if not k.startswith("HSK3.0")})
col.close()
print("done")