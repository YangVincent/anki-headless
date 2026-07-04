#!/usr/bin/env python3
"""Font-aware per-idiom split of 中华成语典故 + TOC split of 海的女儿, ingest into
dongchinese.db. --apply to insert. Appends ids to ingested_reader_ids.json."""
import fitz, re, json, sqlite3, sys
from datetime import datetime, timezone
APPLY="--apply" in sys.argv
DB="/home/vincent/chinese-projects/dong-chinese/server/dongchinese.db"
TB="/home/vincent/anki-headless/freq_data/textbooks/Learning Mandarin Material (DO NOT SELL) @binkybing/"
HAN=lambda s: re.fullmatch(r'[一-鿿]+',s) is not None
KEEPB=re.compile(r'[一-鿿，。！？：；、“”‘’（）《》〈〉…—·]')
BLOCK={"中华成语典故","品格意志","为人处世","智慧谋略","好学求知","生活启示","幽默诙谐","上卷","中卷","下卷"}

def idiom_stories():
    d=fitz.open(TB+"Story Book/Historical Stories of Chinese Idioms 中华成语典故.pdf")
    out=[]; cur=None; body=[]
    def flush():
        nonlocal cur,body
        if cur and body:
            t="".join(body).strip()
            if t.count("。")>=3 and len(t)>=120: out.append((cur,t))
        body=[]
    for pno in range(d.page_count):
        for b in d[pno].get_text("dict")["blocks"]:
            for l in b.get("lines",[]):
                for s in l["spans"]:
                    t=s["text"].strip(); sz=s["size"]
                    if not t or not any('一'<=c<='鿿' for c in t): continue
                    if sz>=20 and 2<=len(t)<=7 and HAN(t):
                        flush(); cur=None if t in BLOCK else t
                    elif 9<=sz<=14 and cur:
                        body.append("".join(c for c in t if KEEPB.match(c)))
    flush()
    return out

ETITLE={"打火匣":"The Tinderbox","小克劳斯和大克劳斯":"Little Claus and Big Claus","豌豆上的公主":"The Princess and the Pea","小意达的花儿":"Little Ida's Flowers","拇指姑娘":"Thumbelina","顽皮孩子":"The Naughty Boy","旅伴":"The Traveling Companion","海的女儿":"The Little Mermaid"}
SKIP=re.compile(r'前言|目次|目录|译后记|译者|扉页|版权|后记|序')
def andersen():
    d=fitz.open(TB+"Story Book/海的女儿.pdf"); toc=d.get_toc()
    ents=[(t.strip(),p) for lvl,t,p in toc if lvl==1 and not SKIP.search(t)]
    out=[]
    for i,(title,page) in enumerate(ents):
        end=ents[i+1][1]-1 if i+1<len(ents) else d.page_count
        prose="".join("".join(c for c in d[p].get_text() if KEEPB.match(c)) for p in range(page-1,end)).strip()
        if len(prose)>=200: out.append((title,prose))
    return out

con=sqlite3.connect(DB)
uid=con.execute("SELECT user_id FROM stories WHERE topic='水浒传' LIMIT 1").fetchone()[0]
ids=[]
def ingest(stories, topic, etmap=None):
    print(f"\n=== {topic} — {len(stories)} stories ===")
    for n,(title,txt) in enumerate(stories,1):
        han=sum(1 for c in txt if '一'<=c<='鿿')
        if n<=3 or n%50==0: print(f"  {n:>3}. {title[:20]:<20} {han:>5} hanzi")
        if APPLY:
            et=(etmap or {}).get(title, title)
            cur=con.execute("INSERT INTO stories(user_id,title,topic,story_text,new_words,created_at,english_title,origin) VALUES(?,?,?,?,?,?,?,?)",
                (uid,f"{n}. {title}",topic,txt,"[]",datetime.now(timezone.utc).isoformat(),et,"graded-reader"))
            ids.append({"id":cur.lastrowid,"title":title})

ingest(andersen(), "安徒生童话 (Andersen's Fairy Tales)", ETITLE)
ingest(idiom_stories(), "中华成语典故 (Chinese Idiom Stories)")
if APPLY:
    con.commit()
    prev=[]
    try: prev=json.load(open("/home/vincent/anki-headless/freq_data/ingested_reader_ids.json"))
    except Exception: pass
    json.dump(prev+ids, open("/home/vincent/anki-headless/freq_data/ingested_reader_ids.json","w"), ensure_ascii=False, indent=1)
    print(f"\ninserted {len(ids)} stories total")
else:
    print("\nPREVIEW only. re-run with --apply")
con.close()