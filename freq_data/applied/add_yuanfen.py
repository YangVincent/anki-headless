#!/usr/bin/env python3
"""RETIRED 2026-09-01. It names a deck that no longer exists: `HSK`, `HSK7-9`,
`non-HSK` and `Mined` all became `Main` that day. Kept as a record of what was done
to the collection, not as a tool. Re-running it would resolve nothing and report
success -- the exact failure freq_data/README.md warns about.

Promote 缘分 (HSK 7-9) out of Hidden::Personal into the HSK7-9 study deck.

It was the last multi-character HSK 3.0 word with no active card in a study deck: a
ChineseVocabulary note tagged `personal`, living in Hidden::Personal. Its ord=0 card moves
to HSK7-9 and gets the deck's HSK tags; the ord=1 reverse card stays where it is (reverse
cards are suspended/hidden everywhere else — cleanup_hsk_residue.py).

Also repairs the note the same way freq_data/fix_and_unsuspend_hsk.py did the other 64: its
SentenceSimplified was an unpunctuated subtitle fragment with no traditional/pinyin/
translation/cloze, and the Traditional field was empty.

Position is NOT set here — run freq_data/resort_hsk_queue.py afterwards.

Usage: bash freq_data/anki_op.sh yuanfen freq_data/add_yuanfen.py --apply
"""
import re, argparse

from anki.collection import Collection
from wordfreq import zipf_frequency
from opencc import OpenCC
from pypinyin import pinyin, Style
import jieba

ROOT = "/home/vincent/anki-headless"
WORD = "缘分"
NID = 1708747505302
SENT = "我们能相遇真是一种缘分。"
EN = "That we were able to meet really is a matter of fate."
TO_TRAD = OpenCC("s2t").convert
PUNCT = {"，": ",", "。": ".", "？": "?", "！": "!", "、": ","}


def strip_html(s):
    return re.sub(r"<[^>]+>", "", s or "").replace("&nbsp;", " ").strip()


def sent_pinyin(sent, word, word_pinyin):
    def run(t):
        out = []
        for tok in jieba.cut(t):
            if re.search(r"[一-鿿]", tok):
                out.append("".join(p[0] for p in pinyin(tok, style=Style.TONE)))
            elif tok.strip():
                out.append(PUNCT.get(tok, tok))
        return out
    py_word = "".join(p[0] for p in pinyin(word, style=Style.TONE))
    field = word_pinyin.replace(" ", "").strip()
    use = py_word if py_word.lower() == field.lower() else field
    i = sent.index(word)
    s = " ".join(p for p in run(sent[:i]) + [use] + run(sent[i + len(word):]) if p)
    s = re.sub(r"\s+([,.?!;:])", r"\1", s)
    return s[:1].upper() + s[1:]


def freq_badge(w):
    z = zipf_frequency(w, "zh")
    label, stars = (("very common", 5) if z >= 5 else ("common", 4) if z >= 4
                    else ("mid", 3) if z >= 3.5 else ("uncommon", 2) if z > 0 else ("rare", 1))
    return f"{'★' * stars} {label} · zipf {round(z, 1)}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=f"{ROOT}/collection.anki2")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    col = Collection(args.db)
    try:
        cv = col.models.by_name("ChineseVocabulary")
        IX = {f["name"]: i for i, f in enumerate(cv["flds"])}
        did = col.decks.id_for_name("HSK7-9")
        assert did is not None, "HSK7-9 deck missing"

        note = col.get_note(NID)
        assert strip_html(note.fields[IX["Simplified"]]) == WORD, "nid is not 缘分"
        assert note.note_type()["id"] == cv["id"], "not a ChineseVocabulary note"

        wp = strip_html(note.fields[IX["Pinyin"]])
        trad, wtrad = TO_TRAD(SENT), TO_TRAD(WORD)
        vals = {
            "Traditional": wtrad,
            "SentenceSimplified": SENT.replace(WORD, f"<b>{WORD}</b>", 1),
            "SentenceTraditional": trad.replace(wtrad, f"<b>{wtrad}</b>", 1),
            "SentenceSimplifiedCloze": SENT.replace(WORD, "[ ]", 1),
            "SentenceTraditionalCloze": trad.replace(wtrad, "[ ]", 1),
            "SentencePinyin": sent_pinyin(SENT, WORD, wp),
            "SentenceMeaning": EN,
            "CustomFreq": freq_badge(WORD),
        }
        print(f"note {NID} {WORD} [{wp}] {strip_html(note.fields[IX['Meaning']])[:60]}")
        print(f"  old sentence: {strip_html(note.fields[IX['SentenceSimplified']])!r}")
        for k, v in vals.items():
            print(f"  {k:26} -> {strip_html(v)!r}")

        fwd = [c for c in note.cards() if c.ord == 0]
        assert len(fwd) == 1, f"expected 1 ord=0 card, got {len(fwd)}"
        cid = fwd[0].id
        print(f"  ord=0 card {cid}: deck {col.decks.name(fwd[0].did)} -> HSK7-9, queue {fwd[0].queue}")

        if args.apply:
            for k, v in vals.items():
                note.fields[IX[k]] = v
            for t in ("HSK", "HSK::HSK7-9", "chinese"):
                note.add_tag(t)
            col.update_note(note)
            col.set_deck([cid], did)
            col.sched.unsuspend_cards([cid])

            # ── verify (before the bot restarts) ──
            n = col.get_note(NID)
            c0 = [c for c in n.cards() if c.ord == 0][0]
            print("\n── verify ──")
            print(f"  deck={col.decks.name(c0.did)} queue={c0.queue} type={c0.type}")
            print(f"  tags={' '.join(sorted(n.tags))}")
            print(f"  sentence={strip_html(n.fields[IX['SentenceSimplified']])}")
            print(f"  pinyin  ={n.fields[IX['SentencePinyin']]}")
            print(f"  trad    ={strip_html(n.fields[IX['SentenceTraditional']])}")
            print(f"  cloze   ={strip_html(n.fields[IX['SentenceSimplifiedCloze']])}")
            assert col.decks.name(c0.did) == "HSK7-9" and c0.queue != -1
            # the other-deck reverse card must be untouched
            rev = [c for c in n.cards() if c.ord == 1]
            print(f"  reverse card left in: {col.decks.name(rev[0].did) if rev else '(none)'}")
            print("\nAPPLIED.")
        else:
            print("\nDRY-RUN — nothing written.")
    finally:
        col.close()


if __name__ == "__main__":
    main()
