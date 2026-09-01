#!/usr/bin/env python3
"""Rank the Cold Window guide's webnovels by how hard they are for Vincent to read.

Reads gen_coldwindow/samples.json (written by coldwindow_fetch.py) and scores each
work with the same tap-calibrated metric difficulty_report.py prints for one book.

It prints two rankings, because they answer two questions:

  frequency   how rare is this text's vocabulary, against the words he taps in the
              reader (difficulty_report.py)
  collection  how much of it is vocabulary his Anki collection says he has learned,
              and how much of the rest is built from characters he has already met
              (anki_coverage.py)

A sample is either free chapters (jjwxc) or a publisher blurb (everywhere else).
A blurb is short and its register is not the register of the body, so the report
separates the two and never ranks a blurb against a chapter.
"""
import json, sys
from pathlib import Path
import difficulty_report as dr
import anki_coverage as ak

HERE = Path(__file__).resolve().parent
OUT = HERE / "gen_coldwindow"
PAGE = 1000        # one "page" = 1000 characters, so per-page rates compare across works
MIN_TOKENS = 150   # below this a percentage is noise
#: Scored in the same run as the novels, so the collection percentages — which run high
#: for the reason anki_coverage.band() records — read against something known.
ANCHOR = (HERE / "incoming" / "charlottes_web.jsonl", "夏洛的网")


def main():
    entries = json.loads((OUT / "samples.json").read_text(encoding="utf-8"))
    frontier, tapped, n_tap = dr.tap_frontier()
    knowledge = ak.load()
    # Character names, flagged per book by coldwindow_words.py. jieba's own tagger
    # misses 边烬 and 冉禁, and an unfiltered name reads as a hard unknown word 100+
    # times over. Both scorers get the same list, so the two rankings stay comparable.
    names_file = OUT / "names_by_book.json"
    names = json.loads(names_file.read_text(encoding="utf-8")) if names_file.exists() else {}
    if not names:
        print("no names_by_book.json — run coldwindow_words.py first", file=sys.stderr)
    ref_text = "\n".join(json.loads(ln).get("text", "")
                         for ln in ANCHOR[0].read_text(encoding="utf-8").splitlines() if ln.strip())
    anchor = ak.cover(ref_text, knowledge)   # the reference book carries its own name list
    print(f"collection: {len(knowledge.known)} words learned, {len(knowledge.queued)} queued, "
          f"{len(knowledge.chars)} characters met inside a learned word", file=sys.stderr)
    print(f"lookup frontier: Zipf {frontier:.2f} (median of {n_tap} words you looked up)\n",
          file=sys.stderr)

    rows = []
    for e in entries:
        s = e.get("sample")
        if not s:
            continue
        if s["chapters"]:
            text, kind = "\n".join(s["chapters"]), "chapters"
        elif s["blurb"]:
            text, kind = s["blurb"], "blurb"
        else:
            continue
        text, converted = ak.to_simplified(text)
        if converted:
            print(f"  {e['title_zh']}: traditional source, converted to simplified",
                  file=sys.stderr)
        drop = set(names.get(e["title_zh"], ()))
        r = dr.score(text, max(len(text) // PAGE, 1), tapped, frontier,
                     proper=dr.PROPER | drop)
        if r["tokens"] < MIN_TOKENS:
            kind = "too short"
        a = ak.cover(text, knowledge, drop=drop)
        rows.append({
            "anki": a,
            "title": e["title_zh"], "author": e["author_zh"], "rec_by": e["rec_by"],
            "title_en": e["title_en"], "url": e["zh_url"], "kind": kind,
            "chars": len(text), "tokens": r["tokens"], "unique": r["unique"],
            "firm_pct": r["firm_pct"], "lookup_pct": r["lookup_pct"],
            "effective": r["effective"], "band": dr.band(r["effective"]),
            "cov40": r["cov"][4.0], "cov30": r["cov"][3.0],
            "per_page": r["lookup_tok"] / max(r["pages"], 1),
            "top": sorted(r["lookup"].items(), key=lambda x: -x[1])[:12],
        })

    (OUT / "difficulty.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")

    for kind, header in (("chapters", "FROM FREE CHAPTERS (~10k chars each) — reliable"),
                         ("blurb", "FROM THE BLURB ONLY — indicative, not a ranking"),
                         ("too short", "SAMPLE TOO SHORT TO SCORE")):
        group = sorted([r for r in rows if r["kind"] == kind], key=lambda r: r["effective"])
        if not group:
            continue
        print(f"\n=== {header} ===")
        print(f"{'title':<18}{'author':<12}{'chars':>7}{'≥4.0':>6}{'<3.0':>6}"
              f"{'eff%':>6}{'/1k':>6}  verdict")
        for r in group:
            print(f"{r['title']:<18}{r['author']:<12}{r['chars']:>7}{r['cov40']:>6.0f}"
                  f"{r['firm_pct']:>6.1f}{r['effective']:>6.1f}{r['per_page']:>6.0f}"
                  f"  {r['band'].split(' — ')[0]}")

    group = sorted([r for r in rows if r["kind"] == "chapters"],
                   key=lambda r: r["anki"]["opaque_pct"])
    print(f"\n=== AGAINST YOUR COLLECTION — free chapters only ===")
    print(f"{'title':<18}{'author':<12}{'known%':>7}{'guess%':>7}{'new%':>6}"
          f"{'newchr%':>8}  vs 夏洛的网")
    for r in group + [{"title": ANCHOR[1], "author": "(reference)", "anki": anchor}]:
        a = r["anki"]
        label = "— reference —" if r["author"] == "(reference)" else \
            ak.band(a["opaque_pct"], anchor["opaque_pct"])
        print(f"{r['title']:<18}{r['author']:<12}{a['coverage']:>7.1f}"
              f"{a['transparent_pct']:>7.1f}{a['opaque_pct']:>6.1f}"
              f"{a['unseen_char_pct']:>8.1f}  {label}")

    print(f"\nwrote {OUT/'difficulty.json'}")


if __name__ == "__main__":
    main()
