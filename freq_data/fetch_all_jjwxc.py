#!/usr/bin/env python3
"""Fetch every FREE chapter of every jjwxc book in the guide, not a sample of three.

The difficulty ranking was built on 3-chapter samples. Sample size then turned out to be
its largest error source: a full text scores up to 4.7 points easier than three chapters
of it, because early chapters introduce the setting and later ones reuse it. Eleven books
still had 11 to 26 free chapters sitting unfetched -- 215 in total -- so every score below
the top four rested on about a tenth of the freely available text.

coldwindow_fetch.get() caches by URL, so chapters already on disk cost no request.

Usage: fetch_all_jjwxc.py [--min-gap N]
"""
import json
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "gen_coldwindow"


def slug_for(title, novelid):
    """A filename that cannot collide and stays readable: the novel id carries identity."""
    return f"jj{novelid}"


def main():
    entries = json.loads((OUT / "entries.json").read_text(encoding="utf-8"))
    coverage = {r["title"]: r for r in
                json.loads((OUT / "coverage.json").read_text(encoding="utf-8"))}
    done = {"十年", "桥头楼上", "女主对此感到厌烦", "穆小姐与金丝雀"}

    todo = []
    for e in entries:
        url = e.get("zh_url", "")
        m = re.search(r"(?:novelid=|/book2/)(\d+)", url) if "jjwxc" in url else None
        if not m or e["title_zh"] in done:
            continue
        free = (coverage.get(e["title_zh"]) or {}).get("free_chapters") or 0
        if free:
            todo.append((e["title_zh"], m.group(1), free))
    todo.sort(key=lambda t: -t[2])

    print(f"{len(todo)} books, {sum(t[2] for t in todo)} free chapters to collect\n",
          flush=True)
    for i, (title, nid, free) in enumerate(todo, 1):
        slug = slug_for(title, nid)
        print(f"[{i}/{len(todo)}] {title} (novelid {nid}, {free} free)", flush=True)
        r = subprocess.run(
            [sys.executable, str(HERE / "coldwindow_book.py"), nid, slug, "--simplified"],
            capture_output=True, text=True)
        tail = [l for l in r.stdout.splitlines() if "->" in l or "chars" in l][-1:]
        print(f"    {tail[0].strip() if tail else r.stderr.strip()[:100]}", flush=True)


if __name__ == "__main__":
    main()
