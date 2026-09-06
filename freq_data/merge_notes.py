#!/usr/bin/env python3
"""Merge a duplicated word's two Main notes into one, then delete the loser.

WHY. The deck's rule is one comprehensive note per character. Seven characters had two
Main notes each: a rich ChineseCharacters note (component mnemonic, Radicals,
CharacterFreq, ColorPinyin, Uses) and a thinner ChineseVocabulary note mined from 水浒传
(CustomFreq badge, PartOfSpeech, cloze fields). Both notes of every pair are suspended,
so nothing in the study queue moves.

The ChineseCharacters note is kept in all seven cases: these are single characters, and
it is the notetype that holds the radical and frequency data a character card needs.
The Vocabulary note's fields are copied across wherever the kept note has none, so the
merge only ever adds.

WHAT THE MERGE COSTS, stated rather than hidden: the dropped note's cards go with it.
肉 and 跳 each carry ONE review on the dropped note (ivl 8 and 6). Those two reviews are
lost. Every other dropped card has reps=0. The ChineseCharacters notetype has no cloze
template, so the Cloze cards of the dropped notes disappear -- all 8,456 cloze cards in
this collection are suspended, so that costs nothing today.

Cloze fields are still written on the kept note. They render nowhere now, but they are
the sentence's data, and a cloze template added later should not have to backfill them.

Usage: bash freq_data/anki_op.sh merge-notes freq_data/merge_notes.py --apply
"""
import argparse
import json
import re
import sys

from anki.collection import Collection
from opencc import OpenCC

ROOT = "/home/vincent/anki-headless"
DEFAULT = f"{ROOT}/freq_data/gen_heian/merges.json"
SENT = ["SentenceSimplified", "SentenceTraditional", "SentenceSimplifiedCloze",
        "SentenceTraditionalCloze", "SentencePinyin", "SentenceMeaning", "SentenceAudio"]


def strip_html(s):
    s = re.sub(r"\[sound:[^\]]*\]", "", s or "")
    return re.sub(r"<[^>]+>", "", s).replace("&nbsp;", " ").strip()


def bare(s):
    return re.sub(r"\s+", "", strip_html(s))


def fields_of(note):
    return {f["name"]: i for i, f in enumerate(note.note_type()["flds"])}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=f"{ROOT}/collection.anki2")
    ap.add_argument("--data", default=DEFAULT)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    data = json.load(open(args.data, encoding="utf-8"))
    cc = OpenCC("s2tw")
    col = Collection(args.db)
    try:
        cards_before = col.card_count()
        notes_before = col.note_count()

        # Refuse to merge anything that is not the shape this was written for: two Main
        # notes, both suspended, same headword. A live card must never be deleted here.
        print("── preflight ──")
        bad = []
        for w, spec in data.items():
            for role in ("keep", "drop"):
                try:
                    n = col.get_note(spec[role])
                except Exception:
                    bad.append((w, f"{role} note {spec[role]} not found")); continue
                if bare(n.fields[fields_of(n)["Simplified"]]) != w:
                    bad.append((w, f"{role} note is not {w}"))
                for cid in col.card_ids_of_note(spec[role]):
                    c = col.get_card(cid)
                    if c.queue != -1:
                        bad.append((w, f"{role} has a LIVE card in {col.decks.name(c.did)}"))
        print(f"  problems: {len(bad)} (want 0)")
        for w, why in bad:
            print(f"    {w}: {why}")
        assert not bad

        print("\n── merging ──")
        for w, spec in data.items():
            keep = col.get_note(spec["keep"])
            drop = col.get_note(spec["drop"])
            K, D = fields_of(keep), fields_of(drop)
            print(f"\n  {w}   keep {spec['keep']} <- drop {spec['drop']}")
            print(f"    why: {spec['why']}")

            # 1. anything the dropped note has and the kept note lacks
            added = []
            for name, di in D.items():
                if name in SENT or name not in K:
                    continue
                if strip_html(drop.fields[di]) and not strip_html(keep.fields[K[name]]):
                    keep.fields[K[name]] = drop.fields[di]
                    added.append(name)
            if added:
                print(f"    carried across: {', '.join(added)}")

            # 2. the sentence, from whichever note was judged to have the better one
            src = drop if spec["sentence_from"] == "drop" else keep
            S = D if spec["sentence_from"] == "drop" else K
            sent = strip_html(src.fields[S["SentenceSimplified"]])
            for name in ("SentencePinyin", "SentenceMeaning", "SentenceAudio"):
                if name in S and name in K:
                    keep.fields[K[name]] = src.fields[S[name]]
            simp = sent.replace(w, f"<b>{w}</b>")
            keep.fields[K["SentenceSimplified"]] = simp
            keep.fields[K["SentenceTraditional"]] = cc.convert(simp)
            if "SentenceSimplifiedCloze" in K:
                keep.fields[K["SentenceSimplifiedCloze"]] = sent.replace(w, "[ ]")
                keep.fields[K["SentenceTraditionalCloze"]] = cc.convert(sent).replace(
                    cc.convert(w), "[ ]")
            print(f"    sentence ({spec['sentence_from']}): {sent}")

            # 3. gloss
            old = strip_html(keep.fields[K["Meaning"]])
            keep.fields[K["Meaning"]] = spec["meaning"]
            print(f"    meaning: {old!r} -> {spec['meaning']!r}")

            # 4. tags: union, so the provenance of the dropped note survives it
            new_tags = sorted(set(keep.tags) | set(drop.tags))
            if new_tags != sorted(keep.tags):
                print(f"    tags: {' '.join(keep.tags)} -> {' '.join(new_tags)}")
            keep.tags = new_tags

            if args.apply:
                col.update_note(keep)
                col.remove_notes([spec["drop"]])

        if not args.apply:
            print("\nDRY-RUN — nothing written.")
            return

        print("\n── verify ──")
        bad = []
        for w, spec in data.items():
            try:
                col.get_note(spec["drop"])
                bad.append((w, "dropped note still exists"))
            except Exception:
                pass
            k = col.get_note(spec["keep"])
            K = fields_of(k)
            if strip_html(k.fields[K["Meaning"]]) != spec["meaning"]:
                bad.append((w, "meaning did not take"))
            s = bare(k.fields[K["SentenceSimplified"]])
            if w not in s:
                bad.append((w, "sentence lost its word"))
            if "SentenceSimplifiedCloze" in K:
                cz = bare(k.fields[K["SentenceSimplifiedCloze"]])
                if w in cz:
                    bad.append((w, "cloze shows the answer"))
            # exactly one Main note for this word now
            n = len(col.find_notes(f'deck:Main "Simplified:{w}"'))
            if n != 1:
                bad.append((w, f"{n} Main notes remain"))
        print(f"  problems: {len(bad)} (want 0)")
        for w, why in bad:
            print(f"    {w}: {why}")
        print(f"  notes {notes_before} -> {col.note_count()} (-{notes_before - col.note_count()})")
        print(f"  cards {cards_before} -> {col.card_count()} (-{cards_before - col.card_count()})")
        assert not bad
        print("APPLIED")
    finally:
        col.close()


if __name__ == "__main__":
    main()
