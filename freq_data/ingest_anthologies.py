#!/usr/bin/env python3
"""Split TOC-bearing prose anthologies into per-chapter stories and ingest into
dongchinese.db. Skips front/back matter. --apply to insert; preview otherwise.
Appends inserted ids to freq_data/ingested_reader_ids.json."""
import fitz, re, json, sqlite3, sys
from datetime import datetime, timezone

APPLY = "--apply" in sys.argv
DB = "/home/vincent/chinese-projects/dong-chinese/server/dongchinese.db"
TB = "/home/vincent/anki-headless/freq_data/textbooks/Learning Mandarin Material (DO NOT SELL) @binkybing/"
KEEP = re.compile(r'[一-鿿，。！？：；、“”‘’（）《》〈〉…—·]')
clean = lambda s: "".join(c for c in s if KEEP.match(c))

# skip TOC entries whose titles are front/back matter
SKIP = re.compile(r'前言|目次|目录|译后记|译者|扉页|版权|后记|序|上卷|中卷|下卷')

ETITLE = {  # known English titles
 "打火匣":"The Tinderbox","小克劳斯和大克劳斯":"Little Claus and Big Claus",
 "豌豆上的公主":"The Princess and the Pea","小意达的花儿":"Little Ida's Flowers",
 "拇指姑娘":"Thumbelina","顽皮孩子":"The Naughty Boy","旅伴":"The Traveling Companion",
 "海的女儿":"The Little Mermaid",
}

BOOKS = [
 dict(path="Story Book/海的女儿.pdf", topic="安徒生童话 (Andersen's Fairy Tales)", toc_level=1),
 dict(path="Story Book/Historical Stories of Chinese Idioms 中华成语典故.pdf",
      topic="中华成语典故 (Chinese Idiom Stories)", toc_level=3, only=r'^第.{1,3}章'),
]

def chapters(bk):
    d = fitz.open(TB + bk["path"]); toc = d.get_toc()
    ents = [(t.strip(), p) for lvl,t,p in toc
            if lvl == bk["toc_level"] and not SKIP.search(t)
            and (re.search(bk["only"], t.strip()) if bk.get("only") else True)]
    out = []
    for i,(title,page) in enumerate(ents):
        end = ents[i+1][1]-1 if i+1 < len(ents) else d.page_count
        prose = "".join(clean(d[p].get_text()) for p in range(page-1, end)).strip()
        if len(prose) >= 200:
            out.append((title, prose))
    return out

con = sqlite3.connect(DB)
uid = con.execute("SELECT user_id FROM stories WHERE topic='水浒传' LIMIT 1").fetchone()[0]
ids = []
for bk in BOOKS:
    chs = chapters(bk)
    print(f"\n=== {bk['topic']} — {len(chs)} chapters ===")
    for n,(title,prose) in enumerate(chs,1):
        han = sum(1 for c in prose if '一'<=c<='鿿')
        et = ETITLE.get(title, re.sub(r'^第.{1,3}章\s*','',title))
        print(f"  {n:>2}. {title[:24]:<24} {han:>6} hanzi  | {prose[:34]}")
        if APPLY:
            cur = con.execute("INSERT INTO stories(user_id,title,topic,story_text,new_words,created_at,english_title,origin) VALUES(?,?,?,?,?,?,?,?)",
                (uid, f"{n}. {title}", bk["topic"], prose, "[]",
                 datetime.now(timezone.utc).isoformat(), et, "graded-reader"))
            ids.append({"id":cur.lastrowid,"title":title})
if APPLY:
    con.commit()
    prev = []
    try: prev = json.load(open("/home/vincent/anki-headless/freq_data/ingested_reader_ids.json"))
    except Exception: pass
    json.dump(prev+ids, open("/home/vincent/anki-headless/freq_data/ingested_reader_ids.json","w"), ensure_ascii=False, indent=1)
    print(f"\ninserted {len(ids)} stories")
else:
    print("\nPREVIEW only. re-run with --apply")
con.close()