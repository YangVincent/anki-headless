#!/usr/bin/env python3
"""Reorder hanly new-card queue by corpus frequency (most common first) and
suspend very-rare idiom cards (zipf<2.0). Uses official Anki API for sync safety."""
import json, re, sys
from wordfreq import zipf_frequency

COLLECTION = "/home/vincent/anki-headless/collection.anki2"
HANLY_DID = 1770350587056
SUSPEND_BELOW = 2.0

def clean(s): return re.sub(r"<[^>]+>", "", s or "").strip()

with open("quality/all_notes.json") as f:
    notes = json.load(f)
nid2word = {n["nid"]: clean(n.get("Simplified","")) for n in notes}

from anki.collection import Collection
col = Collection(COLLECTION)
try:
    # all NEW cards in hanly (queue/type new)
    new_cids = col.db.list(
        "SELECT id FROM cards WHERE did=? AND type=0", HANLY_DID)
    info = []  # (zipf, current_due, cid, word)
    for cid in new_cids:
        nid = col.db.scalar("SELECT nid FROM cards WHERE id=?", cid)
        due = col.db.scalar("SELECT due FROM cards WHERE id=?", cid)
        word = nid2word.get(nid, "")
        z = zipf_frequency(word, "zh") if word else 0.0
        info.append((z, due, cid, word))

    # order: most frequent first; stable tiebreak on existing due
    info.sort(key=lambda x: (-x[0], x[1]))
    ordered_cids = [cid for (_z,_d,cid,_w) in info]

    print(f"Repositioning {len(ordered_cids)} new cards by frequency (most common first)")
    print("New FIRST 15:", " ".join(info[i][3] for i in range(15)))
    print("New LAST 15 :", " ".join(info[i][3] for i in range(len(info)-15, len(info))))

    col.sched.reposition_new_cards(
        card_ids=ordered_cids, starting_from=1, step_size=1,
        randomize=False, shift_existing=False)

    # suspend very-rare cards (idioms/proverbs), excluding empty-word cards
    suspend = [cid for (z,_d,cid,w) in info if w and z < SUSPEND_BELOW]
    col.sched.suspend_cards(suspend)
    print(f"\nSuspended {len(suspend)} cards with zipf<{SUSPEND_BELOW}")
    print("   e.g.:", " ".join(w for (z,_d,cid,w) in info if w and z<SUSPEND_BELOW)[:200] if suspend else "")

    col.save()
    print("\nSaved collection.")
finally:
    col.close()
