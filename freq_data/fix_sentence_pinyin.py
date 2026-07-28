#!/usr/bin/env python3
"""Rebuild SentencePinyin for the 64 sentences written by fix_and_unsuspend_hsk.py.

pypinyin's phrase dictionary gives a full tone where the word actually takes a neutral
one (马虎 -> "mǎhǔ", should be "mǎhu"; also 益处/巴结/牡丹), and jieba can split across
the target word (纯金|子 -> "chúnjīn zi"). The note's own Pinyin field is authoritative,
so splice it in verbatim: pinyin(prefix) + Pinyin + pinyin(suffix). Everything outside
the target word keeps pypinyin's reading, matching the deck's existing sentence style.

Usage: bash freq_data/anki_op.sh fix-sent-pinyin freq_data/fix_sentence_pinyin.py --apply
"""
import sys, json, re, argparse

from anki.collection import Collection
from pypinyin import pinyin, Style
import jieba

ROOT = "/home/vincent/anki-headless"
PUNCT = {"，": ",", "。": ".", "？": "?", "！": "!", "、": ",",
         "“": '"', "”": '"', "：": ":", "；": ";"}


def strip_html(s):
    return re.sub(r"<[^>]+>", "", s or "").replace("&nbsp;", " ").strip()


def py_of(text):
    """pypinyin over a run of text, jieba-segmented, punctuation romanized."""
    out = []
    for tok in jieba.cut(text):
        if re.search(r"[一-鿿]", tok):
            out.append("".join(p[0] for p in pinyin(tok, style=Style.TONE)))
        elif tok.strip():
            out.append(PUNCT.get(tok, tok))
    return out


def build(sent, word, word_pinyin):
    """Splice the note's own reading in ONLY where pypinyin disagrees with it.

    Sentence pinyin joins a word's syllables ("guìxìng"), while the Pinyin field spaces
    them ("guì xìng") — so compare with spaces stripped and, on a real disagreement
    (neutral-tone words: mǎhu, yìchu, bājie, mǔdan), use the field's reading joined the
    same way. Otherwise keep pypinyin's, which already matches the deck's style."""
    py_word = "".join(p[0] for p in pinyin(word, style=Style.TONE))
    field_word = word_pinyin.replace(" ", "").strip()
    use = py_word if py_word.lower() == field_word.lower() else field_word

    i = sent.index(word)
    parts = py_of(sent[:i]) + [use] + py_of(sent[i + len(word):])
    s = " ".join(p for p in parts if p)
    s = re.sub(r"\s+([,.?!;:])", r"\1", s)
    return s[:1].upper() + s[1:] if s else s


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=f"{ROOT}/collection.anki2")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    sents = json.load(open(f"{ROOT}/freq_data/gen_fix/sentences.json"))
    col = Collection(args.db)
    try:
        cv = col.models.by_name("ChineseVocabulary")
        IX = {f["name"]: i for i, f in enumerate(cv["flds"])}
        changed, unchanged, bad = 0, 0, []
        for e in sents:
            note = col.get_note(e["nid"])
            word = e["word"]
            if strip_html(note.fields[IX["Simplified"]]) != word:
                bad.append((word, "nid/word mismatch")); continue
            wp = strip_html(note.fields[IX["Pinyin"]])
            new = build(e["sent"], word, wp)
            old = note.fields[IX["SentencePinyin"]]
            # the word's own reading must now appear verbatim
            if wp.replace(" ", "").lower() not in new.replace(" ", "").lower():
                bad.append((word, f"word pinyin still absent: {new!r}")); continue
            if new != old:
                changed += 1
                if changed <= 6:
                    print(f"  {word:8} {old}\n  {'':8} -> {new}")
                if args.apply:
                    note.fields[IX["SentencePinyin"]] = new
                    col.update_note(note)
            else:
                unchanged += 1
        print(f"\n{changed} rewritten, {unchanged} already correct, {len(bad)} problems")
        for w, why in bad:
            print(f"  PROBLEM {w}: {why}")

        if args.apply:
            print("\n── verify: every one of the 64 now contains its word's pinyin ──")
            miss = []
            for e in sents:
                n = col.get_note(e["nid"])
                wp = strip_html(n.fields[IX["Pinyin"]]).replace(" ", "").lower()
                sp = strip_html(n.fields[IX["SentencePinyin"]]).replace(" ", "").lower()
                if wp not in sp:
                    miss.append((e["word"], wp, sp))
            print(f"  garbled: {len(miss)} (want 0)")
            for w, wp, sp in miss:
                print(f"    {w} {wp} | {sp}")
            for w in ("马虎", "益处", "巴结", "牡丹", "金子"):
                e = next(x for x in sents if x["word"] == w)
                n = col.get_note(e["nid"])
                print(f"  {w}: {strip_html(n.fields[IX['SentencePinyin']])}")
        else:
            print("DRY-RUN — nothing written.")
    finally:
        col.close()


if __name__ == "__main__":
    main()
