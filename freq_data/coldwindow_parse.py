#!/usr/bin/env python3
"""Parse the Cold Window guide's single-page version into one record per work.

Source: https://coldwindow.substack.com/p/single-page-version-the-cold-window
Each recommendation ends with a fixed four-line block:

    作者《书名》
    English Title by Romanized Author
    Serialized 2024-2025 (173 chapters)
    Original Chinese at JJWCX // Translation by Douqi     <- the links

So the 作者《书名》 line is the anchor. A 《》 inside a prose paragraph is not one,
because the anchor line holds nothing else.

Writes gen_coldwindow/entries.json, which coldwindow_fetch.py reads.
"""
import json, re, sys
from pathlib import Path
from urllib.parse import urlparse
from bs4 import BeautifulSoup

HERE = Path(__file__).resolve().parent
OUT = HERE / "gen_coldwindow"

CJK = re.compile(r"[一-鿿]")
ANCHOR = re.compile(r"^(.*?)《(.+?)》\s*$")
SERIAL = re.compile(r"^(Serialized|Serialised|Published|Ongoing|Completed)", re.I)

# Hosts that serve the Chinese original. novelupdates and the English publishers
# describe a translation, so they are not a text source.
ZH_HOSTS = ("jjwxc.net", "qidian.com", "zhihu.com", "read.douban.com",
            "gongzicp.com", "fanqienovel.com", "baijiahao.baidu.com", "weibo.com")


def parse(html):
    soup = BeautifulSoup(html, "html.parser")
    body = soup.select_one("div.available-content") or soup.select_one("div.body")
    if body is None:
        sys.exit("article body not found — the page markup changed")

    els = body.find_all(["h1", "h2", "h3", "h4", "p"])
    entries, who = [], None
    for i, e in enumerate(els):
        text = e.get_text(" ", strip=True)
        if e.name in ("h2", "h3"):
            who = text
        m = ANCHOR.match(text)
        if not (m and len(text) < 40 and CJK.search(text)):
            continue
        title_en, serial, links = "", "", []
        for b in els[i + 1:i + 5]:
            bt = b.get_text(" ", strip=True)
            if SERIAL.match(bt):
                serial = bt
            elif b.find("a") and ("//" in bt or " at " in bt):
                links = [{"label": a.get_text(" ", strip=True), "url": a["href"]}
                         for a in b.find_all("a", href=True)]
                break
            elif not title_en and bt:
                title_en = bt
        zh = [l["url"] for l in links
              if urlparse(l["url"]).netloc.endswith(ZH_HOSTS)]
        entries.append({"rec_by": who, "title_zh": m.group(2).strip(),
                        "author_zh": m.group(1).strip(), "title_en": title_en,
                        "serial": serial, "links": links,
                        "zh_url": zh[0] if zh else ""})
    return entries


def main():
    html = Path(sys.argv[1]).read_text(encoding="utf-8", errors="replace")
    entries = parse(html)
    OUT.mkdir(exist_ok=True)
    (OUT / "entries.json").write_text(
        json.dumps(entries, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(entries)} works, "
          f"{sum(1 for e in entries if e['zh_url'])} with a Chinese source, "
          f"{len({e['rec_by'] for e in entries})} recommenders")


if __name__ == "__main__":
    main()
