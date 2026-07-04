#!/usr/bin/env python3
"""Ingest text-extractable graded readers into dongchinese.db `stories`.
Auto-detects layout: 'rainbow' (lettered glossary -> new_words) vs 'prose'
(clean prose, new_words=[] so the reader falls back to CC-CEDICT).
--apply to insert; default previews only. Logs inserted IDs to
freq_data/ingested_reader_ids.json (reversible)."""
import fitz, re, json, sqlite3, sys
from datetime import datetime, timezone

APPLY = "--apply" in sys.argv
DB = "/home/vincent/chinese-projects/dong-chinese/server/dongchinese.db"
TB = "/home/vincent/anki-headless/freq_data/textbooks/Learning Mandarin Material (DO NOT SELL) @binkybing/"
KEEP = re.compile(r'[一-鿿，。！？：；、“”‘’（）《》〈〉…—·]')
clean = lambda s: "".join(c for c in s if KEEP.match(c))
GLOSS = re.compile(r'^([a-z])\t(.+)$')

# Only single-story graded readers here. Big multi-story prose anthologies
# (海的女儿, 中华成语典故, 500词) are deferred for proper chapter-splitting.
READERS = [
  ("Story Book/Nuwa the Goddess of Mankind by Rainbow Bridge.pdf", "女娲造人", "Nüwa Creates Mankind"),
  ("Story Book/The Legend of Chinese New Years Eve by Rainbow Bridge Graded Chinese.pdf", "中国节日的传说", "Legends of Chinese Festivals"),
]
TOPIC = "Rainbow Bridge Graded Readers"

def parse(path):
    d = fitz.open(TB + path)
    # detect rainbow: any lettered-glossary line in first 20 content pages
    rainbow = any(GLOSS.match(l) for p in range(min(20, d.page_count))
                  for l in d[p].get_text().split("\n"))
    parts, gl = [], {}
    # rainbow readers: start at the first glossary page (skips the 编者的话 preface,
    # which has no lettered glossary). prose: first page with >=120 hanzi.
    if rainbow:
        start = next((p for p in range(d.page_count)
                      if any(GLOSS.match(l) for l in d[p].get_text().split("\n"))), 0)
    else:
        start = next((p for p in range(d.page_count)
                      if sum(1 for c in d[p].get_text() if '一'<=c<='鿿') >= 120), 0)
    for pno in range(start, d.page_count):
        lines = d[pno].get_text().split("\n")
        gi = next((i for i,l in enumerate(lines) if GLOSS.match(l)), len(lines))
        pr = clean("".join(lines[:gi])).strip()
        if len(pr) >= 10: parts.append(pr)
        if rainbow:
            g = "\n".join(lines[gi:])
            for m in re.finditer(r'(?:^|\n)([a-z])\t(.+?)(?=(?:\n[a-z]\t)|\Z)', g, re.S):
                body = re.sub(r'\s+', ' ', m.group(2)).strip()
                mm = re.match(r'(.+?)\s*\(([^)]+)\)\s*(.*?)(?:e\.g\.,.*)?$', body)
                if mm and re.fullmatch(r'[一-鿿]+', mm.group(1).strip()):
                    w = mm.group(1).strip()
                    gl.setdefault(w, {"word": w, "pinyin": mm.group(2).strip(), "meaning": mm.group(3).strip()})
    return "".join(parts), list(gl.values()), ("rainbow" if rainbow else "prose")

con = sqlite3.connect(DB)
uid = con.execute("SELECT user_id FROM stories WHERE topic='水浒传' LIMIT 1").fetchone()[0]
ids = []
for path, title, etitle in READERS:
    story, nw, typ = parse(path)
    han = sum(1 for c in story if '一'<=c<='鿿')
    print(f"\n[{typ}] {title} — {han} hanzi, {len(nw)} new_words")
    print(f"   preview: {story[:90]}")
    if han < 300:
        print("   SKIP (too little clean text)"); continue
    if APPLY:
        cur = con.execute("INSERT INTO stories(user_id,title,topic,story_text,new_words,created_at,english_title,origin) VALUES(?,?,?,?,?,?,?,?)",
            (uid, title, TOPIC, story, json.dumps(nw, ensure_ascii=False),
             datetime.now(timezone.utc).isoformat(), etitle, "graded-reader"))
        ids.append({"id": cur.lastrowid, "title": title})
        print(f"   INSERTED id={cur.lastrowid}")
if APPLY:
    con.commit()
    json.dump(ids, open("/home/vincent/anki-headless/freq_data/ingested_reader_ids.json","w"), ensure_ascii=False, indent=1)
    print(f"\ninserted {len(ids)} stories; ids -> freq_data/ingested_reader_ids.json")
else:
    print("\nPREVIEW only. re-run with --apply")
con.close()