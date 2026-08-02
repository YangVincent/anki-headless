#!/usr/bin/env python3
"""Re-render machine-generated SentenceTraditional with OpenCC's Taiwan mapping.

OpenCC's plain `s2t` picks variant forms this deck does not use: it turns 吃 into 喫,
為 into 爲 and 裡 into 裏. The deck is decisively Taiwan-convention — 為 545:49, 裡
1018:108, 吃 260:16, 啟 17:1 — so `s2tw` is the correct config, and every sentence
converted with `s2t` (including by my own earlier scripts in this repo) is inconsistent
with the other 90%+ of the deck.

Only notes whose stored traditional is *exactly* what `s2t` produces are touched, which
is the signature of machine conversion. A hand-written or differently-sourced traditional
never matches that byte-for-byte, so it is left alone.

Usage: bash freq_data/anki_op.sh trad-variants freq_data/fix_traditional_variants.py --apply
"""
import argparse
import re

from anki.collection import Collection
from opencc import OpenCC

ROOT = "/home/vincent/anki-headless"


def strip_html(s):
    return re.sub(r"<[^>]+>", "", s or "").replace("&nbsp;", " ").strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=f"{ROOT}/collection.anki2")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    s2t, s2tw = OpenCC("s2t"), OpenCC("s2tw")
    col = Collection(args.db)
    try:
        cv = col.models.by_name("ChineseVocabulary")
        IX = {f["name"]: i for i, f in enumerate(cv["flds"])}
        fixed = []
        for nid in col.find_notes('"note:ChineseVocabulary"'):
            note = col.get_note(nid)
            simp = note.fields[IX["SentenceSimplified"]]
            trad = note.fields[IX["SentenceTraditional"]]
            if not strip_html(simp) or not strip_html(trad):
                continue
            old_style, new_style = s2t.convert(simp), s2tw.convert(simp)
            if old_style == new_style:
                continue
            if strip_html(trad) != strip_html(old_style):
                continue  # not machine-converted by s2t; leave it
            if args.apply:
                note.fields[IX["SentenceTraditional"]] = new_style
                col.update_note(note)
            fixed.append((strip_html(note.fields[IX["Simplified"]]),
                          strip_html(trad), strip_html(new_style)))

        for w, old, new in fixed[:6]:
            print(f"  {w}: {old}\n     -> {new}")
        print(f"\n{len(fixed)} notes re-rendered with s2tw")

        if args.apply:
            left = 0
            for nid in col.find_notes('"note:ChineseVocabulary"'):
                n = col.get_note(nid)
                simp, trad = n.fields[IX["SentenceSimplified"]], n.fields[IX["SentenceTraditional"]]
                if not strip_html(simp) or not strip_html(trad):
                    continue
                if s2t.convert(simp) != s2tw.convert(simp) and \
                        strip_html(trad) == strip_html(s2t.convert(simp)):
                    left += 1
            print(f"verify: s2t-style traditional remaining: {left} (want 0)")
        else:
            print("DRY-RUN — nothing written.")
    finally:
        col.close()


if __name__ == "__main__":
    main()
