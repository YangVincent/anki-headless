#!/usr/bin/env python3
"""Replace the junk example sentences on HSK notes that never had pinyin.

723 HSK notes carried a "sentence" that was never a sentence: raw mined subtitle lines
(鸣人 别灰心), a literal SSA timestamp row for 璃, a comma-separated character list for 矛,
or just the word itself (结账 -> 结账吧). 617 of them had no ending punctuation and 700 had
no English either — they were dumped into the sentence field and never finished, which is
why the pinyin was missing: nothing ever generated it.

Each note gets a written example sentence, its pinyin, and an English translation from
hsk_sentences.json. Fields are written in the deck's existing shape: the target word
<b>-wrapped in the simplified and traditional sentences.

Deliberately NOT touched:
  - SentenceSimplifiedCloze / SentenceTraditionalCloze. These are empty on these notes, and
    Cloze-Recall is gated on the simplified one — filling it would generate hundreds of new
    cloze cards nobody asked for. The card count is asserted unchanged.
  - SentenceAudio. Two notes have audio that voices the old sentence and will now disagree
    with the text; left alone by request.

Usage: bash freq_data/anki_op.sh hsk-sentences freq_data/apply_hsk_sentences.py --apply
"""
import argparse
import sys

sys.path.insert(0, "/home/vincent/anki-headless")
import decks  # noqa: E402
import json
import re

from anki.collection import Collection
from opencc import OpenCC

ROOT = "/home/vincent/anki-headless"


def strip_html(s):
    return re.sub(r"<[^>]+>", "", s or "").replace("&nbsp;", " ").strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=f"{ROOT}/collection.anki2")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--entries", default="hsk_sentences.json",
                    help="authored sentences, relative to freq_data/")
    # Resolved from the registry, not spelled here. The literal "HSK" outlived the deck
    # by a day when it became `Main`, and a stale default verifies nothing while looking
    # like it verified everything.
    ap.add_argument("--deck", default=decks.RECOGNITION_DECKS[0],
                    help="deck checked by the final verification")
    args = ap.parse_args()

    entries = json.load(open(f"{ROOT}/freq_data/{args.entries}"))
    cc = OpenCC("s2tw")  # s2t picks 喫/爲/裏, which this deck does not use
    col = Collection(args.db)
    try:
        cards_before = col.card_count()
        done, skipped = [], []
        for e in entries:
            nid, sent, py, en = e["nid"], e["sentence"], e["pinyin"], e["english"]
            try:
                note = col.get_note(nid)
            except Exception:
                skipped.append((nid, "note not found")); continue
            IX = {f["name"]: i for i, f in enumerate(note.note_type()["flds"])}
            if "SentencePinyin" not in IX:
                skipped.append((nid, "unexpected note type")); continue
            word = strip_html(note.fields[IX["Simplified"]])
            if word not in sent:
                skipped.append((nid, f"{word} absent from authored sentence")); continue
            # only rewrite notes that are still in the state this was built for
            if strip_html(note.fields[IX["SentencePinyin"]]):
                skipped.append((nid, "already has sentence pinyin")); continue

            simp = sent.replace(word, f"<b>{word}</b>", 1)
            note.fields[IX["SentenceSimplified"]] = simp
            note.fields[IX["SentenceTraditional"]] = cc.convert(simp)
            note.fields[IX["SentencePinyin"]] = py
            note.fields[IX["SentenceMeaning"]] = en
            if args.apply:
                col.update_note(note)
            done.append((word, sent, py))

        for w, s, p in done[:6]:
            print(f"  {w:6} {s}\n  {'':6} {p}")
        print(f"\n{len(done)} notes rewritten, {len(skipped)} skipped")
        for nid, why in skipped[:20]:
            print(f"  SKIP {nid}: {why}")

        if args.apply:
            cards_after = col.card_count()
            print(f"\nverify: cards {cards_before} -> {cards_after} "
                  f"({'OK, none created' if cards_after == cards_before else 'CARDS CHANGED'})")
            still = 0
            for cid in col.decks.cids(col.decks.id_for_name(args.deck), children=True):
                n = col.get_note(col.get_card(cid).nid)
                IX = {f["name"]: i for i, f in enumerate(n.note_type()["flds"])}
                if "SentencePinyin" not in IX:
                    continue
                if strip_html(n.fields[IX["SentenceSimplified"]]) and \
                        not strip_html(n.fields[IX["SentencePinyin"]]):
                    still += 1
            print(f"verify: {args.deck} notes with a sentence but no pinyin: {still} (want 0)")
        else:
            print("DRY-RUN — nothing written.")
    finally:
        col.close()


if __name__ == "__main__":
    main()
