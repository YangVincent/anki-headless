#!/usr/bin/env python3
"""Move mined reading-words BELOW the backbone frontier (Zipf < 5.0) out of the Vocab
front-of-queue and into a separate 'Mined' deck (frequency-ordered, own new/day cap),
so the Vocab backbone stays a clean progression. Mined words AT/above 5.0 stay in Vocab
(resort_vocab.py then un-pins them to natural frequency position). Cloze cards (ord2) are
left in Vocab Cloze. Dry-run unless --apply. Run via anki_op.sh."""
import sys, re
from anki.collection import Collection
from wordfreq import zipf_frequency
APPLY = "--apply" in sys.argv
CUTOFF = 5.0
ROOT = "/home/vincent/anki-headless"
def clean(s): return re.sub(r'<[^>]+>', '', s or '').strip()

col = Collection(f"{ROOT}/collection.anki2")
try:
    cv = col.models.by_name("ChineseVocabulary"); SEP = chr(31)
    fi = {f['name']: i for i, f in enumerate(cv['flds'])}
    vd = col.decks.id_for_name("Vocab")
    md = col.decks.id("Mined")                       # create if missing

    # own options group with a modest new/day so you study reading-vocab on demand
    existing = [c for c in col.decks.all_config() if c['name'] == "Mined"]
    conf = existing[0] if existing else col.decks.add_config("Mined")
    conf['new']['perDay'] = 10
    conf['rev']['perDay'] = 200
    col.decks.save(conf)
    deck = col.decks.get(md); deck['conf'] = conf['id']; col.decks.save(deck)

    # mined ord0 cards currently in Vocab, split by frequency
    rows = col.db.all(
        "SELECT c.id, n.flds FROM cards c JOIN notes n ON c.nid=n.id "
        "WHERE c.did=? AND c.ord=0 AND n.mid=? AND n.tags LIKE '%mined%'", vd, cv['id'])
    below = []; stay = 0
    for cid, flds in rows:
        z = zipf_frequency(clean(flds.split(SEP)[fi['Simplified']]), 'zh')
        if z < CUTOFF: below.append((z, cid))
        else: stay += 1
    below.sort(key=lambda x: -x[0])                  # commonest reading-words first
    print(f"mined in Vocab: {len(rows)} | -> Mined deck (Zipf<{CUTOFF}): {len(below)} | stay in Vocab: {stay}")

    if APPLY and below:
        cids = [c for _, c in below]
        col.set_deck(cids, md)
        col.sched.unsuspend_cards(cids)
        due = 1
        for _, cid in below:                         # frequency order within Mined
            card = col.get_card(cid); card.due = due; col.update_card(card); due += 1
        tot = col.db.scalar("SELECT COUNT(*) FROM cards WHERE did=?", md)
        print(f"APPLIED: moved {len(below)} cards to Mined (new/day=10). Mined now {tot} cards.")
    elif not APPLY:
        print("DRY-RUN (use --apply)")
finally:
    col.close()
