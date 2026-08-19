#!/usr/bin/env python3
"""(1) Re-move any mined ord0 cards that drifted back into Vocab below the 5.0 cutoff
(happens when a card studied on a not-yet-synced phone wins the merge) into the Mined
deck — keeps learning progress. (2) Refresh CustomFreq on ALL mined notes (Vocab + Mined)
to a consistent '★ rating · zipf X.X' badge reflecting the true live frequency.
Dry-run unless --apply. Run via anki_op.sh."""
import sys, re
from anki.collection import Collection
from wordfreq import zipf_frequency
APPLY = "--apply" in sys.argv
CUTOFF = 5.0
ROOT = "/home/vincent/anki-headless"
def clean(s): return re.sub(r'<[^>]+>', '', s or '').strip()
def label(z):
    if   z >= 5.0: s, t = "★★★★★", "very common"
    elif z >= 4.5: s, t = "★★★★", "common"
    elif z >= 4.0: s, t = "★★★", "mid"
    elif z >= 3.5: s, t = "★★", "uncommon"
    else:          s, t = "★", "rare"
    return f"{s} {t} · zipf {z:.1f}"

col = Collection(f"{ROOT}/collection.anki2")
try:
    cv = col.models.by_name("ChineseVocabulary"); SEP = chr(31)
    fi = {f['name']: i for i, f in enumerate(cv['flds'])}
    vd = col.decks.id_for_name("Vocab"); md = col.decks.id("Mined")

    # 1) stragglers: mined ord0 in Vocab with zipf < cutoff -> Mined
    rows = col.db.all("SELECT c.id, n.flds FROM cards c JOIN notes n ON c.nid=n.id "
                      "WHERE c.did=? AND c.ord=0 AND n.mid=? AND n.tags LIKE '%mined%'", vd, cv['id'])
    move = [cid for cid, flds in rows if zipf_frequency(clean(flds.split(SEP)[fi['Simplified']]), 'zh') < CUTOFF]
    print(f"stragglers (mined Zipf<{CUTOFF} back in Vocab) to re-move: {len(move)}")
    if APPLY and move:
        col.set_deck(move, md)

    # 2) refresh CustomFreq on all mined notes (Vocab + Mined)
    mnids = col.db.list("SELECT DISTINCT n.id FROM cards c JOIN notes n ON c.nid=n.id "
                        "WHERE c.ord=0 AND n.mid=? AND n.tags LIKE '%mined%' AND c.did IN (?,?)",
                        cv['id'], vd, md)
    refreshed = 0
    for nid in mnids:
        note = col.get_note(nid)
        z = zipf_frequency(clean(note.fields[fi['Simplified']]), 'zh')
        new = label(z)
        if clean(note.fields[fi['CustomFreq']]) != new:
            note.fields[fi['CustomFreq']] = new
            if APPLY: col.update_note(note)
            refreshed += 1
    print(f"CustomFreq badges to refresh on mined notes: {refreshed} / {len(mnids)}")
    print("APPLIED." if APPLY else "DRY-RUN (use --apply)")
finally:
    col.close()
