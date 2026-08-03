"""Create ChineseVocabulary notes for HSK 3.0 words the decks have no card for.

After the reinstatement and prune, 167 words of the official list still had no card that
could be filed: 165 existed only as legacy "Basic - new hsk 3.0 xiehanzi v3 - *" notes (a
different four-card writing system, deliberately not repurposed) and 8 had nothing at all.
Mostly erhua and spoken forms — 一下儿, 有空儿, 名牌儿, 能不能, 不太 — plus HSK 7-9 vocabulary.

Content comes from freq_data/hsk_missing_cards.json: level and pinyin from the official
list, meaning kept from it where present, example sentence + pinyin + translation written
for this batch.

Deck by band (1-6 -> HSK, 7-9 -> HSK7-9) and tagged HSK::HSKn to match the rest.
Cloze fields are left empty on purpose: Cloze-Recall is gated on SentenceSimplifiedCloze,
so filling it would generate a second card per note that nobody asked for.

Usage: bash freq_data/anki_op.sh hsk-create freq_data/hsk_create_missing.py --apply
"""
import argparse
import json
import re

from anki.collection import Collection
from opencc import OpenCC

ROOT = "/home/vincent/anki-headless"
RANK = {"1": 1, "2": 2, "3": 3, "4": 4, "5": 5, "6": 6, "7-9": 7}


def strip_html(s):
    return re.sub(r"<[^>]+>", "", s or "").replace("&nbsp;", " ").strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=f"{ROOT}/collection.anki2")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    content = {e["word"]: e for e in
               json.load(open(f"{ROOT}/freq_data/hsk_missing_cards.json"))}
    official = {e["word"]: e for e in
                json.load(open(f"{ROOT}/freq_data/hsk30_official.json"))}
    cc = OpenCC("s2tw")
    col = Collection(args.db)
    try:
        cards_before = col.card_count()
        model = col.models.by_name("ChineseVocabulary")
        IX = {f["name"]: i for i, f in enumerate(model["flds"])}
        hsk, hsk79 = col.decks.id_for_name("HSK"), col.decks.id_for_name("HSK7-9")

        present = set()
        for did in (hsk, hsk79):
            for nid, in col.db.all("SELECT DISTINCT nid FROM cards WHERE did=?", did):
                present.add(strip_html(col.get_note(nid).fields[0]))

        made, skipped = [], []
        for word, e in content.items():
            if word in present:
                skipped.append((word, "already in the deck")); continue
            o = official.get(word)
            if not o:
                skipped.append((word, "not in the official list")); continue
            note = col.new_note(model)
            note.fields[IX["Simplified"]] = word
            note.fields[IX["Pinyin"]] = o.get("pinyin", "")
            note.fields[IX["Meaning"]] = e["meaning"]
            note.fields[IX["Traditional"]] = cc.convert(word)
            note.fields[IX["PartOfSpeech"]] = o.get("pos", "")
            simp = e["sentence"].replace(word, f"<b>{word}</b>", 1)
            note.fields[IX["SentenceSimplified"]] = simp
            note.fields[IX["SentenceTraditional"]] = cc.convert(simp)
            note.fields[IX["SentencePinyin"]] = e["pinyin"]
            note.fields[IX["SentenceMeaning"]] = e["english"]
            lvl = o["level"]
            for t in ("chinese", "HSK", f"HSK::HSK{lvl}", "claude"):
                note.add_tag(t)
            did = hsk if RANK[lvl] <= 6 else hsk79
            if args.apply:
                col.add_note(note, did)
            made.append((word, lvl, "HSK" if did == hsk else "HSK7-9"))

        print(f"creating {len(made)} notes; skipped {len(skipped)}")
        for w, why in skipped[:10]:
            print(f"  SKIP {w}: {why}")
        for w, lvl, d in made[:6]:
            print(f"  {w} (HSK {lvl}) -> {d}")

        if args.apply:
            after = col.card_count()
            print(f"\nverify: cards {cards_before} -> {after} (+{after - cards_before}) "
                  f"for {len(made)} notes")
            still = []
            got = set()
            for did in (hsk, hsk79):
                for nid, in col.db.all("SELECT DISTINCT nid FROM cards WHERE did=?", did):
                    got.add(strip_html(col.get_note(nid).fields[0]))
            for w in content:
                if w not in got:
                    still.append(w)
            print(f"verify: batch words still absent from the decks: {len(still)} (want 0)")
            wrongdeck = 0
            for did, ok in ((hsk, lambda l: l <= 6), (hsk79, lambda l: l == 7)):
                for nid, in col.db.all("SELECT DISTINCT nid FROM cards WHERE did=?", did):
                    w = strip_html(col.get_note(nid).fields[0])
                    if w in official and not ok(RANK[official[w]["level"]]):
                        wrongdeck += 1
            print(f"verify: words in the wrong band: {wrongdeck} (want 0)")
        else:
            print("\nDRY-RUN — nothing written.")
    finally:
        col.close()


if __name__ == "__main__":
    main()
