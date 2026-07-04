#!/usr/bin/env python3
"""Daily gate for the parallel cloze deck: unsuspend the 'Vocab Cloze' card for any
word whose Vocab recognition card (ord 0) has become MATURE (review, interval >= 21d).
Idempotent — only flips suspended->unsuspended, never the reverse. Dry-run unless --apply.
Run via anki_op.sh (so it backs up + coordinates with the bot)."""
import sys, time
from anki.collection import Collection
APPLY = "--apply" in sys.argv
ROOT = "/home/vincent/anki-headless"
MATURE_IVL = 21

col = None
for _ in range(30):
    try: col = Collection(f"{ROOT}/collection.anki2"); break
    except Exception: time.sleep(2)
if col is None: print("collection locked"); sys.exit(1)
try:
    cv = col.models.by_name("ChineseVocabulary")
    vd = col.decks.id_for_name("Vocab")
    mdid = col.decks.id_for_name("Mined")     # mined reading-words live here now
    cd = col.decks.id_for_name("Vocab Cloze")
    if cd is None: print("no 'Vocab Cloze' deck yet — run cloze_build.py first"); sys.exit(0)
    cloze_ord = next((t['ord'] for t in cv['tmpls'] if t['name'] == "Cloze-Recall"), None)
    if cloze_ord is None: print("no Cloze-Recall template"); sys.exit(0)

    # notes whose ord-0 recognition card is mature — in Vocab OR the Mined deck
    decks = [d for d in (vd, mdid) if d is not None]
    ph = ",".join("?" * len(decks))
    mature_nids = set(col.db.list(
        f"SELECT n.id FROM cards c JOIN notes n ON c.nid=n.id "
        f"WHERE c.did IN ({ph}) AND c.ord=0 AND n.mid=? AND c.type=2 AND c.ivl>=?",
        *decks, cv['id'], MATURE_IVL))
    # their cloze cards that are currently suspended
    to_unsuspend = col.db.list(
        f"SELECT c.id FROM cards c WHERE c.did=? AND c.ord=? AND c.queue=-1 AND c.nid IN "
        f"(SELECT id FROM notes WHERE mid=?)", cd, cloze_ord, cv['id'])
    # filter to mature
    to_unsuspend = [cid for cid in to_unsuspend
                    if col.db.scalar("SELECT nid FROM cards WHERE id=?", cid) in mature_nids]

    susp_now = col.db.scalar("SELECT COUNT(*) FROM cards WHERE did=? AND queue=-1", cd)
    live_now = col.db.scalar("SELECT COUNT(*) FROM cards WHERE did=? AND queue!=-1", cd)
    print(f"Vocab mature words: {len(mature_nids)} | Vocab Cloze: {live_now} live, {susp_now} suspended")
    print(f"to unsuspend this run: {len(to_unsuspend)}")
    if APPLY and to_unsuspend:
        col.sched.unsuspend_cards(to_unsuspend)
        col.save()
        print(f"APPLIED: unsuspended {len(to_unsuspend)} cloze cards")
    elif not APPLY:
        print("DRY-RUN (use --apply)")
finally:
    col.close()
