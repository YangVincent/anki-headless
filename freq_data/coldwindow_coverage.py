#!/usr/bin/env python3
"""How much of each novel can actually be read, per source. No guessing, no probing.

jjwxc publishes the whole answer on the book page. Every chapter is one table row
carrying schema.org markup:

    free      <a href="...chapterid=N" itemprop="url">
    paid      <a id="vip_N" onclick="vip_buy('vip_N')">   — no href
    length    <td itemprop="wordCount">

So free-versus-paid and the length of each chapter both come from one cached page.

A free chapter is not always a readable one. 《十年》 lists ten free chapters whose
word counts are 15 to 32: the author emptied them in 2010 and left a censorship note,
`春风吹来大河蟹，看文只能靠百度`. MIN_WORDS separates a chapter from a placeholder.

Writes gen_coldwindow/coverage.json.
"""
import hashlib
import json
import re
from pathlib import Path
from urllib.parse import urlparse

from bs4 import BeautifulSoup

HERE = Path(__file__).resolve().parent
OUT = HERE / "gen_coldwindow"
RAW = OUT / "raw"
#: Below this a jjwxc chapter row is a placeholder, not a chapter.
MIN_WORDS = 500


def cached(url):
    p = RAW / (hashlib.sha1(url.encode()).hexdigest()[:16] + ".html")
    return p.read_bytes() if p.exists() else None


def jjwxc_chapters(novelid):
    """[(number, title, words, free)] for one book, from its cached page."""
    data = cached(f"https://www.jjwxc.net/onebook.php?novelid={novelid}")
    if not data:
        return None
    soup = BeautifulSoup(data.decode("gb18030", "replace"), "html.parser")
    out = []
    # Select on the row shape, not on itemprop="chapter". The most recently updated
    # chapter carries no itemprop, so an attribute selector silently drops it — that
    # undercounted 《十年》 by one chapter until it was caught.
    for tr in soup.find_all("tr"):
        tds = tr.find_all("td")
        if len(tds) < 4 or not re.match(r"^\d+$", tds[0].get_text(strip=True)):
            continue
        wc = tr.find("td", attrs={"itemprop": "wordCount"})
        words = int(re.sub(r"\D", "", wc.get_text(strip=True)) or 0) if wc else 0
        link = tds[1].find("a")
        free = bool(link and link.get("href"))
        head = tr.find("span", attrs={"itemprop": "headline"})
        out.append((int(tds[0].get_text(strip=True)),
                    head.get_text(" ", strip=True)[:40] if head else "", words, free))
    return out


def main():
    entries = json.loads((OUT / "entries.json").read_text(encoding="utf-8"))
    report = []
    for e in entries:
        url = e.get("zh_url", "")
        host = urlparse(url).netloc
        row = {"title": e["title_zh"], "author": e["author_zh"], "host": host,
               "serial": e["serial"], "url": url}
        m = re.search(r"(?:novelid=|/book2/)(\d+)", url) if "jjwxc" in host else None
        chapters = jjwxc_chapters(m.group(1)) if m else None
        if chapters:
            total = sum(w for _, _, w, _ in chapters)
            readable = sum(w for _, _, w, f in chapters if f and w >= MIN_WORDS)
            row.update(
                source="jjwxc", chapters=len(chapters), total_words=total,
                free_chapters=sum(1 for _, _, w, f in chapters if f and w >= MIN_WORDS),
                empty_free=sum(1 for _, _, w, f in chapters if f and w < MIN_WORDS),
                paid_chapters=sum(1 for _, _, _, f in chapters if not f),
                readable_words=readable,
                readable_pct=round(100 * readable / total, 1) if total else 0.0)
        else:
            row.update(source=host or "(no Chinese source)", chapters=None,
                       readable_pct=None)
        report.append(row)

    (OUT / "coverage.json").write_text(json.dumps(report, ensure_ascii=False, indent=1),
                                       encoding="utf-8")
    jj = [r for r in report if r.get("source") == "jjwxc"]
    jj.sort(key=lambda r: -r["readable_pct"])
    print(f"{'title':<20}{'chs':>5}{'free':>6}{'paid':>6}{'empty':>6}"
          f"{'readable words':>16}{'of book':>9}")
    for r in jj:
        print(f"{r['title']:<20}{r['chapters']:>5}{r['free_chapters']:>6}"
              f"{r['paid_chapters']:>6}{r['empty_free']:>6}"
              f"{r['readable_words']:>16,}{r['readable_pct']:>8.1f}%")
    print(f"\nwrote {OUT/'coverage.json'}")


if __name__ == "__main__":
    main()
