#!/usr/bin/env python3
"""Flag the character names in a book, so they stop counting as unknown vocabulary.

WHY A VOTE AND NOT A RULE. Character names and rare domain words overlap on every
single signal I measured across the Cold Window samples:

    wordfreq Zipf   names 0.00-3.15   rare words 1.43-5.21
    keyness         names 3.95-6.59   rare words 2.76-5.06
    CC-CEDICT       absent for both
    surname first   true for 沈逆 and 燕落, ALSO true for 义体 and 师门
    jieba `nr`      catches 沈逆 and 曾倾洛, misses 边烬 and 燕落

No threshold on any one of them separates 边烬 (a name, 109 times in 焚情) from 玉瓶
(a real word, 48 times in 清穿日常). So this scores several weak signals and takes a
vote, and every decision it makes stays in the output for review. It is a filter you
check, not a filter you trust.

keyness = how far a word's rate in ONE book runs above its rate in the wordfreq corpus.
A name is written a hundred times in its own novel and almost nowhere else.
"""
from __future__ import annotations

import math
import re

CEDICT = "/home/vincent/chinese-projects/dong-chinese/Resources/cedict_ts.u8"
HAN = re.compile(r"[一-鿿]")
#: A vote at or above this counts as a name. Tuned on 26 hand-labelled tokens; see
#: the module test in coldwindow_words.py --check.
THRESHOLD = 3
#: jieba's proper-noun tags. anki_coverage drops these before scoring; the filter reads
#: them too, because a tag on one occurrence should convict every occurrence.
NAME_TAGS = {"nr", "nrt", "nrfg", "ns", "nt", "nz"}
#: Below this keyness a token is not book-specific enough to be a character name.
KEYNESS_FLOOR = 3.0
#: A second keyness vote. Measured, not chosen: no labelled real word reaches it.
KEYNESS_HIGH = 5.2
#: A surname-initial token repeated this often in one book is a character.
SURNAME_REPEAT = 20


def load_cedict(path=CEDICT):
    """(headwords, surname characters). Surnames come from the glosses, not a list I
    typed: any single-character entry with a gloss that starts "surname"."""
    words, surnames = set(), set()
    for line in open(path, encoding="utf-8"):
        if line.startswith("#"):
            continue
        m = re.match(r"(\S+) (\S+) \[([^\]]*)\] /(.+)/", line)
        if not m:
            continue
        simp = m.group(2)
        words.add(simp)
        if len(simp) == 1 and any(g.startswith("surname") for g in m.group(4).split("/")):
            surnames.add(simp)
    return words, surnames


def keyness(count, total, zipf):
    """log10(rate in this book) - log10(rate in the corpus). Zipf is per billion."""
    if not count or not total:
        return 0.0
    return math.log10(count / total) - (zipf - 9)


def score(word, count, total, zipf, tags, cedict, surnames):
    """Vote on whether `word` is a proper noun in this book. Returns (votes, reasons).

    Note what this does NOT have to catch. anki_coverage and difficulty_report already
    drop any token jieba tags nr/nrt/ns/nt/nz, which covers 莉莉丝, 多琳, 亦秋 and 穆星.
    This exists for the leaks: 边烬 tagged `n`, 冉禁 tagged `d`.
    """
    if word in cedict:
        return 0, ["in CEDICT"]          # a dictionary word is never a name here
    if count < 3 or not (2 <= len(word) <= 4):
        return 0, ["too rare or too long to judge"]
    k = keyness(count, total, zipf)
    if k < KEYNESS_FLOOR:
        # 全文完 and 那本书 sit below it: jieba calls them names and their first
        # character is a surname, but they are not book-specific enough to be one.
        return 0, [f"keyness {k:.1f} below the floor"]

    votes, why = 0, []
    if tags & NAME_TAGS:
        votes += 2
        why.append("jieba tags it a name")
    if word[0] in surnames:
        votes += 1
        why.append("starts with a surname")
        if count >= SURNAME_REPEAT:
            # 冉禁, 113 times in 造物的恩宠. A surname-initial token written this often
            # in one book is a character. The labelled real words that start with a
            # surname character — 义体, 师门 — appear 12 and 13 times.
            votes += 1
            why.append(f"surname repeated {count} times")
    if k >= 4.5:
        votes += 1
        why.append(f"keyness {k:.1f}")
    if k >= KEYNESS_HIGH:
        # 边烬 and 幽砚 sit here, with no surname and no name tag. The margin is thin:
        # the highest keyness among the labelled real words is 簪子 at 5.06.
        votes += 1
        why.append("keyness very high")
    if zipf < 2.0:
        votes += 1
        why.append(f"zipf {zipf:.2f}")
    return votes, why
