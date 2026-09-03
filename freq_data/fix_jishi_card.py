#!/usr/bin/env python3
"""Repair the 既是 card: one gloss covering two constructions, and three empty fields.

WHAT WAS WRONG, and why each is a defect rather than a preference:

  * The Meaning field carried CC-CEDICT's raw output, "is both ...(and...) / since / as".
    Slash-separated senses are not this collection's format -- 既然 reads "since; given
    that; now that" and 鉴于 reads "in light of; in view of; seeing that". Same field,
    same word class, different convention.
  * It also merges TWO constructions. 既是⋯亦是 is the correlative "both … and"; 既是 at
    the head of a clause is causal, "since it is the case that". They behave differently
    and the card's only sentence shows the first, so the causal sense -- the one met in
    formal writing -- is unrecognisable from this card.
  * SentenceTraditional was empty while Traditional was filled. It renders on the
    Cloze-Recall template.
  * Both cloze fields were empty, so no cloze card could ever generate.

PartOfSpeech stays empty. 既是 is not in hsk30_official.json, and the collection renders
the same official tag three different ways, so any value here would be invented.

Usage: bash freq_data/anki_op.sh fix-jishi freq_data/fix_jishi_card.py --apply
"""
import argparse
import re
import sys
from pathlib import Path

ROOT = Path("/home/vincent/anki-headless")
sys.path.insert(0, str(ROOT))

import anki.collection  # noqa: E402,F401
from anki.collection import Collection  # noqa: E402

WORD = "既是"
MEANING = "since; given that; also 既是…也是 both … and …"
#: The mined sentence was 傀儡既是他的铠甲亦是他的武器 -- 铠甲 sits at zipf 3.4 and Vincent
#: knew 1 of its 3 content words. It also showed the CORRELATIVE sense while the gloss
#: leads with the causal one, so the card's only example contradicted its own headline.
#: This replacement uses nothing below zipf 3.5 and shows the 既是⋯就⋯ frame the causal
#: sense actually takes. The correlative moves to Notes, with its own simple example.
SENTENCE = "既是你自己选的，就别后悔。"
SENT_EN = "Since you chose it yourself, do not regret it."
NOTES = ("Causal 既是 heads a clause and pairs with 就; 既然 is interchangeable there. "
         "Correlative 既是…也是 means both A and B: 手机既是电话，也是相机 — a phone is "
         "both a telephone and a camera.")


def strip_html(s):
    return re.sub(r"<[^>]+>", "", s or "").replace("&nbsp;", " ").strip()


def main():
    from opencc import OpenCC
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(ROOT / "collection.anki2"))
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    cc = OpenCC("s2tw")

    col = Collection(args.db)
    try:
        nids = [n for n in col.find_notes(f'"Simplified:{WORD}"')
                if col.get_note(n).note_type()["name"] == "ChineseVocabulary"]
        if not nids:
            sys.exit(f"no ChineseVocabulary note for {WORD!r}")
        note = col.get_note(nids[0])
        IX = {f["name"]: i for i, f in enumerate(note.note_type()["flds"])}
        plain = SENTENCE
        sent = plain.replace(WORD, f"<b>{WORD}</b>", 1)
        assert WORD in plain, "the target word must appear in its own sentence"

        new = {
            "Meaning": MEANING,
            "Notes": NOTES,
            "SentenceSimplified": sent,
            "SentenceMeaning": SENT_EN,
            "SentencePinyin": " ".join(
                x[0] for x in __import__("pypinyin").pinyin(plain, style=__import__("pypinyin").Style.TONE)),
            "SentenceTraditional": cc.convert(sent),
            "SentenceSimplifiedCloze": plain.replace(WORD, "[ ]", 1),
            "SentenceTraditionalCloze": cc.convert(plain).replace(cc.convert(WORD), "[ ]", 1),
        }
        for k, v in new.items():
            before = strip_html(note.fields[IX[k]])
            print(f"  {k:<26}{(before or '(empty)')[:44]}")
            print(f"  {'':<26}-> {strip_html(v)[:70]}")
        if not args.apply:
            print("\n(dry run; nothing written)")
            return

        for k, v in new.items():
            note.fields[IX[k]] = v
        col.update_note(note)

        after = col.get_note(nids[0])
        print("\nverify:")
        for k in ("Meaning", "Notes", "SentenceSimplified", "SentenceTraditional",
                  "SentenceSimplifiedCloze", "PartOfSpeech"):
            v = strip_html(after.fields[IX[k]])
            print(f"  {k:<26}{v[:64] if v else '(empty, on purpose)' if k=='PartOfSpeech' else '(EMPTY)'}")
        assert WORD not in strip_html(after.fields[IX["SentenceSimplifiedCloze"]]), \
            "the cloze still shows the answer"
        print("  cloze hides the answer: yes")
    finally:
        col.close()


if __name__ == "__main__":
    main()
