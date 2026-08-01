#!/usr/bin/env python3
"""Re-derive the cloze and traditional sentence fields from SentenceSimplified.

The July batches rewrote SentenceSimplified (and its pinyin and meaning) but left
SentenceSimplifiedCloze, SentenceTraditional and SentenceTraditionalCloze holding the
*previous* sentence. The Cloze-Recall front renders SentenceSimplifiedCloze and the back
renders SentenceSimplified, so 151 cards asked about one sentence and answered with a
different one — ten of them with no context left at all (为什么 was literally "[ ]？",
and 十分 asked for 十分钟 "ten minutes" rather than the card's 十分 "very").

SentenceSimplified is treated as the source of truth because it is the field the July
batches actually updated: its pinyin and meaning already correspond to it, and its
sentences carry far more context than the ones they replaced. The target word is
<b>-wrapped in the sentence, so the blank goes exactly where the bold span is.

Not fixed here: SentenceAudio on these notes still voices the old sentence. Cloze-Recall
does not reference it, but the Hanzi-English and English-Speaking templates do, so those
cards (in other decks) still play the wrong audio. Reported by --audit, not touched.

Usage: bash freq_data/anki_op.sh cloze-resync freq_data/resync_cloze_sentences.py --apply
"""
import argparse
import re

from anki.collection import Collection
from opencc import OpenCC

ROOT = "/home/vincent/anki-headless"
CLOZE_DID = 1781631612781
BOLD = re.compile(r"<b>(.*?)</b>", re.S)


def strip_html(s):
    return re.sub(r"<[^>]+>", "", s or "").replace("&nbsp;", " ").strip()


def bold_target(sentence_html):
    """The exact inflected form highlighted in the sentence, if any. Headwords carry
    citation forms the sentence never contains verbatim (还好（了） appears as 还好了),
    so this is what the blank must be matched against — not the Simplified field."""
    m = BOLD.search(sentence_html)
    return strip_html(m.group(1)) if m else None


def blank(sentence_html, target):
    """Replace the highlighted target with '[ ]'. Falls back to a literal search when the
    sentence carries no <b> markup (a handful of notes)."""
    if BOLD.search(sentence_html):
        return strip_html(BOLD.sub("[ ]", sentence_html))
    plain = strip_html(sentence_html)
    return plain.replace(target, "[ ]", 1) if target and target in plain else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=f"{ROOT}/collection.anki2")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    cc = OpenCC("s2t")
    col = Collection(args.db)
    try:
        cv = col.models.by_name("ChineseVocabulary")
        IX = {f["name"]: i for i, f in enumerate(cv["flds"])}
        nids = sorted({col.get_card(c).nid for c in col.decks.cids(CLOZE_DID, children=True)})

        fixed, skipped, stale_audio = [], [], []
        for nid in nids:
            note = col.get_note(nid)
            word = strip_html(note.fields[IX["Simplified"]])
            simp_html = note.fields[IX["SentenceSimplified"]]
            simp = strip_html(simp_html)
            if not simp:
                continue
            target = bold_target(simp_html) or word
            old_cloze = strip_html(note.fields[IX["SentenceSimplifiedCloze"]])
            new_cloze = blank(simp_html, target)
            if new_cloze is None:
                skipped.append((word, f"cannot locate target in {simp!r}")); continue
            if not old_cloze or old_cloze == new_cloze:
                continue  # front already agrees with the back (or gates off the card)

            # regenerate Traditional only when it no longer matches the current sentence
            trad_html = note.fields[IX["SentenceTraditional"]]
            want_trad = cc.convert(simp_html)
            trad_changed = strip_html(trad_html) != strip_html(want_trad)
            if trad_changed:
                trad_html = want_trad
            new_trad_cloze = blank(trad_html, cc.convert(target))
            if new_trad_cloze is None:
                skipped.append((word, "cannot locate target in traditional")); continue

            if strip_html(note.fields[IX["SentenceAudio"]]) and trad_changed:
                stale_audio.append((nid, word))

            if args.apply:
                note.fields[IX["SentenceSimplifiedCloze"]] = new_cloze
                note.fields[IX["SentenceTraditional"]] = trad_html
                note.fields[IX["SentenceTraditionalCloze"]] = new_trad_cloze
                col.update_note(note)
            fixed.append((word, old_cloze, new_cloze, trad_changed))

        for word, old, new, tc in fixed[:8]:
            print(f"  {word}\n    was: {old}\n    now: {new}{'   (+traditional)' if tc else ''}")
        print(f"\n{len(fixed)} resynced "
              f"({sum(1 for *_, tc in fixed if tc)} also had Traditional regenerated), "
              f"{len(skipped)} skipped")
        for word, why in skipped:
            print(f"  SKIP {word}: {why}")
        print(f"\n{len(stale_audio)} of these still have SentenceAudio voicing the OLD "
              f"sentence (not used by Cloze-Recall; affects Hanzi-English / "
              f"English-Speaking cards elsewhere)")

        if args.apply:
            bad = []
            for nid in nids:
                n = col.get_note(nid)
                sh = n.fields[IX["SentenceSimplified"]]
                if not strip_html(sh):
                    continue
                # reconstruct against the inflected form in the sentence, NOT the headword:
                # 还好（了） is a citation form the sentence never contains verbatim, and
                # comparing against it reports correct cards as broken
                target = bold_target(sh) or strip_html(n.fields[IX["Simplified"]])
                cz = strip_html(n.fields[IX["SentenceSimplifiedCloze"]])
                expected = blank(sh, target)
                if cz and expected and cz != expected:
                    bad.append((strip_html(n.fields[IX["Simplified"]]), cz, expected))
            print(f"\nverify: {len(bad)} cloze fronts still disagree with their back")
            for w, cz, sp in bad[:10]:
                print(f"  {w}: {cz}  |  {sp}")
        else:
            print("DRY-RUN — nothing written.")
    finally:
        col.close()


if __name__ == "__main__":
    main()
