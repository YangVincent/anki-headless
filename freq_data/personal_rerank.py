#!/usr/bin/env python3
"""Re-rank the Vocab new-card queue by the user's PERSONAL register, derived from the
Chinese he actually consumes across his own apps. Re-runnable: reads the live app DBs each
run, so the ordering self-tunes as he watches/listens/saves more.

Rationale: generic wordfreq ordering surfaces web/news/spoken filler; HSK ordering surfaces
exam/institutional vocab. Neither matches a heritage reader whose goal is books/essays. The
transcripts of what he watches (kanchinese) and listens to (tingchinese) ARE his target
register (interior / psychological / literary / analytic), so word frequency *within that
corpus* is the right ranking signal, and the words he taps/saves/highlights are confirmed gaps.

Sources (ALL scoped to Vincent's own accounts — several DBs are multi-user prod DBs)
  kanchinese  fetched.db   : video transcripts (corpus, source='user') + word_events tap/save
                             (gaps, user_id=KAN_USER). Single-user instance, scoped anyway.
  tingchinese *_server.db  : podcast transcripts (corpus) + saved vocab + word_tap_events
                             (gaps) — all WHERE user_id IN TING_USERS. Taps empty until they log.
  dong        dongchinese.db: reading_events tap/save (gaps, user_id IN 1,3) — biggest tap source
  jsonl logs  reader/dict lookups: additional tap gaps (reader log has no user field; single-user)

Gap cleaning (built into the pipeline so re-runs stay reproducible)
  * drop proper nouns via CC-CEDICT capitalized pinyin (鲁智深/大名府 out; 和尚/友谊 kept)
  * tap-only gaps must clear a frequency floor (zipf>=GAP_FLOOR) — this strips the 水浒传
    classical residue that dominates dong; deliberately SAVED gaps bypass the floor (trusted)

Score per card
  proper nouns (CEDICT cap-pinyin / jieba) -> suspend (names, not vocabulary)
  cleaned gap words, non-basic       -> pinned to the very front (words he couldn't read)
  personal-corpus frequency          -> primary boost; each source item capped (CAP) so one
                                        topic can't dominate
  HSK band backbone (foundation-first) -> HSK3-5 upweighted over HSK6-9 to build reading
                                        fluency to HSK5 first; HSK 1-2 demoted (owned)
  single-char function words (jieba) -> demoted (heritage speaker owns them)
  generic zipf                       -> mild tiebreak

Run DRY  :  .venv/bin/python freq_data/personal_rerank.py
Run APPLY:  bash freq_data/anki_op.sh personal-rerank freq_data/personal_rerank.py --apply
"""
import json, re, math, sys, sqlite3, time
from collections import Counter
import jieba, jieba.posseg as pseg
from wordfreq import zipf_frequency
from anki.collection import Collection

ROOT = "/home/vincent/anki-headless"
KAN  = "/home/vincent/chinese-projects/kanchinese/fetched.db"
TING = "/home/vincent/databases/tingchinese_server.db"
DONG = "/home/vincent/chinese-projects/dong-chinese/server/dongchinese.db"
READER_LOOKUPS = f"{ROOT}/freq_data/reader_lookups.jsonl"
DICT_LOOKUPS   = "/home/vincent/chinese-projects/chinese-dict/dict_lookups.jsonl"
CEDICT = "/home/vincent/chinese-projects/dong-chinese/Resources/cedict_ts.u8"
HSK  = f"{ROOT}/freq_data/hsk3_vocab.json"
# Several of these are MULTI-USER production DBs — every query MUST be scoped to Vincent's own
# accounts or it pollutes with strangers. tingchinese: his email maps to two user_ids; dong:
# user_id 1,3 (same scoping bot.py._lookup_counts already uses).
TING_USERS = ("20039a5917c444f895520e6e4265f40b", "cc02018e77064db49b63b338e19c99a8")
DONG_USERS = (1, 3)
KAN_USER   = "02e6e1e4-e2ff-4fba-b3c1-7a43117bb88d"   # kanchinese is single-user, but scope explicitly
APPLY = "--apply" in sys.argv
SEP  = chr(31)
HAN  = re.compile(r'[一-鿿]')
CAP  = 8     # max a single video/episode contributes to one word's count
GAP_FLOOR = 3.3   # tap-only gaps below this zipf are dropped (strips 水浒传 classical residue)

PROP = {'nr','ns','nt','nz'}
FUNC = {'c','u','d','r','m','q','p','e','o','y','uj','ul','ud','uv','uz','rr','mq'}
# Foundation-first backbone: upweight mid levels (HSK3-5) over advanced (HSK6-9) so the
# non-gap backbone builds reading fluency to HSK5 before piling on HSK6-9. Gaps still lead
# everything (score ~60). Flip back toward flat/advanced once HSK5 feels solid.
HSK_BONUS = {'3':22,'4':18,'5':13,'6':6,'7-9':3,'2':-15,'1':-20}

def _ro(path):
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)

def add_doc(eff, text):
    """add one document's capped word counts into the running eff counter"""
    vc = Counter(t for t in jieba.cut(text) if len(t) >= 2 and all(HAN.match(c) for c in t))
    for w, c in vc.items():
        eff[w] += min(c, CAP)

# ---- CC-CEDICT: proper-noun detection via capitalized pinyin (repo standard) -------------
_ced = None
def load_cedict():
    global _ced
    if _ced is not None: return _ced
    _ced = {}
    try:
        for line in open(CEDICT, encoding="utf-8"):
            if line.startswith("#"): continue
            m = re.match(r"^\S+\s+(\S+)\s+\[([^\]]*)\]\s+/(.*)/\s*$", line)
            if m: _ced.setdefault(m.group(1), (m.group(2), m.group(3)))
    except OSError as e:
        print(f"  [cedict unavailable: {e}]")
    return _ced
def is_name(w):
    """proper noun if CC-CEDICT gives it capitalized pinyin (surname/person/place/org)."""
    e = load_cedict().get(w)
    if not e: return False
    py, defs = e
    return bool(re.search(r"(^|\s)[A-Z]", py)) or bool(
        re.search(r"\b(surname|place|county|prefecture|dynasty|Buddhist name)\b", defs))

def load_sources():
    """returns (eff corpus counter, gaps {word: saved_bool}, ndoc)."""
    eff = Counter()
    gaps = {}                       # word -> saved? (True if ever a deliberate save)
    def add_gap(w, saved):
        if w: gaps[w] = gaps.get(w, False) or saved
    ndoc = 0
    # --- kanchinese: transcripts (corpus) + word_events (gaps) — single-user, scoped explicitly ---
    try:
        con = _ro(KAN)
        # `fetched` has no user_id, but every row is source='user' in a single-user instance,
        # so the transcript cache is entirely his. word_events IS user-scoped defensively.
        for (tr,) in con.execute("SELECT transcript FROM fetched "
                                 "WHERE source='user' AND transcript IS NOT NULL AND LENGTH(transcript)>200"):
            try: text = "".join(s.get("text","") for s in json.loads(tr))
            except Exception: text = tr
            add_doc(eff, text); ndoc += 1
        for w, kind in con.execute(
                "SELECT word, kind FROM word_events WHERE user_id=? AND word IS NOT NULL", (KAN_USER,)):
            add_gap(w, kind == "save")
        con.close()
    except Exception as e:
        print(f"  [kanchinese skipped: {e}]")
    # --- tingchinese: transcripts (corpus) + saved vocab (gaps) — SCOPED to his user_ids ---
    try:
        con = _ro(TING); ph = ",".join("?" * len(TING_USERS))
        for (pj,) in con.execute(
                f"SELECT t.payload_json FROM transcripts t JOIN transcription_jobs j "
                f"ON t.job_id=j.id WHERE j.user_id IN ({ph})", TING_USERS):
            try:
                d = json.loads(pj); add_doc(eff, "".join(s.get("text","") for s in d.get("segments",[]))); ndoc += 1
            except Exception: pass
        for (w,) in con.execute(
                f"SELECT selected_text FROM sync_vocabulary_items "
                f"WHERE deleted_at_ms IS NULL AND user_id IN ({ph})", TING_USERS):
            add_gap(w, True)          # saved
        # word_tap_events: tap-tracking shipped 2026-07-04 (may be empty until taps accumulate)
        try:
            for w, kind in con.execute(
                    f"SELECT word, kind FROM word_tap_events WHERE user_id IN ({ph}) "
                    f"AND word IS NOT NULL AND word<>''", TING_USERS):
                add_gap(w, kind == "save")
        except sqlite3.OperationalError:
            pass                      # table not present in this DB build yet
        con.close()
    except Exception as e:
        print(f"  [tingchinese skipped: {e}]")
    # --- dong: reading_events tap/save (gaps) — SCOPED to user_id 1,3 ---
    try:
        con = _ro(DONG); ph = ",".join("?" * len(DONG_USERS))
        for w, kind in con.execute(
                f"SELECT word, kind FROM reading_events WHERE user_id IN ({ph}) "
                f"AND kind IN ('tap','save') AND word IS NOT NULL AND word<>''", DONG_USERS):
            add_gap(w, kind == "save")
        con.close()
    except Exception as e:
        print(f"  [dong skipped: {e}]")
    # --- legacy jsonl lookup logs (taps) ---
    for p in (READER_LOOKUPS, DICT_LOOKUPS):
        try:
            for line in open(p, encoding="utf-8"):
                line = line.strip()
                if not line: continue
                try: add_gap(json.loads(line).get("word", ""), False)
                except Exception: pass
        except OSError:
            pass
    return eff, gaps, ndoc

def clean_gaps(gaps):
    """Prune the raw gap dict (built into the pipeline): drop proper nouns, and require
    tap-only gaps to clear the frequency floor (deliberate saves are trusted, bypass it).
    Returns (kept set, stats dict)."""
    kept, dropped_name, dropped_rare = set(), 0, 0
    for w, saved in gaps.items():
        w = w.strip()
        if not (w and HAN.match(w[:1]) and 1 < len(w) <= 6):
            continue
        if is_name(w):
            dropped_name += 1; continue
        if not saved and zipf_frequency(w, "zh") < GAP_FLOOR:
            dropped_rare += 1; continue
        kept.add(w)
    return kept, {"names": dropped_name, "rare": dropped_rare}

_pn, _fn = {}, {}
def is_proper(w):
    """proper noun for card-suspension: CEDICT capitalized pinyin OR jieba nr/ns/nt/nz."""
    if w not in _pn:
        if is_name(w):
            _pn[w] = True
        else:
            t = list(pseg.cut(w)); _pn[w] = len(t) == 1 and t[0].flag in PROP
    return _pn[w]
def is_func(w):
    if w not in _fn:
        t = list(pseg.cut(w)); _fn[w] = len(t) == 1 and t[0].flag in FUNC
    return _fn[w]
def is_wordlike(w):
    """real lexical item, not a tap-span fragment/phrase: a CC-CEDICT headword, or a single
    jieba token (drops cross-boundary bigrams 他顿/往镇 and transparent compounds 砍开/抢过来)."""
    return w in load_cedict() or len(jieba.lcut(w, HMM=False)) == 1

def main():
    hsk = {h['word']: h['level'] for h in json.load(open(HSK))}
    eff, raw_gaps, ndoc = load_sources()
    gaps, gstats = clean_gaps(raw_gaps)
    print(f"personal corpus: {ndoc} docs, {len(eff):,} distinct words")
    print(f"gap words: {len(raw_gaps)} raw -> {len(gaps)} clean "
          f"(dropped {gstats['names']} names, {gstats['rare']} rare/classical below zipf {GAP_FLOOR})")

    def score(w, z):
        if is_proper(w):
            return -100
        basic = hsk.get(w) in ('1','2')
        if w in gaps and not basic:                     # confirmed gap: pin to front
            return 60 + eff.get(w, 0) + z
        personal = 6.0 * math.log2(1 + eff.get(w, 0))
        hb = HSK_BONUS.get(hsk.get(w), 0)
        fn = -14 if (is_func(w) and eff.get(w, 0) < CAP) else 0
        return personal + hb + fn + z

    for _ in range(12):
        try: col = Collection(f"{ROOT}/collection.anki2"); break
        except Exception: time.sleep(3)
    else: raise SystemExit("collection locked")
    try:
        vd = col.decks.id_for_name("Vocab")
        rows = col.db.all("SELECT c.id,n.flds FROM cards c JOIN notes n ON c.nid=n.id "
                          "WHERE c.did=? AND c.type=0 AND c.ord=0", vd)
        scored, suspend, deckwords = [], [], set()
        for cid, flds in rows:
            w = re.sub(r"<[^>]+>", "", flds.split(SEP)[0]).strip()
            z = zipf_frequency(w, "zh") if w else 0.0
            s = score(w, z); deckwords.add(w)
            if s <= -50: suspend.append(cid)
            else:        scored.append((s, cid, w))
        scored.sort(key=lambda x: -x[0])
        ordered = [cid for _, cid, _ in scored]
        print(f"\nVocab new cards: {len(rows)}  ->  reposition {len(ordered)}, suspend {len(suspend)} proper-noun cards")
        print("new FRONT 30:", " ".join(w for _, _, w in scored[:30]))
        mine = sorted(w for w in gaps if w not in deckwords and is_wordlike(w))
        print(f"\ngap words NOT yet cards ({len(mine)}) -> mining candidates:\n  " + " ".join(mine))

        if APPLY:
            col.sched.reposition_new_cards(ordered, starting_from=1, step_size=1,
                                           randomize=False, shift_existing=False)
            if suspend: col.sched.suspend_cards(suspend)
            top = col.db.all("SELECT n.flds FROM cards c JOIN notes n ON c.nid=n.id "
                             "WHERE c.did=? AND c.type=0 AND c.ord=0 ORDER BY c.due LIMIT 12", vd)
            ws = [re.sub(r'<[^>]+>', '', f.split(SEP)[0]).strip() for (f,) in top]
            nsus = col.db.scalar("SELECT COUNT(*) FROM cards WHERE did=? AND queue=-1", vd)
            print(f"\nAPPLIED. new frontmost: {' '.join(ws)}")
            print(f"suspended cards in Vocab now: {nsus}")
        else:
            print("\nDRY-RUN (no changes). add --apply (via anki_op.sh) to write.")
    finally:
        col.close()

if __name__ == "__main__":
    main()
