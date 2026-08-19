#!/usr/bin/env python3
"""Suspend single-character cards, by one of three selection rules.

park_bound_chars.py only ever parked cards that had never been shown, and only those below a
standalone-frequency threshold. This script covers the rest of the space. Each mode carries
its OWN tag, so every batch undoes independently and none of them disturbs
parked::bound-character.

  (default)        studied single-character cards — the ones in daily rotation
  --unseen         never-shown ones below --threshold standalone zipf frequency
  --not-hsk-word   any single character absent from the HSK 3.0 WORD list

The last is the most defensible rule and the one to prefer. HSK publishes a word list and a
separate character list: a character in the WORD list (害 lvl5, 手 lvl1, 怕 lvl2) is meant to
be known standalone, while one appearing only in the character list (嗽, 羞, 乒) is a building
block that never occurs alone. That is a judgement about the language from the curriculum,
rather than a frequency proxy — corpus counts answer "how often does he meet it", which is a
different question from "is this a word".

What this does and does not touch:
  * suspend, not delete. Interval, ease, due date, reps and lapses are all preserved;
    unsuspending puts each card back exactly where it was.
  * a card whose due date passes while parked comes back due immediately — a long park
    means a pile-up on --undo. That is the one real cost of reversing this.
  * Hidden::* decks are skipped unless --include-hidden; they are not studied, and
    Hidden::Archive is the staging area novel_deck_apply.py draws from.

  park_studied_chars.py --not-hsk-word                 # dry run
  park_studied_chars.py --not-hsk-word --apply         # via freq_data/anki_op.sh
  park_studied_chars.py --not-hsk-word --undo --apply  # put that batch back
"""
import argparse
import json
import re
from collections import Counter
from pathlib import Path
from anki_common import sync as _sync

ROOT = Path("/home/vincent/anki-headless")
COL = ROOT / "collection.anki2"
TAG = "parked::studied-character"
# --unseen parks the never-shown remainder that park_bound_chars.py left behind (it kept
# any character whose standalone frequency was >= its threshold, i.e. "this is a real
# word"). Separate tag so each batch undoes independently.
TAG_UNSEEN = "parked::unseen-character"
# --not-hsk-word parks characters HSK 3.0 does not teach as words. HSK publishes a word list
# and a character list; a character in the WORD list (害, 手, 怕) is meant to be known
# standalone, one only in the character list (嗽, 羞, 乒) is a building block that never
# occurs alone. That is a curriculum judgement about the language, not a frequency proxy.
TAG_NOT_HSK = "parked::not-hsk-word"
HSK_TSV = Path("/home/vincent/chinese-projects/dong-chinese/server/app/data/hsk30.tsv")
HANZI = re.compile(r"^[一-鿿]$")


def hsk_words():
    """Every entry in the HSK 3.0 vocabulary list (word -> level)."""
    out = {}
    for line in HSK_TSV.open(encoding="utf-8"):
        w, _, lv = line.rstrip("\n").partition("\t")
        lv = lv.split("\t")[-1] if "\t" in lv else lv
        if lv.isdigit():
            out[w] = int(lv)
    return out



def _deck_names(col):
    return {r[0]: r[1].replace("\x1f", "::") for r in col.db.all("select id, name from decks")}


def main():
    from anki.collection import Collection

    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--undo", action="store_true", help="unsuspend everything tagged")
    ap.add_argument("--unseen", action="store_true",
                    help="park the NEVER-SHOWN single-character cards instead of the studied "
                         "ones (the remainder park_bound_chars.py kept as 'real words')")
    ap.add_argument("--not-hsk-word", action="store_true", dest="not_hsk_word",
                    help="park every active single-character card whose character is NOT in "
                         "the HSK 3.0 word list — i.e. the curriculum never teaches it as a "
                         "word. Applies to studied and never-shown cards alike.")
    ap.add_argument("--threshold", type=float, default=4.0,
                    help="--unseen only: keep characters whose standalone zipf frequency is at "
                         "or above this (default 4.0, same test park_bound_chars.py used). "
                         "Pass 99 to park every single-character card regardless.")
    ap.add_argument("--deck", help="restrict to one deck (default: every studied deck)")
    ap.add_argument("--include-hidden", action="store_true",
                    help="also park Hidden::* decks — off by default: they are not studied, "
                         "so parking them changes nothing you see, and Hidden::Archive is the "
                         "staging area novel_deck_apply.py draws from")
    ap.add_argument("--col", default=str(COL))
    a = ap.parse_args()
    if a.apply and a.col != str(COL):
        raise SystemExit("--apply only ever writes the real collection")

    tag = TAG_NOT_HSK if a.not_hsk_word else TAG_UNSEEN if a.unseen else TAG
    col = Collection(a.col)
    try:
        if a.undo:
            ids = col.find_cards(f'tag:"{tag}"')
            print(f"{len(ids)} cards tagged {tag}")
            if a.apply:
                col.sched.unsuspend_cards(ids)
                for nid in col.find_notes(f'tag:"{tag}"'):
                    note = col.get_note(nid)
                    note.remove_tag(tag)
                    col.update_note(note)
                print("unsuspended and untagged.")
                _sync(col)
            else:
                print("(dry run)")
            return

        decks = _deck_names(col)
        # queue >= 0 is unsuspended/unburied; reps > 0 means it has been shown at least once.
        try:
            from wordfreq import zipf_frequency
            _zipf = lambda ch: zipf_frequency(ch, "zh")
        except ImportError:
            _zipf = lambda ch: 0.0

        kept = 0
        HSKW = hsk_words() if a.not_hsk_word else {}
        if a.not_hsk_word:
            reps_clause = "1=1"                      # studied and never-shown alike
        else:
            reps_clause = "c.reps = 0" if a.unseen else "c.reps > 0"
        rows = col.db.all(
            "select c.id, c.did, n.sfld, c.reps from cards c join notes n on n.id = c.nid "
            f"where c.queue >= 0 and {reps_clause}")
        target, by_deck, chars, unseen_in_target = [], Counter(), [], 0
        for cid, did, sfld, reps in rows:
            ch = str(sfld or "").strip()
            if not HANZI.match(ch):
                continue
            name = decks.get(did, f"deck:{did}")
            if a.deck and not name.startswith(a.deck):
                continue
            if not a.include_hidden and name.startswith("Hidden::"):
                continue
            if a.not_hsk_word:
                if ch in HSKW:
                    kept += 1                 # HSK teaches it as a word — leave it in the queue
                    continue
            elif a.unseen and _zipf(ch) >= a.threshold:
                kept += 1                     # a real standalone word — leave it in the queue
                continue
            target.append(cid)
            by_deck[name] += 1
            chars.append(ch)
            if reps == 0:
                unseen_in_target += 1

        new_before = len(col.find_cards("is:new -is:suspended"))
        active_before = len(col.find_cards("-is:suspended"))

        kind = ("not-an-HSK-word" if a.not_hsk_word
                else "never-shown" if a.unseen else "studied")
        print(f"{len(target)} {kind} single-character cards to park")
        for d, n in by_deck.most_common():
            print(f"    {n:>4}  {d}")

        # Show what is being swept up, by standalone-word frequency.
        if a.not_hsk_word:
            print(f"    {kept} left in the queue — HSK teaches these as words")
            print("\n  parking (character: not in the HSK 3.0 word list):")
            for i in range(0, len(sorted(set(chars))), 32):
                print("    " + " ".join(sorted(set(chars))[i:i + 32]))
        elif a.unseen:
            print(f"    {kept} left in the queue — real standalone words "
                  f"(zipf >= {a.threshold})")
        if chars and not a.not_hsk_word:
            ranked = sorted({c: _zipf(c) for c in chars}.items(), key=lambda kv: -kv[1])
            over = [c for c, z in ranked if z >= 4.0]
            if over:
                print(f"\n  WARNING: {len(over)} of {len(set(chars))} distinct characters are "
                      f"common standalone words being parked anyway:")
                print("    " + " ".join(over[:40]))

        if not a.apply:
            print("\n(dry run — nothing written)")
            return

        col.sched.suspend_cards(target)
        for nid in {col.get_card(cid).nid for cid in target}:
            note = col.get_note(nid)
            note.add_tag(tag)
            col.update_note(note)

        new_after = len(col.find_cards("is:new -is:suspended"))
        active_after = len(col.find_cards("-is:suspended"))
        # the new queue shrinks by exactly the never-shown cards in the batch — 0 for the
        # studied mode, all of them for --unseen, a mix for --not-hsk-word
        assert new_before - new_after == unseen_in_target, \
            f"expected {unseen_in_target} fewer new cards, got {new_before - new_after}"
        assert active_before - active_after == len(target), \
            f"expected {len(target)} fewer active cards, got {active_before - active_after}"
        print(f"\nparked {len(target)} cards. active: {active_before} -> {active_after}, "
              f"new queue untouched at {new_after} ✓")
        print(f"reversible with: park_studied_chars.py --undo --apply   (tag {TAG})")
        _sync(col)
    finally:
        col.close()


if __name__ == "__main__":
    main()
