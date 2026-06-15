#!/usr/bin/env python3
"""Remove foreign-notetype (non-ChineseVocabulary) cards from Vocab back to
Archive::Words (suspended); swap in the 38 words that already have a proper
ChineseVocabulary card; reposition Vocab by frequency. Inline verify.
Dry-run unless --apply. Run via anki_op.sh."""
import json, re, sys
from anki.collection import Collection
from wordfreq import zipf_frequency

ROOT="/home/vincent/anki-headless"
APPLY="--apply" in sys.argv
fix=json.load(open(f"{ROOT}/freq_data/foreign_fix.json"))
reuse_rich=fix["reuse_rich"]

col=Collection(f"{ROOT}/collection.anki2")
try:
    SEP=chr(31)
    cv=next(m for m in col.models.all() if m["name"]=="ChineseVocabulary")
    vd=col.decks.id_for_name("Vocab"); arch=col.decks.id_for_name("Archive::Words")
    # foreign cards currently in Vocab (any non-CV notetype)
    foreign=col.db.list("SELECT c.id FROM cards c JOIN notes n ON c.nid=n.id WHERE c.did=? AND n.mid!=?", vd, cv["id"])
    print(f"foreign cards in Vocab to remove: {len(foreign)}")
    # CV cards to swap in for reuse_rich words
    swap=[]
    for w in reuse_rich:
        nid=col.db.scalar("SELECT id FROM notes WHERE mid=? AND flds LIKE ?",cv["id"],w+SEP+"%")
        if nid:
            cid=col.db.scalar("SELECT id FROM cards WHERE nid=? AND ord=0",nid)
            if cid: swap.append(cid)
    print(f"proper CV cards to swap in (reuse_rich): {len(swap)}")
    if APPLY:
        col.set_deck(foreign, arch)
        col.sched.suspend_cards(foreign)
        if swap:
            col.sched.unsuspend_cards(swap)
            col.set_deck(swap, vd)
        # reposition Vocab forward new cards by frequency
        newcards=col.db.all("SELECT c.id,c.nid FROM cards c WHERE c.did=? AND c.type=0 AND c.ord=0",vd)
        order=[]
        for cid,nid in newcards:
            flds=col.db.scalar("SELECT flds FROM notes WHERE id=?",nid)
            w=re.sub(r"<[^>]+>","",flds.split(SEP)[0]).strip()
            order.append((zipf_frequency(w,"zh") if w else 0.0,cid))
        order.sort(key=lambda x:-x[0])
        col.sched.reposition_new_cards([c for _,c in order],starting_from=1,step_size=1,randomize=False,shift_existing=False)
        # verify: any non-CV cards left in Vocab?
        left=col.db.scalar("SELECT COUNT(*) FROM cards c JOIN notes n ON c.nid=n.id WHERE c.did=? AND n.mid!=?", vd, cv["id"])
        print(f"APPLIED: removed {len(foreign)} foreign, swapped {len(swap)}. Non-CV cards left in Vocab: {left}")
    else:
        print("DRY-RUN (no changes).")
finally:
    col.close()
