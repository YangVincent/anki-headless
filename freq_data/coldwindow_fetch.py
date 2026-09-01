#!/usr/bin/env python3
"""Fetch Chinese source text for the works in the Cold Window webnovel guide.

Reads the entry list produced by coldwindow_parse (title/author/links) and
pulls, per work, whatever Chinese text the host serves in plain HTML:

  jjwxc      blurb (文案) + the free chapters listed on the book page
  qidian     blurb only; chapter text needs JS and an obfuscated font
  others     blurb or article body, best effort

Writes gen_coldwindow/samples.json with one record per work, and keeps the raw
HTML under gen_coldwindow/raw/ so a parser change does not mean re-fetching.
"""
import json, re, sys, time, hashlib
from pathlib import Path
from urllib.parse import urlparse, parse_qs
import urllib.request, urllib.error

HERE = Path(__file__).resolve().parent
OUT = HERE / "gen_coldwindow"
RAW = OUT / "raw"
DELAY = 1.5

UA_DESKTOP = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
UA_MOBILE = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
             "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1")


def get(url, ua=UA_DESKTOP, referer=None, timeout=30):
    """Fetch a URL and cache the bytes under raw/. Returns bytes or None."""
    key = hashlib.sha1(url.encode()).hexdigest()[:16]
    cached = RAW / f"{key}.html"
    if cached.exists():
        return cached.read_bytes()
    req = urllib.request.Request(url, headers={
        "User-Agent": ua,
        "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.5",
        **({"Referer": referer} if referer else {}),
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = r.read()
    except Exception as e:
        print(f"    fetch failed: {type(e).__name__}: {e}", file=sys.stderr)
        return None
    cached.write_bytes(data)
    time.sleep(DELAY)
    return data


def soup(data, encoding=None):
    from bs4 import BeautifulSoup
    if encoding:
        text = data.decode(encoding, "replace")
    else:
        text = data.decode("utf-8", "replace")
        if text.count("�") > len(text) / 200:
            text = data.decode("gb18030", "replace")
    return BeautifulSoup(text, "html.parser")


# jjwxc wraps the story text of a chapter in its own div, inside div.noveltext
# alongside bookmark, report and author-note widgets. Take the inner div; the
# chapter heading it sits next to also appears in the footer nav, so a text-level
# cut on 第N章 trims the wrong end.
JJ_TEXT = "#paragraph_comment_content"


def jjwxc(url):
    m = re.search(r"(?:novelid=|/book2/)(\d+)", url)
    if not m:
        return None
    nid = m.group(1)
    book = f"https://www.jjwxc.net/onebook.php?novelid={nid}"
    data = get(book)
    if not data:
        return None
    s = soup(data, "gb18030")
    intro = s.select_one("#novelintro")
    blurb = intro.get_text("\n", strip=True) if intro else ""
    ids = []
    for a in s.find_all("a", href=True):
        cm = re.search(r"chapterid=(\d+)", a["href"])
        if cm and cm.group(1) not in ids:
            ids.append(cm.group(1))
    chapters = []
    for cid in ids[:3]:
        cd = get(f"https://www.jjwxc.net/onebook.php?novelid={nid}&chapterid={cid}", referer=book)
        if not cd:
            continue
        cs = soup(cd, "gb18030")
        node = cs.select_one(JJ_TEXT)
        if not node:
            continue
        chapters.append(node.get_text("\n", strip=True))
    return {"source": "jjwxc", "blurb": blurb, "chapters": chapters}


def qidian(url):
    m = re.search(r"/book/(\d+)", url)
    if not m:
        return None
    data = get(f"https://m.qidian.com/book/{m.group(1)}/", ua=UA_MOBILE)
    if not data:
        return None
    s = soup(data)
    node = s.select_one(".detail__summary") or s.select_one(".book-intro")
    return {"source": "qidian", "blurb": node.get_text("\n", strip=True) if node else "", "chapters": []}


def generic(url):
    """Best effort for hosts with no dedicated handler."""
    ua = UA_MOBILE if "//m." in url else UA_DESKTOP
    data = get(url, ua=ua)
    if not data:
        return None
    s = soup(data)
    for tag in s(["script", "style", "nav", "header", "footer"]):
        tag.decompose()
    # Longest run of CJK-heavy paragraphs is the best guess at the body.
    paras = [p.get_text(" ", strip=True) for p in s.find_all(["p", "div"])]
    paras = [p for p in paras if len(p) > 30 and len(re.findall(r"[一-鿿]", p)) > len(p) * 0.5]
    paras.sort(key=len, reverse=True)
    host = urlparse(url).netloc
    return {"source": host, "blurb": paras[0][:2000] if paras else "", "chapters": []}


HANDLERS = [
    ("jjwxc.net", jjwxc),
    ("qidian.com", qidian),
]


def handler_for(url):
    host = urlparse(url).netloc
    for frag, fn in HANDLERS:
        if host.endswith(frag):
            return fn
    return generic


def main():
    entries = json.loads((OUT / "entries.json").read_text(encoding="utf-8"))
    for i, e in enumerate(entries, 1):
        url = e.get("zh_url") or ""
        print(f"[{i:2d}/{len(entries)}] {e['title_zh']}  {urlparse(url).netloc or '(no source)'}")
        if not url:
            e["sample"] = None
            continue
        try:
            e["sample"] = handler_for(url)(url)
        except Exception as ex:
            print(f"    parse failed: {type(ex).__name__}: {ex}", file=sys.stderr)
            e["sample"] = None
        s = e.get("sample")
        if s:
            n = len(s["blurb"]) + sum(len(c) for c in s["chapters"])
            print(f"    {s['source']}: blurb {len(s['blurb'])} chars, "
                  f"{len(s['chapters'])} chapters, {n} chars total")
    (OUT / "samples.json").write_text(
        json.dumps(entries, ensure_ascii=False, indent=1), encoding="utf-8")
    ok = sum(1 for e in entries if e.get("sample") and e["sample"]["blurb"])
    print(f"\nwrote {OUT/'samples.json'}: {ok}/{len(entries)} works have Chinese text")


if __name__ == "__main__":
    main()
