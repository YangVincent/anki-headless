#!/usr/bin/env python3
"""Rescue what is worth keeping from the non-HSK deck, then delete the rest.

WHAT non-HSK IS. Whatever did not match the official HSK list when the collection was
sorted. 9,940 cards, 155 of them ever reviewed. It is a leftovers pile: single characters
(邦, 怖, 署), phrase fragments (大家好, 这就, 有可能), proper nouns (东京, 欧元), dates
(五月), and 5,941 words below zipf 4.0.

RESCUED, both verified against hsk30_official.json:
   81 chengyu  -> Mined. NONE is on the official list, and chengyu are 3.8% of what
                  Vincent actually reads while the HSK queue contains none.
  121 official -> HSK. All 121 are on the list and 115 carry a level tag that MATCHES
                  it; only the deck was wrong. They were created 2026-06, after
                  hsk_split_by_level.py had already run, so it never saw them.

DELETED: the remaining 9,307 notes. This also removes their Cloze, Reverse and Archive
siblings -- 27,721 cards in total, every one outside non-HSK already suspended. Vincent
chose deletion over suspension on 2026-09-01, having been shown that figure and the fact
that 151 of the notes carry review history.

Deletion is irreversible; anki_op.sh takes a backup first. Dry-run unless --apply.
"""
import argparse
import json

from anki.collection import Collection

COL = "/home/vincent/anki-headless/collection.anki2"
OFFICIAL = "/home/vincent/anki-headless/freq_data/hsk30_official.json"
SRC, HSK, CHENGYU_HOME = "non-HSK", "HSK", "Mined"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    official = {x["word"] for x in json.load(open(OFFICIAL, encoding="utf-8"))}
    col = Collection(COL)
    try:
        src = col.decks.id_for_name(SRC)
        hsk = col.decks.id_for_name(HSK)
        ch = col.decks.id_for_name(CHENGYU_HOME)
        assert src and hsk and ch
        cv = col.models.by_name("ChineseVocabulary")
        si = [f["name"] for f in cv["flds"]].index("Simplified")

        to_hsk, to_ch, to_drop = [], [], []
        for nid in col.models.nids(cv["id"]):
            row = col.db.first("SELECT id FROM cards WHERE nid=? AND ord=0 AND did=?",
                               nid, src)
            if not row:
                continue
            n = col.get_note(nid)
            w = n.fields[si].strip()
            if w in official:
                to_hsk.append(row[0])
            elif "type::Chengyu" in n.tags:
                to_ch.append(row[0])
            else:
                to_drop.append(nid)

        cards = 0
        for nid in to_drop:
            cards += col.db.scalar("SELECT count(*) FROM cards WHERE nid=?", nid)
        # nothing studied may be caught: assert, do not assume
        caught = col.db.scalar(
            f"SELECT count(*) FROM cards WHERE nid IN ({','.join('?'*len(to_drop))}) "
            f"AND did IN (?,?,?)", *to_drop, hsk, ch,
            col.decks.id_for_name("Stella An")) if to_drop else 0
        print(f"rescue -> {HSK}: {len(to_hsk)}   rescue -> {CHENGYU_HOME}: {len(to_ch)}")
        print(f"delete: {len(to_drop)} notes / {cards} cards")
        print(f"cards of the delete set sitting in a studied deck: {caught}")
        assert caught == 0, "refusing: a note being deleted has a studied card"

        if not args.apply:
            print("\nDRY-RUN (pass --apply)")
            return

        col.set_deck(to_hsk, hsk)
        col.set_deck(to_ch, ch)
        col.sched.unsuspend_cards(to_ch)          # chengyu should be studiable
        lo = col.db.scalar(
            "SELECT MIN(due) FROM cards WHERE did=? AND type=0 AND ord=0", ch) or 1
        pos = lo - len(to_ch)
        for cid in to_ch:
            c = col.get_card(cid)
            if c.type == 0:
                c.due = pos
                col.update_card(c)
            pos += 1

        col.remove_notes(to_drop)

        left = col.db.scalar("SELECT count(*) FROM cards WHERE did=?", src)
        gone = col.db.scalar(
            f"SELECT count(*) FROM notes WHERE id IN ({','.join('?'*len(to_drop))})",
            *to_drop)
        live_ch = col.db.scalar(
            "SELECT count(*) FROM cards WHERE did=? AND queue>=0 AND ord=0", ch)
        print(f"\n{SRC} now holds {left} cards (expect 0)")
        print(f"deleted notes still present: {gone} (expect 0)")
        print(f"{CHENGYU_HOME} unsuspended forward cards: {live_ch}")
        assert left == 0 and gone == 0
        print("APPLIED")
    finally:
        col.close()


if __name__ == "__main__":
    main()
