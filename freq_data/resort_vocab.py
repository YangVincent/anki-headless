#!/usr/bin/env python3
"""Re-sort the Vocab new-card backbone by frequency, PRESERVING wild 'mined'
cards at the front. Run periodically (e.g. after a batch of wild adds) via
anki_op.sh. Dry-run unless --apply; verifies inline."""
import re, sys
from anki.collection import Collection
from wordfreq import zipf_frequency

ROOT="/home/vincent/anki-headless"
APPLY="--apply" in sys.argv

col=Collection(f"{ROOT}/collection.anki2")
try:
    SEP=chr(31)
    vd=col.decks.id_for_name("Vocab")
    mined=set(col.find_cards("deck:Vocab tag:mined is:new"))
    # backbone = Vocab forward (ord0) new cards that are NOT mined
    rows=col.db.all("SELECT c.id,c.nid FROM cards c WHERE c.did=? AND c.type=0 AND c.ord=0",vd)
    backbone=[(cid,nid) for cid,nid in rows if cid not in mined]
    order=[]
    for cid,nid in backbone:
        mid,flds=col.db.first("SELECT mid,flds FROM notes WHERE id=?",nid)
        w=re.sub(r"<[^>]+>","",flds.split(SEP)[0]).strip()
        order.append((zipf_frequency(w,"zh") if w else 0.0,cid))
    order.sort(key=lambda x:-x[0])
    print(f"Vocab new cards: {len(rows)} | mined (kept at front): {len(mined)} | backbone to re-sort: {len(order)}")
    if APPLY:
        # backbone starts at position 1; mined cards keep their negative due (stay in front)
        col.sched.reposition_new_cards([c for _,c in order],starting_from=1,step_size=1,
                                       randomize=False,shift_existing=False)
        # verify: lowest-due cards should be mined
        top=col.db.all("SELECT c.id FROM cards c WHERE c.did=? AND c.type=0 AND c.ord=0 ORDER BY c.due LIMIT 5",vd)
        n_mined_top=sum(1 for (cid,) in top if cid in mined)
        print(f"APPLIED: re-sorted {len(order)} backbone cards; {n_mined_top}/5 frontmost are mined")
    else:
        print("DRY-RUN (no changes).")
finally:
    col.close()
