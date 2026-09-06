#!/usr/bin/env python3
"""Write the Notes field (and optionally a replacement sentence) from a reviewed file.

WHY NOTES MATTER HERE. 332 notes in the book set have an empty Notes field, and the gap
bites hardest where several words share one English gloss. 疲倦, 疲劳 and 疲惫 sit at queue
positions 5522, 5523 and 5524 -- three consecutive days -- and all three glossed as
"tired", with nothing on any card to separate them. 累 and 困 both carry a note; these did
not. 厌倦 is worse than a synonym: it shares the character 倦 but is not physical tiredness
at all, so the shared character actively misleads.

The Notes field renders on the BACK of the Main and Reverse cards, between the
part-of-speech line and the example sentence, wrapped in {{#Notes}}...{{/Notes}} so an
empty one shows nothing. It is not on the Cloze card.

Format follows what the deck already does: collocations separated by ·, then the contrast
with the near-synonyms, then an optional "Mnemo:". Plain text, no <b> wrappers -- the
newer notes in this deck do not use them.

Usage: bash freq_data/anki_op.sh write-notes freq_data/write_notes.py --data <file> --apply
"""
import argparse
import json
import re
import sys

import jieba
from anki.collection import Collection
from opencc import OpenCC

ROOT = "/home/vincent/anki-headless"


def strip_html(s):
    s = re.sub(r"\[sound:[^\]]*\]", "", s or "")
    return re.sub(r"<[^>]+>", "", s).replace("&nbsp;", " ").strip()


def bare(s):
    return re.sub(r"\s+", "", strip_html(s))


def pykey(s):
    return re.sub(r"['’]", "", bare(s)).lower()


def readings(pinyin_field):
    """The card's readings, as separate keys.

    A one-card-per-character deck keeps every reading on one note, so 中 has the Pinyin
    field "zhōng; zhòng". Demanding the whole field appear in a sentence's pinyin is
    impossible for such a card -- one sentence uses one reading. Split on the separators
    and require ANY of them."""
    parts = [p for p in re.split(r"[;,、/]", strip_html(pinyin_field)) if p.strip()]
    return [pykey(p) for p in parts] or [pykey(pinyin_field)]


def is_split(word, sent):
    if not word or not sent or word not in sent:
        return False
    pos, spans = 0, []
    for t in jieba.cut(sent):
        spans.append((pos, pos + len(t))); pos += len(t)
    i = sent.index(word); j = i + len(word)
    cover = [(a, b) for a, b in spans if a < j and b > i]
    if len(cover) < 2:
        return False
    if cover[0][0] == i and cover[-1][1] == j:
        return False
    return cover[0][0] < i or cover[-1][1] > j


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=f"{ROOT}/collection.anki2")
    ap.add_argument("--data", required=True)
    ap.add_argument("--front", default=None,
                    help="word to pull to the front of the new queue, e.g. 疲倦")
    ap.add_argument("--front-tag", default=None,
                    help="tag added to --front so the canonical resort keeps it there")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    data = json.load(open(args.data, encoding="utf-8"))
    cc = OpenCC("s2tw")
    col = Collection(args.db)
    try:
        targets = {}
        for w, spec in data.items():
            nids = col.find_notes(f'deck:Main "Simplified:{w}"')
            # A word can legitimately have two Main notes -- 偷 has a ChineseCharacters
            # one and a ChineseVocabulary one, both suspended. Rather than guess, the
            # entry names the nid. Never silently pick the first.
            if "nid" in spec:
                if spec["nid"] not in nids:
                    sys.exit(f"{w}: nid {spec['nid']} is not a Main note for it {nids}")
                targets[w] = spec["nid"]
                continue
            if len(nids) != 1:
                sys.exit(f"{w}: expected 1 Main note, found {len(nids)} {nids} — "
                         f'add "nid" to the entry to say which')
            targets[w] = nids[0]

        # a replacement sentence must be unique and must not split its own word
        inuse = {}
        for nid in col.find_notes(""):
            note = col.get_note(nid)
            IX = {f["name"]: i for i, f in enumerate(note.note_type()["flds"])}
            if "SentenceSimplified" in IX:
                s = bare(note.fields[IX["SentenceSimplified"]])
                if s:
                    inuse.setdefault(s, nid)

        print("── checks ──")
        bad = []
        for w, spec in data.items():
            if "sentence" in spec:
                s = spec["sentence"]
                if w not in s:
                    bad.append((w, "word not in its sentence"))
                if is_split(w, s):
                    bad.append((w, "segmentation splits the word"))
                if bare(s) in inuse and inuse[bare(s)] != targets[w]:
                    bad.append((w, "sentence already used by another note"))
                note = col.get_note(targets[w])
                IX = {f["name"]: i for i, f in enumerate(note.note_type()["flds"])}
                rs = [r for r in readings(note.fields[IX["Pinyin"]]) if r]
                if rs and not any(r in pykey(spec["pinyin"]) for r in rs):
                    bad.append((w, f"no reading of {rs} appears in the sentence pinyin"))
            # A note must actually name what it contrasts against, or it is not a
            # disambiguation. But it is optional: several cards being repaired for a
            # cloze leak already carry a good note, and rewriting it would be a loss.
            if "notes" in spec and not re.search(r"[一-鿿]", spec["notes"]):
                bad.append((w, "note contains no Chinese at all"))
            if "notes" not in spec and "sentence" not in spec:
                bad.append((w, "entry changes nothing"))
        print(f"  problems: {len(bad)} (want 0)")
        for w, why in bad:
            print(f"    {w}: {why}")
        assert not bad

        print("\n── writing ──")
        for w, spec in data.items():
            note = col.get_note(targets[w])
            IX = {f["name"]: i for i, f in enumerate(note.note_type()["flds"])}
            if "notes" in spec:
                had = bool(strip_html(note.fields[IX["Notes"]]))
                note.fields[IX["Notes"]] = spec["notes"]
                print(f"\n  {w}  (Notes {'REPLACED' if had else 'was empty'}, "
                      f"{len(spec['notes'])} chars)")
                print(f"    {spec['notes'][:150]}")
            else:
                print(f"\n  {w}  (Notes left as it is)")
            if "sentence" in spec:
                s, py, en = spec["sentence"], spec["pinyin"], spec["english"]
                old = strip_html(note.fields[IX["SentenceSimplified"]])
                # EVERY occurrence, not just the first. A cloze that blanks one of two
                # leaves the answer sitting in the other half of its own front side; 13
                # cards in Main already read like "厨房里飞进来一只[]，我赶紧拿苍蝇拍打".
                simp = s.replace(w, f"<b>{w}</b>")
                note.fields[IX["SentenceSimplified"]] = simp
                note.fields[IX["SentenceTraditional"]] = cc.convert(simp)
                note.fields[IX["SentenceSimplifiedCloze"]] = s.replace(w, "[ ]")
                note.fields[IX["SentenceTraditionalCloze"]] = cc.convert(s).replace(
                    cc.convert(w), "[ ]")
                note.fields[IX["SentencePinyin"]] = py
                note.fields[IX["SentenceMeaning"]] = en
                note.fields[IX["SentenceAudio"]] = ""   # reads the OLD sentence
                print(f"    sentence - {old}")
                print(f"    sentence + {s}")
            if args.front_tag and w == args.front:
                note.add_tag(args.front_tag)
                print(f"    tagged {args.front_tag}")
            if args.apply:
                col.update_note(note)

        if args.front:
            nid = targets[args.front]
            cids = [c for c in col.card_ids_of_note(nid)
                    if col.decks.name(col.get_card(c).did).split("::")[0] == "Main"
                    and col.get_card(c).queue == 0]
            assert len(cids) == 1, cids
            before = col.get_card(cids[0]).due
            if args.apply:
                # shift_existing so nothing else lands on the same position
                col.sched.reposition_new_cards(cids, 1, 1, False, True)
            after = col.get_card(cids[0]).due
            print(f"\n  {args.front}: queue position {before} -> {after}")

        if not args.apply:
            print("\nDRY-RUN — nothing written.")
            return

        print("\n── verify ──")
        bad = []
        for w, spec in data.items():
            note = col.get_note(targets[w])
            IX = {f["name"]: i for i, f in enumerate(note.note_type()["flds"])}
            if "notes" in spec and strip_html(note.fields[IX["Notes"]]) != spec["notes"]:
                bad.append((w, "Notes did not take"))
            if "sentence" in spec:
                s = bare(note.fields[IX["SentenceSimplified"]])
                if w not in s or is_split(w, s):
                    bad.append((w, "sentence absent or splits the word"))
                if bare(note.fields[IX["SentenceAudio"]]):
                    bad.append((w, "stale sentence audio"))
                for fld in ("SentenceSimplifiedCloze", "SentenceTraditionalCloze"):
                    cz = bare(note.fields[IX[fld]])
                    if "[]" not in cz.replace(" ", ""):
                        bad.append((w, f"{fld} has no blank"))
                    if w in cz:
                        bad.append((w, f"{fld} still shows the answer"))
        print(f"  problems: {len(bad)} (want 0)")
        for w, why in bad:
            print(f"    {w}: {why}")

        if args.front:
            nid = targets[args.front]
            cid = [c for c in col.card_ids_of_note(nid)
                   if col.decks.name(col.get_card(c).did).split("::")[0] == "Main"][0]
            rows = col.db.all(
                "select c.id from cards c join decks d on d.id=c.did "
                "where d.name like 'Main%' and c.queue=0 order by c.due")
            rank = [r[0] for r in rows].index(cid) + 1
            print(f"  {args.front} is now number {rank} in the new queue (want 1)")
            if rank != 1:
                bad.append((args.front, f"front card ranks {rank}"))
        assert not bad
        print("APPLIED")
    finally:
        col.close()


if __name__ == "__main__":
    main()
