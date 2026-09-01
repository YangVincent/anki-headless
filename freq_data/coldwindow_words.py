#!/usr/bin/env python3
"""One row per (word, book) across the Cold Window samples, tagged so it can be sorted.

Answers "which words does this novel demand that I have not studied", and does it per
book, so a study list for one novel is a filter away:

    book == 入迷 and anki == absent and is_name == False

Columns:

    book, author        which novel the word appears in
    word, count, share  the token and how much of that book it is
    zipf                wordfreq commonness, 7 = everywhere, 2 = rare
    anki                known | queued | absent — what the collection says
    status              mature | learning, when anki == known
    transparent         every character appears inside a word already known
    in_cedict           the word is in CC-CEDICT
    pinyin, meaning     from CC-CEDICT, so a row can become a card
    is_name             the name filter's verdict — REVIEW IT, it is a vote
    name_votes, why     how it voted, so a wrong call is visible

Writes gen_coldwindow/words_by_book.csv and names_by_book.json. The names file is what
coldwindow_difficulty.py reads, so the ranking and this table never disagree.
"""
from __future__ import annotations

import csv
import json
import re
import sys
from pathlib import Path

import anki_coverage as ak
import name_filter as nf

HERE = Path(__file__).resolve().parent
OUT = HERE / "gen_coldwindow"
MIN_COUNT = 1


def cedict_entries(path=nf.CEDICT):
    """{simplified: (pinyin, first gloss)} — enough to turn a row into a card."""
    out = {}
    for line in open(path, encoding="utf-8"):
        if line.startswith("#"):
            continue
        m = re.match(r"(\S+) (\S+) \[([^\]]*)\] /(.+)/", line)
        if m and m.group(2) not in out:
            out[m.group(2)] = (m.group(3), m.group(4).split("/")[0])
    return out


def profile(text):
    """{word: count} and {word: jieba tags} for the content words of one book."""
    import jieba.posseg as pseg
    counts, tags = {}, {}
    for w, flag in pseg.cut(text):
        if len(w) >= 2 and ak.HAN.search(w):
            counts[w] = counts.get(w, 0) + 1
            tags.setdefault(w, set()).add(flag)
    return counts, tags


def books():
    """{title: (author, simplified text)} for every work with real chapter text."""
    entries = json.loads((OUT / "samples.json").read_text(encoding="utf-8"))
    out = {}
    for e in entries:
        s = e.get("sample")
        if not s or not s["chapters"]:
            continue
        text, _ = ak.to_simplified("\n".join(s["chapters"]))
        out[e["title_zh"]] = (e["author_zh"], text)
    return out


def main():
    from wordfreq import zipf_frequency
    cedict, surnames = nf.load_cedict()
    gloss = cedict_entries()
    k = ak.load()
    rows, names = [], {}

    for title, (author, text) in books().items():
        counts, tags = profile(text)
        total = sum(counts.values())
        names[title] = []
        for word, n in counts.items():
            if n < MIN_COUNT:
                continue
            z = zipf_frequency(word, "zh")
            votes, why = nf.score(word, n, total, z, tags.get(word, set()), cedict, surnames)
            is_name = votes >= nf.THRESHOLD
            if is_name:
                names[title].append(word)
            status = k.known.get(word)
            rows.append({
                "book": title, "author": author, "word": word, "count": n,
                "share_pct": round(100 * n / total, 3), "zipf": round(z, 2),
                "anki": "known" if status else ("queued" if word in k.queued else "absent"),
                "status": status or "",
                "transparent": all(c in k.chars for c in word if ak.HAN.match(c)),
                "in_cedict": word in cedict,
                "pinyin": gloss.get(word, ("", ""))[0],
                "meaning": gloss.get(word, ("", ""))[1],
                "is_name": is_name, "name_votes": votes, "why": "; ".join(why),
                "keyness": round(nf.keyness(n, total, z), 2),
            })

    rows.sort(key=lambda r: (r["book"], -r["count"]))
    with open(OUT / "words_by_book.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    (OUT / "names_by_book.json").write_text(
        json.dumps(names, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"{len(rows)} rows over {len(names)} books -> {OUT/'words_by_book.csv'}")
    flagged = sum(len(v) for v in names.values())
    print(f"{flagged} name types flagged -> {OUT/'names_by_book.json'}")
    print(f"\n{'book':<20}{'types':>7}{'names':>7}  most frequent names")
    for title in sorted(names):
        n = [r for r in rows if r["book"] == title]
        top = sorted((r for r in n if r["is_name"]), key=lambda r: -r["count"])[:6]
        print(f"{title:<20}{len(n):>7}{len(names[title]):>7}  "
              + " ".join(f"{r['word']}x{r['count']}" for r in top))


if __name__ == "__main__":
    main()
