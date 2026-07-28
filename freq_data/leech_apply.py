#!/usr/bin/env python3
"""Write the rewritten descriptions onto the failing HSK cards, and park the characters
that are not words.

Reads freq_data/leech_rewrite.json. For each card:
  Meaning              -> the new plain-English description
  Notes                -> the contrast with its confusables, plus real collocations.
                          For the connectives this is the actual content of the card:
                          "however" is shared by 但是/可是/不过/却, so the only thing worth
                          testing is what separates them.
  SentenceSimplified   -> a new example (several old ones were anime or game fragments)
  SentenceMeaning      -> its translation
  SentencePinyin       -> cleared, since it belonged to the sentence being replaced

The Pinyin field is left alone — the markup in it is tone colouring, which renders fine.

Every original field is written to freq_data/leech_backup.json before anything changes,
so this is reversible with --undo.

Also suspends the character cards the rewrite marked "learn-in-word" — characters that
never stand alone, whose card asks a question with no answer. 祝 is excluded from that
despite being flagged: it genuinely is used alone (祝你生日快乐) and the rewrite gave no
replacement word for it. They get the same tag as the 400 already parked, so one undo
restores everything.

  leech_apply.py                # dry run
  leech_apply.py --apply        # via freq_data/anki_op.sh
  leech_apply.py --undo --apply # restore the original fields
"""
import argparse
import json
from pathlib import Path
from anki_common import sync as _sync

ROOT = Path("/home/vincent/anki-headless")
COL = ROOT / "collection.anki2"
REWRITE = ROOT / "freq_data/leech_rewrite.json"
BACKUP = ROOT / "freq_data/leech_backup.json"
TAG_REWRITTEN = "rewritten::leech"
TAG_PARKED = "parked::bound-character"
KEEP_ANYWAY = {"祝"}          # flagged learn-in-word, but it does stand alone
FIELDS = ("Meaning", "Notes", "SentenceSimplified", "SentenceMeaning", "SentencePinyin")



def build_notes(card):
    """Contrast first — for a connective that IS the card — then the collocations."""
    parts = []
    if card.get("contrast"):
        parts.append(f"<b>vs.</b> {card['contrast']}")
    if card.get("collocations"):
        parts.append("<br>".join(card["collocations"]))
    if card.get("study_instead") and card.get("recommend") == "learn-in-word":
        parts.append("<i>Not a word on its own — study "
                     + "、".join(w.split(" (")[0] for w in card["study_instead"]) + "</i>")
    return "<br><br>".join(parts)


def main():
    from anki.collection import Collection

    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--undo", action="store_true")
    ap.add_argument("--col", default=str(COL))
    a = ap.parse_args()
    if a.apply and a.col != str(COL):
        raise SystemExit("--apply only ever writes the real collection")

    col = Collection(a.col)
    try:
        if a.undo:
            if not BACKUP.exists():
                raise SystemExit("no backup file — nothing to undo")
            saved = json.loads(BACKUP.read_text())
            print(f"restoring {len(saved)} notes from {BACKUP.name}")
            if not a.apply:
                print("(dry run)")
                return
            for entry in saved:
                note = col.get_note(entry["nid"])
                for f, v in entry["fields"].items():
                    note[f] = v
                note.remove_tag(TAG_REWRITTEN)
                col.update_note(note)
            print("original text restored (parked cards stay parked — "
                  "use park_bound_chars.py --undo for those)")
            _sync(col)
            return

        cards = json.loads(REWRITE.read_text())
        # The "learn-in-word" flag is only meaningful for a single character. It came back
        # on 放弃 too — a common two-character word, flagged because its gloss was too
        # broad, with no replacement word given. Parking that would be a real loss, so the
        # length check is the guard, not the flag alone.
        to_park = [c for c in cards
                   if c.get("recommend") == "learn-in-word"
                   and len(c["word"]) == 1 and c["word"] not in KEEP_ANYWAY]
        spurious = [c["word"] for c in cards
                    if c.get("recommend") == "learn-in-word" and len(c["word"]) > 1]
        if spurious:
            print(f"ignoring the learn-in-word flag on multi-character words: "
                  f"{' '.join(spurious)}")
        print(f"{len(cards)} cards to rewrite, {len(to_park)} to park: "
              + " ".join(c["word"] for c in to_park))
        print(f"keeping despite the flag: {' '.join(sorted(KEEP_ANYWAY))}")

        if not a.apply:
            sample = next(c for c in cards if c["word"] == "然而")
            print(f"\nexample — {sample['word']}:")
            print(f"  Meaning: {sample['meaning'][:150]}")
            print(f"  Notes:   {build_notes(sample)[:150]}")
            print("\n(dry run — nothing written)")
            return

        backup = []
        for card in cards:
            note = col.get_note(card["nid"])
            backup.append({"nid": card["nid"], "word": card["word"],
                           "fields": {f: note[f] for f in FIELDS if f in note}})
        BACKUP.write_text(json.dumps(backup, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"originals saved to {BACKUP.name}")

        changed = 0
        for card in cards:
            note = col.get_note(card["nid"])
            note["Meaning"] = card["meaning"]
            if "Notes" in note:
                note["Notes"] = build_notes(card)
            word = card["word"]
            if card.get("sentence"):
                note["SentenceSimplified"] = card["sentence"].replace(word, f"<b>{word}</b>", 1)
                note["SentenceMeaning"] = card.get("sentence_meaning", "")
                if "SentencePinyin" in note:
                    note["SentencePinyin"] = ""      # belonged to the replaced sentence
            note.add_tag(TAG_REWRITTEN)
            col.update_note(note)
            changed += 1

        park_ids = []
        for card in to_park:
            note = col.get_note(card["nid"])
            park_ids += [c.id for c in note.cards()]
            note.add_tag(TAG_PARKED)
            col.update_note(note)
        col.sched.suspend_cards(park_ids)

        # verify
        spot = col.get_note(next(c["nid"] for c in cards if c["word"] == "然而"))
        assert "但是" in spot["Notes"], "contrast did not land on 然而"
        assert len(col.find_notes(f'tag:"{TAG_REWRITTEN}"')) == changed, "tag count mismatch"
        active = len(col.find_cards('deck:"HSK" -is:suspended'))
        print(f"\nrewrote {changed} cards, parked {len(park_ids)} cards "
              f"({len(to_park)} characters)")
        print(f"HSK active cards now: {active}")
        print("undo text with:  leech_apply.py --undo --apply")
        _sync(col)
    finally:
        col.close()


if __name__ == "__main__":
    main()
