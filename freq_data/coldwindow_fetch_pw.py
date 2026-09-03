#!/usr/bin/env python3
"""Render the Chinese sources that plain HTTP cannot read, using Playwright.

coldwindow_fetch.py gets jjwxc with urllib. Three hosts need a real browser:

  qidian        the book page serves a blurb; chapter text arrives by JavaScript
  read.douban   the column page and the free part of each chapter need JavaScript
  gongzicp      the page is a JavaScript shell, blurb only

Two hosts stay out of reach on purpose:

  fanqienovel   serves logged-out readers a text with most characters removed
                (1.9% common-character share against ~13% for real prose)
  zhihu         the paid columns answer 404, and one story reads 内容已下架

Chapter text on qidian carries the per-paragraph reader comments (段评) inline, so
this takes the paragraph nodes and drops the comment nodes, never the page text.

Writes gen_coldwindow/samples_pw.json. Cached per book in gen_coldwindow/raw_pw/.
"""
import json, re, sys, time
from pathlib import Path
from urllib.parse import urlparse

HERE = Path(__file__).resolve().parent
OUT = HERE / "gen_coldwindow"
RAW = OUT / "raw_pw"
HAN = re.compile(r"[一-鿿]")
COMMON = "的了是我他在不有一人"
N_CHAPTERS = 3
DELAY = float(__import__("os").environ.get("COLDWINDOW_DELAY", "8"))  # seconds between works
MIN_HAN = 800          # a chapter under this is an announcement or a paywall stub

UA_MOBILE = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 "
             "(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1")
UA_DESKTOP = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/140.0 Safari/537.36")


class Blocked(Exception):
    """The host served a bot-protection page instead of the content."""


def check_blocked(pg):
    """Qidian sits behind a Tencent Cloud WAF that answers a too-fast client with
    an interception page. Stop that host rather than keep asking."""
    if "WAF" in (pg.title() or ""):
        raise Blocked("WAF interception page")
    head = pg.inner_text("body")[:200]
    if "请求已中断" in head or "访问拦截" in head:
        raise Blocked("access blocked page")


def save_page(pg, tag):
    """Write the raw page to raw_pw/ before anything parses it.

    A request against a rate-limited host is expensive and not repeatable on demand:
    Qidian's WAF blocks after roughly 26 loads in three minutes and clears on its own
    hours later. Every page fetched must therefore survive a parser bug, a selector
    change, or a probe that only wanted a character count -- Qidian chapter text was
    read seven separate times on 2026-09-01 and discarded seven times, each one paid for
    with a request. coldwindow_fetch.py has cached raw HTML since the beginning; this
    path did not, and that asymmetry is the whole reason those books still have no text.
    """
    RAW.mkdir(parents=True, exist_ok=True)
    out = RAW / (re.sub(r"\W+", "_", f"{tag}_{pg.url}")[:120] + ".html")
    try:
        out.write_text(pg.content(), encoding="utf-8")
    except Exception as e:              # never let caching break a fetch
        print(f"    (could not cache {out.name}: {type(e).__name__})")
    return out


def common_share(text):
    """Real Chinese prose runs about 12-14% on these ten characters. A site that
    degrades or re-encodes its text for logged-out readers falls near zero."""
    han = HAN.findall(text)
    if not han:
        return 0.0
    return 100 * sum(text.count(c) for c in COMMON) / len(han)


# Qidian marks each story paragraph with a data-pid. The reader comments sit in
# sibling nodes without one, which is what keeps them out of the text.
QIDIAN_JS = """() => {
  const nodes = document.querySelectorAll('p[data-pid], .content p, #chapterContent p');
  const out = [];
  for (const n of nodes) {
    if (n.closest('.comment, .review, .barrage, .note')) continue;
    const t = (n.innerText || '').trim();
    if (t && !/^\\d+$/.test(t)) out.push(t);
  }
  return out;
}"""

# The douban reader renders each paragraph into a node whose class name contains
# "paragraph"; it uses no <p> tags, so a p-selector returns an empty chapter.
DOUBAN_JS = """() => {
  return Array.from(document.querySelectorAll('[class*=paragraph]'))
    .map(n => (n.innerText || '').trim())
    .filter(t => t.length > 1);
}"""


# qidian renders the段评 count as a badge inside the paragraph node, so the count
# arrives as a bare-number line within the paragraph's own text.
NOISE = re.compile(r"^(?:\d+|[Pp][Ss][：:].*)$")
DROP = ("登录", "注册", "下载", "APP", "书架", "投诉", "举报", "分享",
        "上一章", "下一章", "目录", "本章字数", "更新时间", "加入书架")


def clean(paras):
    """Drop navigation chrome and comment-count badges, keep the prose."""
    keep = []
    for para in paras:
        for line in para.split("\n"):
            line = line.strip()
            if len(line) < 2 or NOISE.match(line):
                continue
            if len(line) < 20 and any(d in line for d in DROP):
                continue
            keep.append(line)
    return "\n".join(keep)


def qidian(pg, url, log):
    m = re.search(r"/book/(\d+)", url)
    if not m:
        return None
    bid = m.group(1)
    # The chapter pages only answer after the catalog visit sets up the context.
    pg.goto(f"https://m.qidian.com/book/{bid}/catalog/",
            wait_until="domcontentloaded", timeout=60000)
    pg.wait_for_timeout(3000)
    save_page(pg, "qidian-catalog")
    check_blocked(pg)
    links = pg.eval_on_selector_all(
        "a[href*='/chapter/']", "e => e.map(x => x.getAttribute('href') || '')")
    seen, chapters = set(), []
    for href in links:
        if len(chapters) >= N_CHAPTERS:
            break
        u = "https:" + href if href.startswith("//") else href
        if u in seen:
            continue
        seen.add(u)
        try:
            pg.goto(u, wait_until="domcontentloaded", timeout=60000)
            pg.wait_for_timeout(2500)
            save_page(pg, "qidian-chapter")
            check_blocked(pg)
            text = clean(pg.evaluate(QIDIAN_JS))
        except Blocked:
            raise
        except Exception as e:
            log(f"    chapter failed: {type(e).__name__}")
            continue
        n, share = len(HAN.findall(text)), common_share(text)
        if n < MIN_HAN:
            log(f"    skip ({n} han) — announcement or paywalled")
            continue
        if share < 6:
            log(f"    skip — text looks re-encoded ({share:.1f}% common)")
            continue
        chapters.append(text)
        log(f"    chapter ok: {n} han, {share:.1f}% common")
    return {"source": "qidian-pw", "blurb": "", "chapters": chapters}


def douban(pg, url, log):
    pg.goto(url, wait_until="domcontentloaded", timeout=60000)
    pg.wait_for_timeout(3500)
    save_page(pg, "douban-column")
    links = pg.eval_on_selector_all(
        "a[href*='/chapter/']", "e => e.map(x => x.getAttribute('href') || '')")
    seen, chapters = set(), []
    for href in links:
        if len(chapters) >= N_CHAPTERS:
            break
        u = "https://read.douban.com" + href if href.startswith("/") else href
        base = u.split("?")[0]
        if base in seen:
            continue
        seen.add(base)
        try:
            pg.goto(u, wait_until="domcontentloaded", timeout=60000)
            pg.wait_for_timeout(3500)
            save_page(pg, "douban-chapter")
            text = clean(pg.evaluate(DOUBAN_JS))
        except Exception as e:
            log(f"    chapter failed: {type(e).__name__}")
            continue
        n, share = len(HAN.findall(text)), common_share(text)
        if n < 300:     # douban shows a free part of each chapter, shorter than a qidian one
            log(f"    skip ({n} han)")
            continue
        chapters.append(text)
        log(f"    chapter ok: {n} han, {share:.1f}% common")
    return {"source": "douban-pw", "blurb": "", "chapters": chapters}


def gongzicp(pg, url, log):
    pg.goto(url, wait_until="domcontentloaded", timeout=60000)
    pg.wait_for_timeout(3500)
    try:
        blurb = pg.eval_on_selector(".novel-intro, .intro, .book-desc", "e => e.innerText")
    except Exception:
        body = pg.inner_text("body")
        parts = [p.strip() for p in body.split("\n") if len(p.strip()) > 25 and HAN.search(p)]
        blurb = max(parts, key=len) if parts else ""
    log(f"    blurb only: {len(HAN.findall(blurb))} han (reading needs a login)")
    return {"source": "gongzicp-pw", "blurb": blurb.strip(), "chapters": []}


HANDLERS = [("qidian.com", qidian, UA_MOBILE),
            ("read.douban.com", douban, UA_DESKTOP),
            ("gongzicp.com", gongzicp, UA_DESKTOP)]


def handler_for(url):
    host = urlparse(url).netloc
    for frag, fn, ua in HANDLERS:
        if host.endswith(frag):
            return fn, ua
    return None, None


def main():
    from playwright.sync_api import sync_playwright
    RAW.mkdir(parents=True, exist_ok=True)
    entries = json.loads((OUT / "entries.json").read_text(encoding="utf-8"))
    todo = [e for e in entries if handler_for(e.get("zh_url", ""))[0]]
    print(f"{len(todo)} works need a browser\n")

    results, blocked = {}, set()
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        for i, e in enumerate(todo, 1):
            url = e["zh_url"]
            cache = RAW / (re.sub(r"\W+", "_", url)[:80] + ".json")
            if cache.exists():
                results[url] = json.loads(cache.read_text(encoding="utf-8"))
                print(f"[{i:2d}/{len(todo)}] {e['title_zh']} — cached")
                continue
            if urlparse(url).netloc in blocked:
                print(f"[{i:2d}/{len(todo)}] {e['title_zh']} — host blocked, skipped")
                continue
            fn, ua = handler_for(url)
            print(f"[{i:2d}/{len(todo)}] {e['title_zh']}  {urlparse(url).netloc}")
            ctx = browser.new_context(
                locale="zh-CN", user_agent=ua,
                viewport={"width": 390, "height": 844} if ua is UA_MOBILE
                else {"width": 1280, "height": 900},
                is_mobile=ua is UA_MOBILE, has_touch=ua is UA_MOBILE)
            pg = ctx.new_page()
            try:
                s = fn(pg, url, lambda m: print(m, flush=True))
            except Blocked as ex:
                print(f"    BLOCKED: {ex} — skipping the rest of this host")
                blocked.add(urlparse(url).netloc)
                s = None
            except Exception as ex:
                print(f"    FAILED: {type(ex).__name__}: {ex}")
                s = None
            ctx.close()
            if s and (s["chapters"] or s["blurb"]):
                cache.write_text(json.dumps(s, ensure_ascii=False), encoding="utf-8")
                results[url] = s
                total = sum(len(c) for c in s["chapters"])
                print(f"    -> {len(s['chapters'])} chapters, {total} chars")
            time.sleep(DELAY)
        browser.close()

    # Fold the browser results into the samples the difficulty report reads.
    samples = json.loads((OUT / "samples.json").read_text(encoding="utf-8"))
    merged = 0
    for e in samples:
        s = results.get(e.get("zh_url", ""))
        if not s:
            continue
        old = e.get("sample") or {"blurb": "", "chapters": []}
        if s["chapters"]:
            e["sample"] = {"source": s["source"], "blurb": old["blurb"],
                           "chapters": s["chapters"]}
            merged += 1
        elif s["blurb"] and len(s["blurb"]) > len(old["blurb"]):
            e["sample"] = {"source": s["source"], "blurb": s["blurb"], "chapters": []}
    (OUT / "samples.json").write_text(
        json.dumps(samples, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nmerged chapter text into {merged} works; updated {OUT/'samples.json'}")


if __name__ == "__main__":
    main()
