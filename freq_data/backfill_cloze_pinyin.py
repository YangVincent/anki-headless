#!/usr/bin/env python3
"""Fill empty SentencePinyin on Vocab Cloze notes.

The Cloze-Recall back shows SentenceSimplified over SentencePinyin, so a note with an
empty SentencePinyin reveals the answer sentence with no reading. 94 notes were left that
way by the July batches that rewrote sentences without regenerating the pinyin.

The readings are hand-written in cloze_sentence_pinyin.json rather than generated.
pypinyin+jieba (fix_sentence_pinyin.build) was tried first and does not match the deck's
existing style: it glues numeral+measure into one token ("Zhèběn", "sānlún" where the deck
writes "Zhè běn", "sān lún"), lowercases proper nouns ("wánglǎoshī"), mis-segments
(这本书写得 -> "shūxiě dé"), and misses neutral tones (得 as a complement marker, 消息,
不好意思). Matching by sentence text keeps this table honest: if a sentence is ever
rewritten again, its entry stops matching and the note is reported instead of mis-filled.

Usage: bash freq_data/anki_op.sh cloze-pinyin freq_data/backfill_cloze_pinyin.py --apply
"""
import argparse
import json
import re

from anki.collection import Collection

ROOT = "/home/vincent/anki-headless"
CLOZE_DID = 1781631612781


def strip_html(s):
    return re.sub(r"<[^>]+>", "", s or "").replace("&nbsp;", " ").strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=f"{ROOT}/collection.anki2")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    table = dict(json.load(open(f"{ROOT}/freq_data/cloze_sentence_pinyin.json")))

    col = Collection(args.db)
    try:
        cv = col.models.by_name("ChineseVocabulary")
        IX = {f["name"]: i for i, f in enumerate(cv["flds"])}
        nids = sorted({col.get_card(c).nid for c in col.decks.cids(CLOZE_DID, children=True)})
        targets = [n for n in nids
                   if not strip_html(col.get_note(n).fields[IX["SentencePinyin"]])]
        print(f"{len(nids)} cloze notes, {len(targets)} with empty SentencePinyin, "
              f"{len(table)} hand-written readings available")

        done, skipped = [], []
        for nid in targets:
            note = col.get_note(nid)
            word = strip_html(note.fields[IX["Simplified"]])
            sent = strip_html(note.fields[IX["SentenceSimplified"]])
            reading = table.get(sent)
            if reading is None:
                skipped.append((word, f"no reading for sentence: {sent!r}")); continue
            # the apostrophe is a syllable separator, not part of the reading, and the
            # Pinyin fields are inconsistent about it (方案 is stored "fāngàn")
            def bare(s):
                return s.replace(" ", "").replace("'", "").lower()

            wp = bare(strip_html(note.fields[IX["Pinyin"]]))
            # tone sandhi is written out, so the word's reading must survive verbatim
            if wp and wp not in bare(reading):
                skipped.append((word, f"word reading {wp!r} absent from {reading!r}")); continue
            if args.apply:
                note.fields[IX["SentencePinyin"]] = reading
                col.update_note(note)
            done.append((word, sent, reading))

        for word, sent, reading in done[:6]:
            print(f"  {word:6} {sent}\n  {'':6} {reading}")
        print(f"\n{len(done)} filled, {len(skipped)} skipped")
        for word, why in skipped:
            print(f"  SKIP {word}: {why}")

        unused = set(table) - {s for _, s, _ in done}
        if unused:
            print(f"\n{len(unused)} table entries matched nothing:")
            for s in sorted(unused):
                print(f"  {s}")

        if args.apply:
            still = [n for n in nids
                     if not strip_html(col.get_note(n).fields[IX["SentencePinyin"]])]
            print(f"\nverify: {len(still)} cloze notes still lack SentencePinyin "
                  f"(expected {len(skipped)})")
        else:
            print("DRY-RUN — nothing written.")
    finally:
        col.close()


if __name__ == "__main__":
    main()
