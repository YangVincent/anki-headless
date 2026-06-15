#!/usr/bin/env python3
"""Functional test of the bot's wild-add wiring + frequency lookup.
Creates a throwaway note, promotes it via the REAL bot.promote_to_vocab,
verifies Vocab + mined + front-of-queue + reverse-suspended, then deletes it."""
import sys
sys.path.insert(0, "/home/vincent/anki-headless")
from bot import promote_to_vocab, freq_tier
from anki.collection import Collection

print("=== freq_tier ===")
for w in ["的", "残酷", "央行", "犄角"]:
    print("  ", freq_tier(w))

col = Collection("/home/vincent/anki-headless/collection.anki2")
try:
    cv = next(m for m in col.models.all() if m["name"] == "ChineseVocabulary")
    vd = col.decks.id_for_name("Vocab")
    front_before = col.db.scalar("SELECT MIN(due) FROM cards WHERE did=? AND type=0 AND ord=0", vd)

    note = col.new_note(cv)
    note["Simplified"] = "ZZ测试ZZ"   # clearly fake, won't collide
    note["Meaning"] = "test"
    col.add_note(note, col.decks.id("Knowledge"))
    res = promote_to_vocab(col, [note.id])

    fwd_did, fwd_due, fwd_q = col.db.first(
        "SELECT did,due,queue FROM cards WHERE nid=? AND ord=0", note.id)
    rev_q = col.db.scalar("SELECT queue FROM cards WHERE nid=? AND ord=1", note.id)
    tags = col.get_note(note.id).tags
    print("\n=== promote_to_vocab ===")
    print("  result:", res)
    print(f"  forward: deck={'Vocab' if fwd_did==vd else fwd_did}  due={fwd_due}  queue={fwd_q}")
    print(f"  (front_before={front_before}; due should be below it -> next-up)")
    print(f"  reverse queue={rev_q}  (-1=suspended)")
    print(f"  tags={tags}")
    ok = (fwd_did == vd and fwd_due < (front_before or 1) and rev_q == -1 and "mined" in tags)
    print(f"  RESULT: {'PASS' if ok else 'FAIL'}")

    col.remove_notes([note.id])
    print("  cleaned up throwaway note")
finally:
    col.close()
