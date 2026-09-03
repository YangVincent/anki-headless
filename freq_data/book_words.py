#!/usr/bin/env python3
"""Candidate words for one book's screening page.

    book_words.py <book.jsonl> <book-name> <min occurrences> <out.json>

Writes the {w,n,py,m,z,c} records build_screen_page.py reads. Same filters
book_deck_eval.py counts with, so the page cannot disagree with the evaluation:
    - already known to the collection    -> dropped
    - scored a character name            -> dropped
    - listed in names_manual.json        -> dropped
    - absent from CC-CEDICT              -> dropped (nothing to put on a card)
`c` records what the collection already holds, so the page can say how many need a
new note rather than implying every tile is one.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import anki_cache as ac                      # noqa: E402
import anki_coverage as ak                   # noqa: E402
import coldwindow_words as cw                # noqa: E402
import name_filter as nf                     # noqa: E402


def main():
    from wordfreq import zipf_frequency
    src, book, minimum, out = Path(sys.argv[1]), sys.argv[2], int(sys.argv[3]), Path(sys.argv[4])
    rows = [json.loads(l) for l in src.read_text(encoding="utf-8").splitlines() if l.strip()]
    text, _ = ak.to_simplified("\n".join(r.get("text", "") for r in rows))

    cedict, surnames = nf.load_cedict()
    gloss = cw.cedict_entries()
    k = ak.load()
    counts, tags = cw.profile(text)
    total = sum(counts.values())
    manual = set(json.loads(
        (Path(__file__).resolve().parent / "gen_coldwindow" / "names_manual.json")
        .read_text(encoding="utf-8")).get(book, []))

    con = ac.connect_ro()
    cards = {}
    for r in con.execute("select simplified, deck, role, status from words"):
        w = r["simplified"]
        if ac._is_plain_word(w):
            cards.setdefault(w, []).append((r["deck"], r["role"], r["status"]))

    def bucket(cs):
        if not cs:
            return "none"
        if any(role != "archive" and st != "new" for _, role, st in cs):
            return "studied"
        if any(role != "archive" for _, role, _ in cs):
            return "queued"
        return "archive"

    recs, dropped_name = [], 0
    for w, n in counts.items():
        if n < minimum or w in k.known:
            continue
        if w in manual:
            dropped_name += 1
            continue
        if nf.score(w, n, total, zipf_frequency(w, "zh"),
                    tags.get(w, set()), cedict, surnames)[0] >= nf.THRESHOLD:
            dropped_name += 1
            continue
        if w not in cedict:
            continue
        py, m = gloss.get(w, ("", ""))
        recs.append({"w": w, "n": n, "py": py, "m": (m or "")[:90],
                     "z": round(zipf_frequency(w, "zh"), 1), "c": bucket(cards.get(w))})
    recs.sort(key=lambda r: -r["n"])
    out.write_text(json.dumps(recs, ensure_ascii=False, indent=0), encoding="utf-8")

    import collections
    by = collections.Counter(r["c"] for r in recs)
    print(f"《{book}》 {minimum}+ occurrences -> {len(recs)} candidates  ({out})")
    print(f"  names dropped: {dropped_name}")
    for key, label in (("none", "no card anywhere"), ("queued", "queued in a live deck"),
                       ("archive", "parked in Archive"), ("studied", "already studied")):
        print(f"    {label:24s} {by.get(key, 0):5d}")


if __name__ == "__main__":
    main()
