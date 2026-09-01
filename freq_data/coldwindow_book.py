#!/usr/bin/env python3
"""Fetch every free chapter of one jjwxc novel, as JSONL — one chapter per line.

coldwindow_fetch.py takes three chapters per work, which is a difficulty sample. A
reader import and a study list need the whole book, so this takes the lot.

Usage: coldwindow_book.py <novelid> <slug> [--simplified] [--max N]

A chapter whose text is under MIN_CHARS is a placeholder, not a chapter. 《十年》 has
nine of them: the author emptied those chapters in 2010 and left a censorship note.
"""
import json, re, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import coldwindow_fetch as cf
import anki_coverage as ak

OUT = Path(__file__).resolve().parent / "gen_coldwindow" / "books"
MIN_CHARS = 500


def main():
    novelid, slug = sys.argv[1], sys.argv[2]
    simplify = "--simplified" in sys.argv
    cap = int(sys.argv[sys.argv.index("--max") + 1]) if "--max" in sys.argv else None
    OUT.mkdir(parents=True, exist_ok=True)
    book = f"https://www.jjwxc.net/onebook.php?novelid={novelid}"
    data = cf.get(book)
    if not data:
        sys.exit("book page failed")
    s = cf.soup(data, "gb18030")
    title = (s.select_one("#novelinfo h1, span[itemprop=name]") or s.title).get_text(strip=True)
    intro = s.select_one("#novelintro")
    ids = []
    for a in s.find_all("a", href=True):
        m = re.search(r"chapterid=(\d+)", a["href"])
        if m and m.group(1) not in ids:
            ids.append(m.group(1))
    print(f"{title}: {len(ids)} chapter links")

    rows = []
    for cid in (ids[:cap] if cap else ids):
        cd = cf.get(f"https://www.jjwxc.net/onebook.php?novelid={novelid}&chapterid={cid}",
                    referer=book)
        if not cd:
            continue
        cs = cf.soup(cd, "gb18030")
        node = cs.select_one(cf.JJ_TEXT)
        if not node:
            print(f"  chapter {cid}: no text (locked?)")
            continue
        text = node.get_text("\n", strip=True)
        heading = cs.select_one("div.noveltext > div:nth-of-type(2)")
        if len(text) < MIN_CHARS:
            print(f"  chapter {cid}: {len(text)} chars — placeholder, skipped")
            continue
        rows.append({"chapter": int(cid), "title": heading.get_text(strip=True) if heading else "",
                     "text": text})
        print(f"  chapter {cid}: {len(text)} chars")
        time.sleep(1.0)

    raw = "\n".join(r["text"] for r in rows)
    converted = False
    if simplify:
        for r in rows:
            r["text"], converted = ak.to_simplified(r["text"])
        raw = "\n".join(r["text"] for r in rows)

    path = OUT / f"{slug}.jsonl"
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    meta = {"novelid": novelid, "title": title, "chapters": len(rows), "chars": len(raw),
            "simplified": converted,
            "blurb": intro.get_text("\n", strip=True) if intro else "",
            "source": book}
    (OUT / f"{slug}.meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1),
                                           encoding="utf-8")
    print(f"\n{len(rows)} chapters, {len(raw):,} chars -> {path}")


if __name__ == "__main__":
    main()
