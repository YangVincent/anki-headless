#!/usr/bin/env python3
"""Re-chunk a poorly-imported Dong book: the importer split long sections into fixed-length
pieces titled "(2)/(3)" or with mid-sentence fragments (e.g. '…做法。1986'), producing 261
stubs in a scrambled order. This merges every continuation chunk back into its parent heading,
yielding proper titled sections. DRY-RUN by default; --apply rewrites (with a backup first).

Usage:
  dry : .venv/bin/python freq_data/dong_rechunk.py "终身成长"
  app : .venv/bin/python freq_data/dong_rechunk.py "终身成长" --apply
"""
import sqlite3, re, sys, shutil, time, os

DB = "/home/vincent/chinese-projects/dong-chinese/server/dongchinese.db"
TOPICS = [a for a in sys.argv[1:] if not a.startswith("-")] or ["终身成长"]
APPLY = "--apply" in sys.argv
USERS = (0, 1, 3)

def is_continuation(title):
    """True if this chunk continues the previous section rather than starting a new one."""
    t = (title or "").strip()
    if re.search(r"[（(]\s*\d+\s*[)）]\s*$", t):     # explicit "(2)" / "（3）" continuation
        return True
    if re.search(r"[。！？，、；：]", t):             # a real heading has no sentence punctuation
        return True
    if re.match(r"^\d", t) and "章" not in t:        # leading stray digit fragment ("2.问题…")
        return True
    if re.match(r"^[—–-]", t):                       # quote-attribution fragment ("——穆罕默德·阿里")
        return True
    if ("（" in t or "(" in t) and not ("）" in t or ")" in t):  # OCR-truncated name ("…（Mark")
        return True
    if re.search(r"[A-Za-z]$", t):                   # title ends mid-Latin -> truncated fragment
        return True
    return False

def base_title(title):
    return re.sub(r"\s*[（(]\s*\d+\s*[)）]\s*$", "", (title or "").strip())

def load_chunks(con, topic):
    return con.execute(
        "SELECT id, title, story_text FROM stories WHERE topic=? AND user_id IN (%s) "
        "ORDER BY id" % ",".join(map(str, USERS)), (topic,)).fetchall()

def consolidate(chunks):
    """-> list of {title, chunk_ids:[...], nchars} merging continuations into headings."""
    sections = []
    for sid, title, text in chunks:
        t = (title or "").strip()
        cont = is_continuation(t)
        # a "(2)" continuation whose base matches the current section is definitely a continuation
        if sections and cont:
            sections[-1]["chunk_ids"].append(sid)
            sections[-1]["nchars"] += len(text or "")
        else:
            sections.append({"title": base_title(t) or t or "无题",
                             "chunk_ids": [sid], "nchars": len(text or "")})
    return sections

def rewrite_topic(con, topic, secs):
    """merge each section into its first chunk row; drop the leftover stub rows."""
    cur = con.cursor()
    kept = deleted = 0
    for s in secs:
        ids = s["chunk_ids"]; canon = ids[0]
        texts = [con.execute("SELECT story_text FROM stories WHERE id=?", (cid,)).fetchone()[0] or "" for cid in ids]
        merged_text = "\n".join(t.strip() for t in texts if t.strip())
        cur.execute("UPDATE stories SET title=?, story_text=? WHERE id=?", (s["title"], merged_text, canon))
        sents = []
        for cid in ids:
            for src, para, zh, en in con.execute(
                    "SELECT source, para, zh, en FROM story_sentences WHERE story_id=? ORDER BY idx", (cid,)):
                sents.append((src, para, zh, en))
        cur.execute("DELETE FROM story_sentences WHERE story_id=?", (canon,))
        for i, (src, para, zh, en) in enumerate(sents):
            cur.execute("INSERT INTO story_sentences(source, story_id, idx, para, zh, en) VALUES(?,?,?,?,?,?)",
                        (src, canon, i, para, zh, en))
        for cid in ids[1:]:
            cur.execute("DELETE FROM story_sentences WHERE story_id=?", (cid,))
            cur.execute("DELETE FROM stories WHERE id=?", (cid,))
            deleted += 1
        kept += 1
    return kept, deleted

def main():
    con = sqlite3.connect(DB)
    plan = {}
    for t in TOPICS:
        secs = consolidate(load_chunks(con, t))
        raw = sum(len(s["chunk_ids"]) for s in secs)
        # guard: heading-less narrative (e.g. novels) collapses to ~1 blob -> refuse to merge
        if raw > 5 and len(secs) <= max(1, raw // 20):
            print(f"topic={t!r}: {raw} chunks -> {len(secs)} sections  ⚠ SKIPPED (no headings detected; would blob)")
            continue
        plan[t] = secs
        print(f"topic={t!r}: {raw} raw chunks -> {len(secs)} consolidated sections")
    if not APPLY:
        con.close()
        print("\nDRY-RUN. Re-run with --apply to rewrite (one .bak is made first; stop dong-chinese around it).")
        return
    bak = f"{DB}.rechunk-bak-{int(time.time())}"
    shutil.copy2(DB, bak)
    print(f"\nbackup -> {bak}")
    for t, secs in plan.items():
        kept, deleted = rewrite_topic(con, t, secs)
        print(f"  {t!r}: {kept} sections kept, {deleted} stubs merged away")
    con.commit()
    con.close()
    print("APPLIED all. Restart dong-chinese to bust the reader's lru_cache.")

if __name__ == "__main__":
    main()
