#!/usr/bin/env python3
"""Build the parallel cloze deck.
 1. Add a 3rd card template 'Cloze-Recall' (ord 2) to ChineseVocabulary:
       front = blanked sentence (only generates when SentenceSimplifiedCloze non-empty)
       back  = word + pinyin + meaning + full bold sentence + english
 2. Route the new ord-2 cards: Vocab-linked notes -> new 'Vocab Cloze' deck; Archive ones -> delete.
 3. Suspend ALL cloze cards (the daily gate unsuspends mature words).
 4. due = the word's frequency rank (copied from its ord-0 card) so the deck is frequency-sorted.
 5. Give 'Vocab Cloze' its own options group with a low new/day cap.
Dry-run unless --apply. Run via anki_op.sh. Schema change -> a full upload sync is required after."""
import sys, time, re
from anki.collection import Collection
APPLY = "--apply" in sys.argv
ROOT = "/home/vincent/anki-headless"

QFMT = """{{#SentenceSimplifiedCloze}}
<div class=title>Read the sentence. What word fills the blank? Say it.</div>
<div class=chinese>{{SentenceSimplifiedCloze}}</div>
{{/SentenceSimplifiedCloze}}"""

AFMT = """{{FrontSide}}

<div class=backbg>
<center>
<div class=chinese>{{Simplified}}{{#Traditional}}　/　{{Traditional}}{{/Traditional}}</div>
<div class=reading>{{Pinyin}}{{Audio}}</div>
<div class=wordtype>{{Meaning}}</div>
</center>

<div class=chinese>{{SentenceSimplified}}{{#SentenceAudio}}{{SentenceAudio}}{{/SentenceAudio}}</div>
<div class=personal>{{#SentencePinyin}}{{SentencePinyin}}{{/SentencePinyin}}</div>
<div class=personal>{{#SentenceMeaning}}{{SentenceMeaning}}{{/SentenceMeaning}}</div>
</div>"""

col = Collection(f"{ROOT}/collection.anki2")
try:
    cv = col.models.by_name("ChineseVocabulary")
    SEP = chr(31)
    vd = col.decks.id_for_name("Vocab")
    existing = [t['name'] for t in cv['tmpls']]
    print("existing templates:", existing)
    if "Cloze-Recall" in existing:
        print("Cloze-Recall template already present -> not re-adding.")
    else:
        print(f"will ADD template 'Cloze-Recall' (ord {len(cv['tmpls'])})")

    # note sets
    vocab_nids = set(col.db.list(
        "SELECT n.id FROM cards c JOIN notes n ON c.nid=n.id WHERE c.did=? AND c.ord=0 AND n.mid=?", vd, cv['id']))
    # ord0 due (frequency rank) per Vocab note
    ord0_due = dict(col.db.all(
        "SELECT n.id, c.due FROM cards c JOIN notes n ON c.nid=n.id WHERE c.did=? AND c.ord=0 AND n.mid=?", vd, cv['id']))
    print(f"Vocab ord-0 notes: {len(vocab_nids)}")

    if not APPLY:
        print("DRY-RUN: would add template, generate cloze cards (~12,834), route 12,458 to 'Vocab Cloze', "
              "delete 376 archive ones, suspend all, set freq-order due, cap new/day.")
        sys.exit(0)

    # 1) add template
    if "Cloze-Recall" not in existing:
        t = col.models.new_template("Cloze-Recall")
        t['qfmt'] = QFMT
        t['afmt'] = AFMT
        col.models.add_template(cv, t)
        col.models.update_dict(cv)   # generates missing cards
        print("template added + cards generated")

    cv = col.models.by_name("ChineseVocabulary")
    cloze_ord = next(t['ord'] for t in cv['tmpls'] if t['name'] == "Cloze-Recall")

    # all freshly generated cloze cards
    all_cloze = col.db.all(f"SELECT id, nid FROM cards WHERE ord=? AND nid IN (SELECT id FROM notes WHERE mid=?)",
                           cloze_ord, cv['id'])
    vocab_cids = [cid for cid, nid in all_cloze if nid in vocab_nids]
    archive_cids = [cid for cid, nid in all_cloze if nid not in vocab_nids]
    print(f"generated cloze cards: {len(all_cloze)}  (vocab {len(vocab_cids)}, archive {len(archive_cids)})")

    # 2) create Vocab Cloze deck + its own options group (low new/day)
    cloze_did = col.decks.id("Vocab Cloze")
    deck = col.decks.get(cloze_did)
    conf = col.decks.add_config("Vocab Cloze")
    conf['new']['perDay'] = 10
    conf['rev']['perDay'] = 200
    col.decks.save(conf)
    deck['conf'] = conf['id']
    col.decks.save(deck)
    col.set_deck(vocab_cids, cloze_did)
    print(f"routed {len(vocab_cids)} cloze cards to 'Vocab Cloze' (new/day=10)")

    # delete archive-only cloze cards (notes keep ord0/ord1 -> not orphaned)
    if archive_cids:
        col.remove_cards_and_orphaned_notes(archive_cids)
        print(f"deleted {len(archive_cids)} archive cloze cards")

    # 3) suspend all vocab cloze cards
    col.sched.suspend_cards(vocab_cids)
    # 4) due = ord0 frequency rank
    for cid, nid in [(c, n) for c, n in all_cloze if n in vocab_nids]:
        d = ord0_due.get(nid)
        if d is not None:
            col.db.execute("UPDATE cards SET due=?, usn=-1 WHERE id=?", int(d), cid)
    col.save()
    susp = col.db.scalar("SELECT COUNT(*) FROM cards WHERE did=? AND queue=-1", cloze_did)
    tot = col.db.scalar("SELECT COUNT(*) FROM cards WHERE did=?", cloze_did)
    print(f"Vocab Cloze: {tot} cards, {susp} suspended (frequency-ordered, awaiting maturity gate)")
    print("APPLIED.  NOTE: schema changed -> run a FULL UPLOAD sync next.")
finally:
    col.close()
