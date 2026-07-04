#!/usr/bin/env python3
"""Re-sort the Vocab new-card backbone purely by frequency. Mined cards are NO LONGER
pinned to the front — below-frontier mined words live in the separate 'Mined' deck, and
any at-frontier mined words still in Vocab just sort to their natural frequency slot.
Run via anki_op.sh. Dry-run unless --apply; verifies inline."""
import re, sys
from anki.collection import Collection
from wordfreq import zipf_frequency

ROOT="/home/vincent/anki-headless"
APPLY="--apply" in sys.argv

col=Collection(f"{ROOT}/collection.anki2")
try:
    SEP=chr(31)
    vd=col.decks.id_for_name("Vocab")
    rows=col.db.all("SELECT c.id,c.nid FROM cards c WHERE c.did=? AND c.type=0 AND c.ord=0",vd)
    # cards tagged 'demoted' (frequency overstates real usefulness, e.g. 人中) sort to the BACK
    demoted=set(col.find_cards("deck:Vocab tag:demoted"))
    order=[]
    for cid,nid in rows:
        if cid in demoted:
            order.append((-1.0,cid)); continue
        mid,flds=col.db.first("SELECT mid,flds FROM notes WHERE id=?",nid)
        w=re.sub(r"<[^>]+>","",flds.split(SEP)[0]).strip()
        order.append((zipf_frequency(w,"zh") if w else 0.0,cid))
    order.sort(key=lambda x:-x[0])   # demoted (-1.0) land last
    print(f"  ({len(demoted)} demoted card(s) pushed to back)")
    print(f"Vocab new cards to re-sort purely by frequency: {len(order)}")
    if APPLY:
        col.sched.reposition_new_cards([c for _,c in order],starting_from=1,step_size=1,
                                       randomize=False,shift_existing=False)
        top=col.db.all("SELECT n.flds FROM cards c JOIN notes n ON c.nid=n.id WHERE c.did=? AND c.type=0 AND c.ord=0 ORDER BY c.due LIMIT 6",vd)
        ws=[re.sub(r'<[^>]+>','',f.split(SEP)[0]).strip() for (f,) in top]
        print(f"APPLIED: re-sorted {len(order)} cards. Frontmost (highest-freq): {' '.join(ws)}")
    else:
        print("DRY-RUN (no changes).")
finally:
    col.close()
