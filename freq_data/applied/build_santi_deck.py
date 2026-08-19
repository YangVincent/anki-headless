"""Create a 三体 reading deck: the words the novel needs that HSK never teaches.

Measured against the trilogy (773k characters). After finishing HSK 1-6 the book still
leaves ~12 opaque words per page — words containing a character Vincent has not met.
Of the 379 it uses ten or more times, 167 are in HSK 7-9 and would be learned anyway;
the other 212 are outside HSK at any level. Those, minus proper nouns and jieba's
numeral+measure fragments, are the 182 here. Learning them roughly halves the stops.

Not a throwaway: 78% of these also appear in Vincent's other books (216 of 379 in
平凡的世界, 209 in 白鹿原), because words like 恐惧, 清晰, 崩溃, 遥远 are ordinary literary
vocabulary the HSK list simply does not reach. Only 84 are 三体-only.

Example sentences are the novel's own wherever one was usable (136 of 182) — authentic
context beats an invented sentence for a book deck, and the sentence is one he will
actually meet. The rest were written because the book's line was too long, a fragment,
or contained Latin/digits that break syllable parity.

Deck is Mined::三体, matching the existing Mined::十日终焉 convention for novel mining.
Cloze fields are left empty so each note makes 2 cards, not 3.

Usage: bash freq_data/anki_op.sh santi-deck freq_data/build_santi_deck.py --apply
"""
import argparse
import json
import re

from anki.collection import Collection
from opencc import OpenCC

ROOT = "/home/vincent/anki-headless"
DECK = "Mined::三体"


def strip_html(s):
    return re.sub(r"<[^>]+>", "", s or "").replace("&nbsp;", " ").strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=f"{ROOT}/collection.anki2")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    cards = json.load(open(f"{ROOT}/freq_data/santi_deck.json"))
    cc = OpenCC("s2tw")
    col = Collection(args.db)
    try:
        before = col.card_count()
        model = col.models.by_name("ChineseVocabulary")
        IX = {f["name"]: i for i, f in enumerate(model["flds"])}
        did = col.decks.id(DECK)          # creates it if absent

        # never duplicate a word he already has a live card for
        live = {d for d, n in col.db.all("SELECT id,name FROM decks") if "Hidden" not in n}
        have = set()
        for sfld, dk, q in col.db.all(
                "SELECT n.sfld,c.did,c.queue FROM cards c JOIN notes n ON n.id=c.nid WHERE c.ord=0"):
            if dk in live and q != -1:
                have.add(strip_html(sfld))

        made, skipped = [], []
        for e in cards:
            w = e["word"]
            if w in have:
                skipped.append((w, "already in a live deck")); continue
            if w not in e["sentence"]:
                skipped.append((w, "word absent from its sentence")); continue
            note = col.new_note(model)
            note.fields[IX["Simplified"]] = w
            note.fields[IX["Pinyin"]] = e["pinyin"]
            note.fields[IX["Meaning"]] = e["meaning"]
            note.fields[IX["Traditional"]] = cc.convert(w)
            simp = e["sentence"].replace(w, f"<b>{w}</b>", 1)
            note.fields[IX["SentenceSimplified"]] = simp
            note.fields[IX["SentenceTraditional"]] = cc.convert(simp)
            note.fields[IX["SentencePinyin"]] = e["sentence_pinyin"]
            note.fields[IX["SentenceMeaning"]] = e["english"]
            for t in ("chinese", "mined", "santi", "claude"):
                note.add_tag(t)
            if e.get("from_book"):
                note.add_tag("santi::book-sentence")
            if args.apply:
                col.add_note(note, did)
            made.append(w)

        print(f"creating {len(made)} notes in {DECK}; skipped {len(skipped)}")
        for w, why in skipped[:15]:
            print(f"  SKIP {w}: {why}")

        if args.apply:
            after = col.card_count()
            print(f"\nverify: cards {before} -> {after} (+{after - before}) for {len(made)} notes")
            n = len(col.decks.cids(col.decks.id_for_name(DECK), children=False))
            print(f"verify: {DECK} now holds {n} cards")
            miss = 0
            for e in cards:
                if e["word"] in have:
                    continue
                if not col.find_notes(f'"deck:{DECK}" "Simplified:{e["word"]}"'):
                    miss += 1
            print(f"verify: intended words missing from the deck: {miss} (want 0)")
        else:
            print("\nDRY-RUN — nothing written.")
    finally:
        col.close()


if __name__ == "__main__":
    main()
