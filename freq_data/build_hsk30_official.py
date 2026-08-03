#!/usr/bin/env python3
"""Build the canonical HSK 3.0 word→level list from the official standard.

Replaces hsk3_vocab.json, which was wrong. That file was parsed out of the HSK 1-6
Vocabulary PDF text (freq_data/chunks/HSK_..._Vocabulary_*.txt), whose layout is a fixed
six lines per record — Num, Level, Word, Pinyin, Word Class, Meaning. Any entry whose
Meaning wrapped onto a second line desynchronised the reader, so from roughly entry 500
onward the Level belonged to a different word than the one it was attached to. Measured
against the official list it is 62% correct over the first 500 entries and 20-25%
correct after that; restricted to HSK 1-6 it has the right level for only 31% of words.
Word, pinyin and gloss stayed aligned (pinyin matches the official list on 9261/9294),
so only the level was lost — which is why the glosses are carried over here rather than
rebuilt.

Source: https://github.com/ivankra/hsk30 (hsk30.csv), itself derived from Pleco's OCR of
the 2021 standard (https://github.com/elkmovie/hsk30, MIT). It reproduces the published
band sizes exactly — 500 / 772 / 973 / 1000 / 1071 / 1140 / 5636 = 11,092 — which is the
check that this file is the real list and hsk3_vocab.json was not.

Two shapes in the source look similar and must NOT be treated the same:
  - "爸爸|爸"    — alternate forms of one entry; both count as HSK words
  - "第（第二）"  — a headword plus an ILLUSTRATION of it in use; only 第 is the word
Both are decomposed via the CSV's own Variants column (37 rows), which tags the second
kind with "Example". Expanding those tagged forms as headwords invents 18 HSK words that
the standard does not contain (朋友们 is not a word, it is how you are shown 们; likewise
小王, 老王, 第二, 服务员). 桌子, 里头 and 志愿者 look like the same case but are real
headword rows in their own right, so they stay.

A word can sit in more than one band (89 of them, e.g. 半 is 1 and 4). `level` is the
LOWEST band — where you first meet it — and `levels` keeps the full set.

Usage: freq_data/build_hsk30_official.py [--csv hsk30.csv] [-o freq_data/hsk30_official.json]
"""
import argparse
import csv
import json
import re

ROOT = "/home/vincent/anki-headless"
CEDICT = "/home/vincent/chinese-projects/tingchinese/TingChinese/Resources/cedict_ts.u8"
RANK = {"1": 1, "2": 2, "3": 3, "4": 4, "5": 5, "6": 6, "7-9": 7}


def cedict_glosses():
    """{simplified: 'gloss; gloss'} — only used to fill words the old file never had."""
    out = {}
    line_re = re.compile(r"^\S+ (\S+) \[[^]]*\] /(.+)/$")
    with open(CEDICT, encoding="utf-8") as f:
        for line in f:
            if line.startswith("#"):
                continue
            m = line_re.match(line.strip())
            if m and m.group(1) not in out:
                defs = [d for d in m.group(2).split("/") if not d.startswith("see ")]
                if defs:
                    out[m.group(1)] = "; ".join(defs[:3])
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True, help="hsk30.csv from github.com/ivankra/hsk30")
    ap.add_argument("-o", "--out", default=f"{ROOT}/freq_data/hsk30_official.json")
    ap.add_argument("--old", default=f"{ROOT}/freq_data/hsk3_vocab.json")
    args = ap.parse_args()

    rows = list(csv.DictReader(open(args.csv, encoding="utf-8")))
    bands = {}
    for r in rows:
        bands.setdefault(r["Level"], 0)
        bands[r["Level"]] += 1
    expect = {"1": 500, "2": 772, "3": 973, "4": 1000, "5": 1071, "6": 1140, "7-9": 5636}
    if bands != expect:
        raise SystemExit(f"REFUSING: band sizes {bands} != published {expect}. "
                         "This is the check that the source is the real standard.")
    print(f"source verified: {len(rows)} rows, band sizes match the published standard")

    old_gloss, old_pos = {}, {}
    for e in json.load(open(args.old, encoding="utf-8")):
        old_gloss.setdefault(e["word"], e.get("gloss", ""))
        old_pos.setdefault(e["word"], e.get("pos", ""))
    ced = cedict_glosses()

    headwords = {r["Simplified"] for r in rows}
    entries = {}          # word -> {levels:set, pinyin, pos}
    skipped_examples = set()
    for r in rows:
        forms = []
        if r.get("Variants"):
            try:
                for v in json.loads(r["Variants"]):
                    # "Example" marks an illustration of the headword, not a word of its own
                    if v.get("Example") and v["Simplified"] not in headwords:
                        skipped_examples.add(v["Simplified"])
                        continue
                    forms.append((v["Simplified"], v.get("Pinyin", ""), v.get("POS", "")))
            except Exception:
                forms = []
        if not forms:
            forms = [(r["Simplified"], r["Pinyin"], r.get("POS", ""))]
        for word, pinyin, pos in forms:
            word = word.strip()
            if not word:
                continue
            e = entries.setdefault(word, {"levels": set(), "pinyin": pinyin, "pos": pos})
            e["levels"].add(r["Level"])

    out, from_old, from_ced, no_gloss = [], 0, 0, 0
    for word, e in entries.items():
        gloss = old_gloss.get(word) or ""
        if gloss:
            from_old += 1
        else:
            gloss = ced.get(word, "")
            if gloss:
                from_ced += 1
            else:
                no_gloss += 1
        levels = sorted(e["levels"], key=lambda l: RANK[l])
        out.append({"word": word, "level": levels[0], "levels": levels,
                    "pinyin": e["pinyin"], "pos": e["pos"] or old_pos.get(word, ""),
                    "gloss": gloss})
    out.sort(key=lambda x: (RANK[x["level"]], x["word"]))

    json.dump(out, open(args.out, "w", encoding="utf-8"), ensure_ascii=False, indent=0)
    multi = sum(1 for x in out if len(x["levels"]) > 1)
    print(f"wrote {args.out}: {len(out)} distinct words ({multi} appear in more than one band)")
    print(f"  skipped {len(skipped_examples)} illustration-only forms: {' '.join(sorted(skipped_examples))}")
    print(f"  glosses: {from_old} kept from the old file, {from_ced} from CC-CEDICT, {no_gloss} empty")
    per = {}
    for x in out:
        per[x["level"]] = per.get(x["level"], 0) + 1
    print("  words by first band:", {k: per[k] for k in sorted(per, key=lambda l: RANK[l])})


if __name__ == "__main__":
    main()
