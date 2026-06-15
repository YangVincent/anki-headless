#!/usr/bin/env python3
"""Weekly Anki progress report: measures genuine new-word acquisition rate from
the revlog and projects reading/listening timelines. Prints a text report.
Usage: weekly_report.py [--days N]"""
import re, sys, os, time, collections, statistics
from anki.collection import Collection
from wordfreq import zipf_frequency

DAYS = 7
if "--days" in sys.argv: DAYS = int(sys.argv[sys.argv.index("--days")+1])
def clean(s): return re.sub(r'<[^>]+>','',s or '').strip()

col = None
for _ in range(30):
    try: col = Collection("/home/vincent/anki-headless/collection.anki2"); break
    except Exception: time.sleep(2)
if col is None: print("could not open collection (locked)"); sys.exit(1)
try:
    cv = next(m for m in col.models.all() if m['name']=='ChineseVocabulary')
    fi = {f['name']:i for i,f in enumerate(cv['flds'])}; SEP=chr(31)
    vd = col.decks.id_for_name("Vocab")
    now = int(time.time()); since_ms = (now - DAYS*86400)*1000

    # all revlog this week for Vocab forward cards
    rl = col.db.all("""SELECT r.id, r.cid, r.ease, r.type, r.ivl, r.lastIvl
                       FROM revlog r JOIN cards c ON r.cid=c.id
                       WHERE r.id>? AND c.did=? AND c.ord=0""", since_ms, vd)
    reviews = len(rl)
    cids_week = {cid for _,cid,_,_,_,_ in rl}

    # first-ever review per card (to detect "introduced this week" + first-answer)
    intro_week = 0; new_unknown = 0   # cards new to you this week (first answer 'again')
    for cid in cids_week:
        first = col.db.first("SELECT ease,id FROM revlog WHERE cid=? ORDER BY id ASC LIMIT 1", cid)
        if first and first[1] >= since_ms:
            intro_week += 1
            if first[0] == 1: new_unknown += 1   # didn't know it on first sight

    # genuine acquisition: cards you failed at least once (ever) and now hold (review, ivl>=3, last correct)
    acquired = 0
    for cid in cids_week:
        ever_failed = col.db.scalar("SELECT 1 FROM revlog WHERE cid=? AND ease=1 LIMIT 1", cid)
        c = col.get_card(cid)
        last = col.db.first("SELECT ease FROM revlog WHERE cid=? ORDER BY id DESC LIMIT 1", cid)
        if ever_failed and c.type==2 and c.ivl>=3 and last and last[0]>=2:
            acquired += 1

    # true retention: mature reviews this week (prev interval >=4d), % correct
    mature = [(e) for _,_,e,t,ivl,liv in rl if liv>=4 and t in (1,2)]
    retention = (100*sum(1 for e in mature if e>=2)/len(mature)) if mature else None

    studied = col.db.scalar("SELECT COUNT(*) FROM cards WHERE did=? AND ord=0 AND type IN (1,2)", vd)
    new_left = col.db.scalar("SELECT COUNT(*) FROM cards WHERE did=? AND ord=0 AND type=0 AND queue!=-1", vd)

    # 小Lin (finance/econ listening) track
    BUSI = re.compile(r'\b(econom|market|invest|financ|compan|trade|profit|stock|capital|bank|tax|fund|industr|commerc|monetary|price|debt|asset|revenue|enterprise|currency|inflation|loan|business|wealth|merger|equity|budget|GDP|interest rate|bond|dividend|recession|fiscal)\b', re.I)
    ACAD = re.compile(r'\b(cognit|belief|rational|reason|logic|fallac|argument|premise|concept|abstract|philosoph|epistem|moral|ethic|theor|evidence|bias|prejudice|perception|conscious|ideolog|doctrine|hypothes|assumption|contradiction|paradox|subjective|objective|psycholog|empirical|deduc|induc|notion|principle|metaphys|skeptic|dogma|narrative|discourse)\b', re.I)
    fin_tot = fin_learned = acad_tot = acad_learned = 0
    for t, flds in col.db.all("SELECT c.type,n.flds FROM cards c JOIN notes n ON c.nid=n.id WHERE c.did=? AND c.ord=0 AND n.mid=?", vd, cv['id']):
        mean = clean(flds.split(SEP)[fi['Meaning']])
        if BUSI.search(mean):
            fin_tot += 1
            if t in (1,2): fin_learned += 1
        if ACAD.search(mean):
            acad_tot += 1
            if t in (1,2): acad_learned += 1

    # projection: known(rank)=600 head + 34% after; gap to 三体 (~top 6k) and 小Lin (~domain)
    rate = acquired/DAYS   # genuinely-new-and-holding per day
    def known(r): return 600+0.34*max(0,r-1000)
    gap_santi = int(6000-known(6000))
    L=[]
    L.append(f"📊 *Weekly Anki report* (last {DAYS}d)")
    L.append("")
    L.append(f"• Reviews: *{reviews}*  ({len(cids_week)} distinct cards)")
    L.append(f"• New cards introduced: *{intro_week}*  — of which *{new_unknown}* you didn't know")
    L.append(f"• Genuinely learned & holding (failed once, now sticking): *{acquired}*  → ~*{rate:.0f}/day*")
    if retention is not None:
        L.append(f"• Retention on mature reviews: *{retention:.0f}%*")
    L.append(f"• Backbone studied: *{studied}* / ~16,500  ({new_left} still new)")
    L.append("")
    fin_left = fin_tot - fin_learned
    if rate >= 1:
        L.append(f"🎯 *三体 (reading)*: ~{gap_santi:,} words to go → ≈ *{gap_santi/rate/30:.1f} months* at ~{rate:.0f}/day")
        L.append(f"🎧 *小Lin (finance listening)*: {fin_learned}/{fin_tot} finance terms learned, {fin_left} to go (you know many by ear; watch with subs).")
        L.append(f"🧠 *Abstract/academic (video essays)*: {acad_learned}/{acad_tot} terms learned, {acad_tot-acad_learned} to go — the hardest register (not in your heritage base).")
    else:
        L.append("🎯 Not enough acquisition data yet — keep studying; rate firms up over 2-3 weeks.")
        L.append(f"🎧 *小Lin*: {fin_learned}/{fin_tot} finance terms learned.")
        L.append(f"🧠 *Abstract/academic*: {acad_learned}/{acad_tot} terms learned.")
    text = "\n".join(L)
    print(text)

    if "--send" in sys.argv:
        import json, urllib.request, urllib.parse
        cfg = json.load(open("/home/vincent/anki-headless/.bot_config.json"))
        token = cfg["telegram_bot_token"]
        try:
            chat_id = open(os.path.expanduser("~/.anki_chat_id")).read().strip()
        except Exception:
            print("no chat_id captured yet — message the anki-bot once"); chat_id=None
        if chat_id:
            data = urllib.parse.urlencode({"chat_id":chat_id,"text":text,"parse_mode":"Markdown"}).encode()
            req = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage", data=data)
            try:
                urllib.request.urlopen(req, timeout=20); print(f"sent to chat {chat_id}")
            except Exception as e:
                print("send failed:", e)
finally:
    col.close()
