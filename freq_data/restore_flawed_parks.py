#!/usr/bin/env python3
"""One-off repair: unsuspend the cards the --not-hsk-word sweep parked in error.

That sweep judged "is this an HSK word" against app/data/hsk30.tsv, which turned out to
have holes (it lacks 表示, 玩, …). Checked against freq_data/hsk3_vocab.json, 6 of the 78
parked characters ARE HSK 3.0 words: 劲 呼 嗯 均 竞 胸 (8 cards). This restores exactly
those, identified from the hsk_match undo snapshot (the sweep tags themselves are gone).

  restore_flawed_parks.py            # dry run
  restore_flawed_parks.py --apply    # via freq_data/anki_op.sh
"""
import argparse
import json
import re
from pathlib import Path
from anki_common import sync as _sync

ROOT = Path("/home/vincent/anki-headless")
COL = ROOT / "collection.anki2"
SNAP = ROOT / "generated" / "hsk_match_undo.json"
VOCAB = ROOT / "freq_data" / "hsk3_vocab.json"
HANZI = re.compile(r"^[一-鿿]$")



def main():
    from anki.collection import Collection

    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--col", default=str(COL))
    a = ap.parse_args()
    if a.apply and a.col != str(COL):
        raise SystemExit("--apply only ever writes the real collection")

    snap = json.loads(SNAP.read_text(encoding="utf-8"))
    vj = {x["word"] for x in json.loads(VOCAB.read_text(encoding="utf-8"))}
    nids = [int(n) for n, tags in snap["tags"].items() if "parked::not-hsk-word" in tags]

    col = Collection(a.col)
    try:
        rows = col.db.all(
            "select c.id, c.queue, n.sfld from cards c join notes n on n.id = c.nid "
            f"where n.id in ({','.join(map(str, nids))})")
        restore = [(cid, str(s).strip()) for cid, q, s in rows
                   if q == -1 and HANZI.match(str(s or "").strip()) and str(s).strip() in vj]
        chars = sorted({s for _, s in restore})
        print(f"{len(restore)} cards / {len(chars)} chars parked against the holey tsv "
              f"but present in hsk3_vocab.json: {' '.join(chars)}")
        if not a.apply:
            print("(dry run)")
            return
        col.sched.unsuspend_cards([cid for cid, _ in restore])
        left = [cid for cid, _ in restore if col.get_card(cid).queue == -1]
        assert not left, f"{len(left)} cards still suspended"
        print("restored ✓")
        _sync(col)
    finally:
        col.close()


if __name__ == "__main__":
    main()
