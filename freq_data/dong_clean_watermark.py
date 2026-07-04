#!/usr/bin/env python3
"""Strip piracy watermarks / SEO spam that a source ebook injected mid-sentence into Dong
imports (e.g. 'SEO观察，每天分享优质电子书：http://www.seosee.info' spliced at every page
break, shredding the text). Removing it inline rejoins the split words. Cleans both
stories.story_text and story_sentences.zh. DRY-RUN unless --apply (backup first; stop
dong-chinese around it, restart after to bust the reader lru_cache)."""
import sqlite3, re, sys, shutil, time

DB = "/home/vincent/chinese-projects/dong-chinese/server/dongchinese.db"
APPLY = "--apply" in sys.argv
TOPICS = [a for a in sys.argv[1:] if not a.startswith("-")]  # empty => all imported

# watermark / spam patterns (order matters: specific first, then bare urls). Covers both the
# Chinese watermark and its English translation, which live in zh / story_text and en.
PATTERNS = [
    re.compile(r"SEO观察[，,]?\s*每天分享优质电子书[：:]?\s*https?://[^\s，。！？、]*seosee\.info"),
    re.compile(r"(SEO ?Watch[,，]?\s*)?[Ss]har\w*\s+quality\s+e-?books\s+(?:daily|every day)\s*[：:]?\s*https?://\S*seosee\.info", re.I),
    re.compile(r"https?://[^\s，。！？、]*seosee\.info"),
    re.compile(r"SEO观察[，,]?\s*每天分享优质电子书[：:]?"),
]

def clean(text):
    if not text:
        return text, 0
    n = 0
    for pat in PATTERNS:
        text, k = pat.subn("", text)
        n += k
    return text, n

def main():
    con = sqlite3.connect(DB)
    where = "origin='imported'"
    params = ()
    if TOPICS:
        where += " AND topic IN (%s)" % ",".join("?" * len(TOPICS)); params = tuple(TOPICS)
    story_ids = [r[0] for r in con.execute(f"SELECT id FROM stories WHERE {where}", params)]
    total_hits = 0
    sample = []
    for sid in story_ids:
        # story_text
        (txt,) = con.execute("SELECT story_text FROM stories WHERE id=?", (sid,)).fetchone()
        new_txt, k1 = clean(txt); total_hits += k1
        if APPLY and k1:
            con.execute("UPDATE stories SET story_text=? WHERE id=?", (new_txt, sid))
        # sentences: clean both zh and the en translation
        for idx, zh, en in con.execute("SELECT idx, zh, en FROM story_sentences WHERE story_id=?", (sid,)).fetchall():
            new_zh, k2 = clean(zh)
            new_en, k3 = clean(en)
            if k2 or k3:
                total_hits += k2 + k3
                if len(sample) < 6 and zh != new_zh:
                    sample.append((zh[:70], new_zh[:70]))
                if APPLY:
                    if new_zh.strip():
                        con.execute("UPDATE story_sentences SET zh=?, en=? WHERE story_id=? AND idx=?", (new_zh, new_en, sid, idx))
                    else:
                        con.execute("DELETE FROM story_sentences WHERE story_id=? AND idx=?", (sid, idx))
    scope = TOPICS or ["<all imported>"]
    print(f"scope: {', '.join(scope)}  ({len(story_ids)} stories)")
    print(f"watermark hits {'removed' if APPLY else 'to remove'}: {total_hits}")
    print("\nbefore -> after samples:")
    for b, a in sample:
        print(f"  - {b}\n    {a}\n")
    if APPLY:
        con.commit(); con.close()
        print("APPLIED. Restart dong-chinese to bust the reader lru_cache.")
    else:
        con.close()
        print("DRY-RUN. add --apply (backup + stop/restart dong-chinese) to write.")

if __name__ == "__main__":
    main()
