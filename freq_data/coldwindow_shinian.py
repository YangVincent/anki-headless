#!/usr/bin/env python3
"""Assemble 《十年》 by 暗夜流光 from the three places its parts survive.

jjwxc emptied chapters 2-11 in 2010 and the author left a note in their place; see
gen_coldwindow/coverage.json. The parts now come from:

    chapters 1-10   bailushuyuan.org      traditional
    番外：我们的生活   the Douban thread      simplified
    特典：记忆之森     jjwxc, still official  traditional (already cached)

VERIFICATION IS THE POINT. jjwxc emptied the chapter bodies but left a preview line for
every chapter in its table of contents. That gives an official fragment of each deleted
chapter to check a copy against, so "is this the real text" is a measurement, not a hope.
Every chapter must match its preview or this script refuses to write the file.

Everything is converted to simplified, because the Anki collection and the lookup tools
are simplified. The traditional original is kept in a `traditional` field per chapter.

Usage: coldwindow_shinian.py [--out gen_coldwindow/books/shinian_full.jsonl]
"""
import hashlib
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

from bs4 import BeautifulSoup

import anki_coverage as ak

HERE = Path(__file__).resolve().parent
OUT = HERE / "gen_coldwindow"
RAW = OUT / "raw"
NOVELID = "379903"
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/126.0 Safari/537.36")

#: bailushuyuan's ids are not in chapter order, so they are mapped by label, never by
#: position — reading them in link order served 第九章 as chapter 10.
BAILU = {1: 255719, 2: 255721, 3: 255722, 4: 255723, 5: 255724,
         6: 255725, 7: 255726, 8: 255727, 9: 255728, 10: 255720}
BAILU_URL = "https://bailushuyuan.org/novel/traditional/chapters/{}"
DOUBAN_URL = "https://www.douban.com/group/topic/27602264/"

#: The site appends its own navigation to the chapter body. Cut at the first marker.
CHROME = ("查看全部", "作家暗夜流光介紹", "暗夜流光全集", "上一章", "下一章", "加入書籤")
#: A Douban reply carries a "<poster> 楼主 <timestamp>" header before the text.
REPLY_HEAD = re.compile(r"^.{0,12}?楼主\s*\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\s*")


def fetch(url, timeout=30):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9"})
    return urllib.request.urlopen(req, timeout=timeout).read()


def longest_text(soup):
    for tag in soup(["script", "style", "nav", "header", "footer"]):
        tag.decompose()
    parts = [d.get_text("\n", strip=True) for d in soup.find_all(["div", "article", "section"])]
    return max(parts, key=len) if parts else ""


def strip_chrome(text):
    cut = min((text.find(m) for m in CHROME if text.find(m) > 200), default=-1)
    return (text[:cut] if cut > 0 else text).strip()


def jjwxc_previews():
    """{chapter number: (title, preview line)} from the cached jjwxc book page.

    These survive the emptied bodies, so they are the reference every copy is checked
    against. The page is GBK; Anki's collection and everything downstream is not.
    """
    key = hashlib.sha1(
        f"https://www.jjwxc.net/onebook.php?novelid={NOVELID}".encode()).hexdigest()[:16]
    path = RAW / f"{key}.html"
    if not path.exists():
        sys.exit(f"jjwxc book page not cached at {path}; run coldwindow_fetch.py first")
    soup = BeautifulSoup(path.read_bytes().decode("gb18030", "replace"), "html.parser")
    out = {}
    for tr in soup.find_all("tr"):
        tds = tr.find_all("td")
        if len(tds) >= 4 and re.match(r"^\d+$", tds[0].get_text(strip=True)):
            out[int(tds[0].get_text(strip=True))] = (
                tds[1].get_text(" ", strip=True), tds[2].get_text(" ", strip=True))
    return out


def han(text):
    return re.sub(r"[^一-鿿]", "", text)


def matches(preview, body, width=12):
    """True when the preview's opening survives in the body. Both are normalised to
    simplified first: the copies differ from jjwxc on variant characters — 干 for 幹 —
    which is not a difference in the text."""
    p, _ = ak.to_simplified(preview, force=True)
    b, _ = ak.to_simplified(body, force=True)
    return han(p)[:width] in han(b)[:600]


def douban_extra():
    """番外：我们的生活, from the thread where the poster serialised the novel."""
    cache = RAW / "douban_27602264.html"
    if not cache.exists():
        cache.write_bytes(fetch(DOUBAN_URL))
    soup = BeautifulSoup(cache.read_text(encoding="utf-8", errors="replace"), "html.parser")
    seen = set()
    for node in soup.select(".reply-doc") or soup.select("li.clearfix"):
        text = node.get_text(" ", strip=True)
        if text in seen:
            continue
        seen.add(text)
        if "我们的生活" in text and "闹钟" in text:
            return REPLY_HEAD.sub("", text).strip()
    return None


def jjwxc_bonus():
    """特典：记忆之森 — chapter 12, which jjwxc still serves."""
    rows = [json.loads(l) for l in
            (OUT / "books" / "shinian.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    for r in rows:
        if "记忆之森" in r.get("title", "") or r.get("chapter") == 12:
            return r["text"]
    return None


def main():
    out_path = Path(sys.argv[sys.argv.index("--out") + 1]) if "--out" in sys.argv \
        else OUT / "books" / "shinian_full.jsonl"
    prev = jjwxc_previews()
    chapters, failures = [], []

    for n in range(1, 11):
        soup = BeautifulSoup(fetch(BAILU_URL.format(BAILU[n])).decode("utf-8", "replace"),
                             "html.parser")
        body = strip_chrome(longest_text(soup))
        title, preview = prev[n]
        # jjwxc's row 1 preview is the 文案, not the chapter, so chapter 1 is checked
        # against the chapter-1 text jjwxc still serves instead.
        ref = preview if n > 1 else "你叫高郁？是那个忧郁的郁？"
        ok = matches(ref, body)
        print(f"  ch{n:<3}{title[:16]:<18}{len(body):>7} chars   verified: {ok}")
        if not ok:
            failures.append(n)
        chapters.append({"chapter": n, "title": title, "raw": body})
        time.sleep(1.2)

    extra = douban_extra()
    if extra:
        ok = matches(prev[11][1], extra)
        print(f"  ch11 {prev[11][0][:16]:<17}{len(extra):>7} chars   verified: {ok}")
        if not ok:
            failures.append(11)
        chapters.append({"chapter": 11, "title": prev[11][0], "raw": extra})
    else:
        print("  ch11 番外：我们的生活   NOT FOUND in the thread")

    bonus = jjwxc_bonus()
    if bonus:
        print(f"  ch12 {prev[12][0][:16]:<17}{len(bonus):>7} chars   verified: official")
        chapters.append({"chapter": 12, "title": prev[12][0], "raw": bonus})

    if failures:
        sys.exit(f"\nREFUSING TO WRITE: chapters {failures} do not match jjwxc's preview. "
                 "A copy that fails this check is a different text, not this novel.")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    with open(out_path, "w", encoding="utf-8") as f:
        for c in chapters:
            simplified, converted = ak.to_simplified(c["raw"])
            total += len(simplified)
            f.write(json.dumps({"chapter": c["chapter"], "title": c["title"],
                                "text": simplified,
                                "traditional": c["raw"] if converted else ""},
                               ensure_ascii=False) + "\n")
    print(f"\n{len(chapters)} chapters, {total:,} characters -> {out_path}")


if __name__ == "__main__":
    main()
