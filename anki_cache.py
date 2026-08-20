"""The derived read cache: one small projection of the collection, owned by the bot.

WHY THIS EXISTS. Five services read one Anki collection three different ways -- the anki
library, a 111 MB snapshot copy taken at 05:15, and a raw read of the live file. Each one
knows Anki's schema, and every consumer breakage on 2026-08-19 came from that knowledge
leaking outward: deck names, `ord`, `queue`, and the three separate meanings of `due`.
This module replaces all of it with `cache.db`: 129,000 rows and 28 MB of derived facts
that the bot writes and everyone else reads. See READ_CACHE_PLAN.md and READ_CACHE_BRIEF.md.

THE RULES, each one learned by breaking something.

  * NO ANKI LIBRARY. Anki allows exactly one open collection handle, so opening it
    contends with the bot's own writer and with freq_data/anki_op.sh. This module reads
    with a plain `mode=ro` sqlite3 connection and takes no lock. A test asserts that
    importing this module does not import `anki`.

  * ONE SNAPSHOT IN. `col.mod` and every row are read inside ONE transaction. A `mod`
    read outside the snapshot records a state the cache does not hold, and the cache then
    never catches up.

  * `immutable` IS NEVER SET. It makes SQLite skip the WAL, so a row Anki committed
    moments ago reads as absent, with no error.

  * NO SQL NAME LOOKUP. `decks.name` carries Anki's `unicase` collation, so on a raw
    connection `where name = 'HSK'` raises. decks.resolve_rows() does it in Python.

  * THE DAY NUMBER IS ANKI'S. `(now - crt) // 86400` disagrees with col.sched.today for
    nine hours of every day, because Anki rolls the day over at config.rollover (04:00
    here), in the current UTC offset. Verified against col.sched.today across shifted
    collections and rollover hours 0, 2, 4, 9 and 23.

  * EVERY LOOKUP RAISES. A deck that does not exist and a deck with no cards must not
    look the same. Where a published HTTP contract returns [] for a missing deck, the
    HANDLER converts; this module stays strict.

  * IT NEVER WRITES TO THE COLLECTION. It is a read model.
"""
from __future__ import annotations

import bisect
import html
import json
import os
import re
import sqlite3
import time
from collections import defaultdict

import decks

SCHEMA_VERSION = 1
# Resolved at CALL time, never as a default argument value. Python binds a default when
# the `def` executes, so `cache_path=CACHE_PATH` captures the module value at import and
# a test that redirects the constant redirects NOTHING. The test fixture caught exactly
# that: a handler test wrote the live cache.db while the guard was watching.
CACHE_PATH = "/home/vincent/anki-headless/cache.db"
DEFAULT_COLLECTION = "/home/vincent/anki-headless/collection.anki2"

#: A review card at or above this interval is `mature`. Same constant as bot.MATURE_IVL.
MATURE_IVL = 21

#: A "leech" for the tutor: lapsed repeatedly AND still on a short interval. NOT Anki's
#: `leech` tag, which matches 1 note in this collection, and not the `%leech%` substring
#: jiangchinese used to run, which matched 118 notes that all carry `rewritten::leech`.
#: The interval bound matters: a card with 9 lapses now sitting at 60 days is relearned.
LEECH_MIN_LAPSES = 3
LEECH_MAX_IVL = 7

#: Consumers that must be correct refuse a cache older than this. The bot confirms the
#: cache every 30 s, so this only trips when the bot is down or the build is failing.
DEFAULT_MAX_AGE = 900

#: The note type whose field layout this module knows. Others store no text.
VOCAB_NOTETYPE = "ChineseVocabulary"
_TEXT_FIELDS = ("Pinyin", "Meaning", "SentenceSimplified", "SentenceMeaning")

#: Day bucketing for reviews_daily and progression_weekly. 7 h, matching bot.PDT_OFFSET
#: and chinese-dashboard/build_stats.OFF. It is a fixed offset, so it is an hour out in
#: winter -- kept identical on purpose, because /api/stats publishes these dates today.
DAY_OFFSET = 7 * 3600

# Template kinds. `speaking` and `cloze` are BOTH production-direction drills -- see
# DECK_REFERENCE.md: "Ords 1 and 2 are both production-direction". Naming ord 1
# "production" and ord 2 "cloze" would invent a third vocabulary for the same thing.
RECOGNITION = "recognition"
SPEAKING = "speaking"
CLOZE = "cloze"
OTHER = "other"

#: Read from the TEMPLATE NAME, not from `ord`. The names are stable data; `ord`
#: arithmetic guesses, and guesses wrongly for the 13 note types that are not
#: ChineseVocabulary.
_KIND_BY_TEMPLATE_NAME = {
    "Hanzi-English": RECOGNITION,
    "English-Speaking": SPEAKING,
    "Cloze-Recall": CLOZE,
}

#: Anki keeps the flag colour in the low 3 bits of cards.flags. Same map as bot.FLAG_NAMES.
FLAG_NAMES = {1: "Red", 2: "Orange", 3: "Green", 4: "Blue",
              5: "Pink", 6: "Turquoise", 7: "Purple"}

_STATUS_RANK = {"new": 0, "learning": 1, "young": 2, "mature": 3}


# ── errors ────────────────────────────────────────────────────────────

class CacheError(RuntimeError):
    """Base for every failure this module reports."""


class CacheMissing(CacheError):
    """There is no cache file at all."""


class CacheIncomplete(CacheError):
    """The file exists but holds no meta row. A first build has not finished.

    Its own error because SQLite CREATES an empty file on connect, so "absent" and
    "empty" are different states that used to look identical.
    """


class CacheStale(CacheError):
    """The bot has not confirmed the cache against the collection recently enough."""


class SchemaMismatch(CacheError):
    """The cache was written by a different version of this module."""


class NotInCache(CacheError):
    """A deck, role or note type that the cache does not hold."""


class BuildError(CacheError):
    """The collection holds something this module refuses to guess about."""


# ── deriving one fact from Anki's columns ──────────────────────────────

_STRIP = re.compile(r"<!--.*?-->|<[^>]+>|\[sound:[^\]]*\]", re.S)
_SPACES = re.compile(r"\s+")


def canonical(text):
    """Field text as a plain string: no tags, no entities, no sound tags, no runs of space.

    The key column must be canonical. Raw field 0 carries markup on 985 notes of this
    collection -- `<span id="docs-internal-guid-...">建筑</span>` and `&nbsp;臭宝` are
    real values -- and nine of those are HSK words that /api/hsk-levels matches by string.
    """
    return _SPACES.sub(" ", html.unescape(_STRIP.sub(" ", text or ""))).strip()


def template_kind(template_name, ord_):
    """What a card ASKS, as a word. Never `ord`."""
    kind = _KIND_BY_TEMPLATE_NAME.get(template_name)
    if kind:
        return kind
    return RECOGNITION if ord_ == 0 else OTHER


def card_status(ctype, ivl):
    """`new` / `learning` / `young` / `mature`, and it RAISES on anything else.

    Four values, not three: /api/hsk-levels already separates a review card under 21 days
    (`young`) from a learning or relearning card (`learning`).
    """
    if ctype == 0:
        return "new"
    if ctype in (1, 3):
        return "learning"
    if ctype == 2:
        return "mature" if ivl >= MATURE_IVL else "young"
    raise BuildError(f"unknown cards.type value {ctype!r}; refusing to guess")


#: queue -1 suspended, -2 sibling-buried, -3 manually buried. 0 new, 1 intraday learning,
#: 2 review, 3 day learning, 4 preview (a filtered deck). Burying is in use here --
#: config.lastUnburied is set -- and a buried card would otherwise read as live with no
#: due date.
_BLOCKED_QUEUES = {-1: "suspended", -2: "buried", -3: "buried"}
_LIVE_QUEUES = frozenset((0, 1, 2, 3, 4))


def card_blocked(queue):
    """'suspended', 'buried', or None. RAISES on an unknown queue rather than defaulting."""
    if queue in _BLOCKED_QUEUES:
        return _BLOCKED_QUEUES[queue]
    if queue in _LIVE_QUEUES:
        return None
    raise BuildError(f"unknown cards.queue value {queue!r}; refusing to guess")


def overdue_days(queue, due, odue, odid, now, today):
    """Days overdue, normalised, or None when the card is not waiting in a queue.

    `cards.due` holds THREE different units and mixing them turned a card due in 9 days
    into one 250 days overdue:
        queue 1 (intraday learning) -- a UNIX TIMESTAMP
        queue 2 (review) and 3 (day learning) -- a DAY NUMBER
        queue 0 -- a NEW-CARD POSITION, which is not a date at all
    A card on loan to a filtered deck keeps its real value in `odue`.
    """
    real = odue if odid else due
    if queue == 1:
        return (now - real) / 86400.0
    if queue in (2, 3):
        return float(today - real)
    return None


# ── Anki's day number ─────────────────────────────────────────────────
# Verified against col.sched.today on shifted copies of the real collection, for rollover
# hours 0, 2, 4, 9 and 23: 8 of 8 exact. The naive (now - crt) // 86400 was wrong by one
# for nine hours of every day.

def _next_day_at(now, rollover, mins_west):
    local = now - mins_west * 60
    cutoff = (local // 86400) * 86400 + rollover * 3600
    if cutoff <= local:
        cutoff += 86400
    return cutoff + mins_west * 60


def _day_start(crt, rollover, mins_west):
    """`crt` moved to the rollover hour on its own local day.

    Anki already stores crt at the creation-day rollover, so this is usually crt itself.
    It matters when the rollover hour changed after the collection was created.
    """
    local = crt - mins_west * 60
    return (local // 86400) * 86400 + rollover * 3600 + mins_west * 60


def sched_timing(crt, rollover, created_mins_west, now_mins_west, now):
    """(today, next_day_at) exactly as Anki's scheduler computes them.

    The `- 1` is not a fudge: at the creation instant next_day_at is one day ahead of
    day_start, and the collection is on day 0.
    """
    next_day = _next_day_at(now, rollover, now_mins_west)
    start = _day_start(crt, rollover, created_mins_west)
    return (next_day - start) // 86400 - 1, next_day


# ── the schema ────────────────────────────────────────────────────────

_SCHEMA = """
create table meta(
  id               integer primary key check (id = 1),
  schema_version   integer not null,
  generated_at     integer not null,
  checked_at       integer not null,
  paused_until     integer,
  source_mod       integer not null,
  build_seconds    real    not null,
  card_count       integer not null,
  note_count       integer not null,
  today            integer not null,
  next_day_at      integer not null,
  day_offset       integer not null,
  unexpected_decks text    not null default '',
  skipped_cards    integer not null default 0
);

create table words(
  simplified       text not null,
  sort_field       text not null,
  deck             text not null,
  role             text not null,
  key_kind         text not null,
  template_kind    text not null,
  template_name    text not null,
  status           text not null,
  relearning       integer not null,
  blocked          text,
  interval         integer not null,
  lapses           integer not null,
  overdue_days     real,
  created_at       integer not null,
  card_count       integer not null,
  preferred        integer not null,
  notetype         text not null,
  pinyin_raw       text not null default '',
  pinyin           text not null default '',
  meaning_raw      text not null default '',
  meaning          text not null default '',
  sentence         text not null default '',
  sentence_meaning text not null default '',
  primary key (simplified, deck, key_kind)
);

create table deck_stats(
  deck          text not null,
  role          text not null,
  template_kind text not null,
  notetype      text not null,
  total         integer not null,
  studied       integer not null,
  mature        integer not null,
  new_left      integer not null,
  primary key (deck, template_kind, notetype)
);

create table deck_limits(
  deck        text primary key,
  new_per_day integer not null,
  updated_at  integer not null
);

create table flagged(
  id            integer primary key,
  simplified    text not null,
  deck          text not null,
  template_kind text not null,
  template_ord  integer not null,
  flag          text not null,
  status        text not null,
  suspended     integer not null,
  pinyin        text not null,
  meaning       text not null,
  notetype      text not null
);

create table reviews_daily(
  date           text not null,
  deck           text not null,
  template_kind  text not null,
  notetype       text not null,
  reviews        integer not null,
  new            integer not null,
  ms             integer not null,
  mature_reviews integer not null,
  mature_passed  integer not null,
  primary key (date, deck, template_kind, notetype)
);

create table progression_weekly(
  date          text not null,
  deck          text not null,
  template_kind text not null,
  notetype      text not null,
  mature        integer not null,
  young         integer not null,
  learning      integer not null,
  relearning    integer not null,
  primary key (date, deck, template_kind, notetype)
);

-- Two indexes, not five. `words` is a ROWID table on purpose: with `without rowid` and
-- a three-column text primary key, every secondary index stores that whole key again,
-- which cost 48.6 MB for 129,215 rows. The primary key's own index already serves every
-- lookup by `simplified`, so no separate one is needed.
create index words_role_status on words(role, status);
"""

#: Every table the rebuild replaces. `deck_limits` is NOT here: only the maturity-gate
#: job can read Anki's deck-config protobuf, so the builder must not empty it.
_REBUILT_TABLES = ("words", "deck_stats", "flagged", "reviews_daily",
                   "progression_weekly", "meta")


# ── reading the collection ────────────────────────────────────────────

def source_mod(collection_path=None):
    collection_path = collection_path or DEFAULT_COLLECTION
    """`col.mod` from the live collection. About 5 ms; safe against a live writer."""
    con = sqlite3.connect(f"file:{collection_path}?mode=ro", uri=True, isolation_level=None)
    try:
        return con.execute("select mod from col").fetchone()[0]
    finally:
        con.close()


def _config(con):
    out = {}
    for key, val in con.execute("select key, val from config"):
        try:
            out[key] = json.loads(bytes(val).decode())
        except Exception:
            out[key] = None
    return out


def _read_collection(collection_path, _after_mod_read=None):
    """Everything the projection needs, from ONE snapshot.

    `_after_mod_read` is a TEST SEAM and nothing else may pass it. A test uses it to
    commit a write between the `mod` read and the row read, which is the only way to make
    a wrong read order fail.
    """
    con = sqlite3.connect(f"file:{collection_path}?mode=ro", uri=True, isolation_level=None)
    try:
        con.execute("BEGIN")
        mod, crt = con.execute("select mod, crt from col").fetchone()
        if _after_mod_read is not None:
            _after_mod_read()
        cfg = _config(con)
        deck_rows = list(con.execute("select id, name from decks"))
        notetypes = {i: n for i, n in con.execute("select id, name from notetypes")}
        templates = {(ntid, ord_): name
                     for ntid, ord_, name in con.execute("select ntid, ord, name from templates")}
        fields = defaultdict(dict)
        for ntid, ord_, name in con.execute("select ntid, ord, name from fields"):
            fields[ntid][name] = ord_
        cards = con.execute(
            "select c.id, c.did, c.odid, c.ord, c.type, c.queue, c.ivl, c.due, c.odue,"
            "       c.flags, c.lapses, n.id, n.mid, n.flds, n.sfld "
            "from cards c join notes n on n.id = c.nid").fetchall()
        note_count = con.execute("select count(*) from notes").fetchone()[0]
        revlog = con.execute(
            "select cid, id, ease, type, lastIvl, time from revlog "
            "where ease > 0 order by id").fetchall()
        con.execute("COMMIT")
    finally:
        con.close()
    return dict(mod=mod, crt=crt, cfg=cfg, deck_rows=deck_rows, notetypes=notetypes,
                templates=templates, fields=fields, cards=cards, note_count=note_count,
                revlog=revlog)


def _bucket_date(unix_secs):
    return time.strftime("%Y-%m-%d", time.gmtime(unix_secs - DAY_OFFSET))


def _progression_bucket(ivl, rtype):
    """Same buckets as bot._stats_progression, ported unchanged."""
    if rtype == 2:
        return "relearning"
    if ivl <= 0:
        return "learning"
    return "young" if ivl < MATURE_IVL else "mature"


def build(collection_path=None, cache_path=None, _after_mod_read=None):
    """Replace the cache from the collection. Returns the new meta dict."""
    collection_path = collection_path or DEFAULT_COLLECTION
    cache_path = cache_path or CACHE_PATH
    started = time.time()
    src = _read_collection(collection_path, _after_mod_read)

    missing = decks.missing_from_rows(src["deck_rows"])
    if missing:
        # Loud, and it stops the cache. A rename is then visible within 30 s instead of
        # sitting dead in a background job for months, which is what happened before.
        raise decks.DeckMissing(
            "required deck(s) missing from the collection: "
            + ", ".join(repr(n) for n in missing))
    resolved = decks.resolve_rows(src["deck_rows"])
    unexpected = decks.unexpected_in_rows(src["deck_rows"])

    now = int(time.time())
    rollover = src["cfg"].get("rollover")
    if rollover is None:
        raise BuildError("config.rollover is absent; this collection predates the v2 "
                         "scheduler and the day number cannot be derived")
    today, next_day_at = sched_timing(
        src["crt"], int(rollover), int(src["cfg"].get("creationOffset") or 0),
        int(src["cfg"].get("localOffset") or 0), now)

    vocab_ntid = next((i for i, n in src["notetypes"].items() if n == VOCAB_NOTETYPE), None)
    text_ord = {}
    if vocab_ntid is not None:
        text_ord = {name: src["fields"][vocab_ntid].get(name) for name in _TEXT_FIELDS}

    rows = {}
    stats = defaultdict(lambda: [0, 0, 0, 0])
    flagged = []
    card_group = {}
    skipped = 0

    for (cid, did, odid, ord_, ctype, queue, ivl, due, odue, flags, lapses,
         nid, mid, flds, sfld) in src["cards"]:
        home = odid or did
        name, role = resolved.get(home, (None, None))
        if role is None:
            # An undeclared deck. Skipping is deliberate: raising would let a stray deck
            # synced from a phone take the cache -- and every consumer -- down. The count
            # and the names go into meta so it stays visible.
            skipped += 1
            continue
        notetype = src["notetypes"].get(mid, "")
        tname = src["templates"].get((mid, ord_), "")
        kind = template_kind(tname, ord_)
        status = card_status(ctype, ivl)
        blocked = card_blocked(queue)
        parts = flds.split("\x1f")
        word = canonical(parts[0] if parts else "")

        group = (name, kind, notetype)
        card_group[cid] = group
        bucket = stats[group]
        bucket[0] += 1
        if ctype in (1, 2):
            bucket[1] += 1
        if ctype == 2 and ivl >= MATURE_IVL:
            bucket[2] += 1
        if ctype == 0 and blocked is None:
            bucket[3] += 1

        flag = flags & 7
        if flag:
            def _text(field):
                i = text_ord.get(field)
                return canonical(parts[i]) if mid == vocab_ntid and i is not None and i < len(parts) else ""
            flagged.append((word, name, kind, ord_, FLAG_NAMES.get(flag, str(flag)),
                            status, 1 if blocked == "suspended" else 0,
                            _text("Pinyin"), _text("Meaning"), notetype))

        if not word:
            skipped += 1
            continue

        # The archive collapses to ONE row per word: no consumer needs a deck or a
        # template inside it, and keeping the detail costs 96,988 rows instead of 56,066.
        key = (word, name, "any" if role == decks.ARCHIVE else kind)
        # pinyin and meaning: every non-archive vocabulary row, because
        # /api/deck/{name}/words publishes them for `Cloze` as well as the study decks.
        # sentences: the recognition role only, because jiangchinese is their one reader
        # and it reads that role. Storing them everywhere cost 24 MB for no reader.
        keep_text = mid == vocab_ntid and role != decks.ARCHIVE
        keep_sentence = keep_text and role == decks.RECOGNITION

        def _pair(field, keep=None):
            i = text_ord.get(field)
            if not (keep_text if keep is None else keep) or i is None or i >= len(parts):
                return "", ""
            return parts[i], canonical(parts[i])

        rank = (_STATUS_RANK[status], 0 if blocked else 1, ivl)
        prev = rows.get(key)
        if prev is None or rank > prev[0]:
            # Carry the running count across a replacement. Building the new row with
            # card_count=0 discarded it, and 540 of 258,959 cards went missing from the
            # totals -- a test caught it, nothing else would have.
            carried = prev[1]["card_count"] if prev is not None else 0
            pin_raw, pin = _pair("Pinyin")
            mean_raw, mean = _pair("Meaning")
            _, sentence = _pair("SentenceSimplified", keep_sentence)
            _, sentence_meaning = _pair("SentenceMeaning", keep_sentence)
            rows[key] = [rank, dict(
                simplified=word, sort_field=(sfld or ""), deck=name, role=role,
                key_kind=key[2], template_kind=kind, template_name=tname, status=status,
                relearning=1 if ctype == 3 else 0, blocked=blocked, interval=ivl,
                lapses=lapses,
                overdue_days=overdue_days(queue, due, odue, odid, now, today),
                created_at=nid // 1000, card_count=carried, preferred=0, notetype=notetype,
                pinyin_raw=pin_raw, pinyin=pin, meaning_raw=mean_raw, meaning=mean,
                sentence=sentence, sentence_meaning=sentence_meaning)]
        rows[key][1]["card_count"] += 1

    # Which row REPRESENTS a word, for /api/status. Ported from bot._vocab_status_map:
    # ranking on interval alone named the archive for ~31,000 words, and ranking on
    # live-and-not-archived alone named a production deck for 23.
    best = {}
    for row in (r[1] for r in rows.values()):
        rank = (1 if row["template_kind"] == RECOGNITION else 0,
                0 if row["blocked"] else 1,
                0 if row["role"] == decks.ARCHIVE else 1,
                row["interval"])
        cur = best.get(row["simplified"])
        if cur is None or rank > cur[0]:
            best[row["simplified"]] = (rank, row)
    for _, row in best.values():
        row["preferred"] = 1

    daily, weekly = _review_tables(src["revlog"], card_group, now)
    meta = dict(
        schema_version=SCHEMA_VERSION, generated_at=now, checked_at=now,
        paused_until=None, source_mod=src["mod"], build_seconds=0.0,
        card_count=len(src["cards"]), note_count=src["note_count"], today=today,
        next_day_at=next_day_at, day_offset=DAY_OFFSET,
        unexpected_decks=", ".join(unexpected), skipped_cards=skipped)
    roles = {name: role for name, role in resolved.values() if role}
    _write(cache_path, meta, [r[1] for r in rows.values()], stats, flagged, daily, weekly,
           roles, started)
    return meta


def _review_tables(revlog, card_group, now):
    """reviews_daily and progression_weekly, keyed by (date, deck, kind, notetype).

    Keyed per deck, not per role, so /api/stats can sum any requested deck subset. The
    weekly boundaries come from the FIRST review in the whole collection, so every group
    shares one date axis and the sums line up. Boundaries run two weeks past `now`; the
    handler truncates to its own `now + 7 days`, which is what bot._stats_progression does.
    """
    daily = defaultdict(lambda: [0, 0, 0, 0, 0])
    per_card = defaultdict(list)
    for cid, rid, ease, rtype, last_ivl, rtime in revlog:
        group = card_group.get(cid)
        if group is None:
            continue
        key = (_bucket_date(rid / 1000), *group)
        row = daily[key]
        row[0] += 1
        if rtype == 0:
            row[1] += 1
        row[2] += rtime or 0
        if last_ivl >= MATURE_IVL and rtype in (1, 2):
            row[3] += 1
            if ease >= 2:
                row[4] += 1
        per_card[cid].append((rid, last_ivl, rtype))

    weekly = defaultdict(lambda: {"mature": 0, "young": 0, "learning": 0, "relearning": 0})
    if per_card:
        first = min(v[0][0] for v in per_card.values()) / 1000
        boundary = first - ((first - DAY_OFFSET) % 86400)
        # bisect, not a scan: the same shape as bot._stats_progression. Scanning each
        # card's whole history once per weekly boundary made the build 10.9 s.
        histories = {}
        for cid, entries in per_card.items():
            entries.sort()
            histories[cid] = (entries, [e[0] for e in entries])
        while boundary <= now + 14 * 86400:
            stamp = boundary * 1000
            date = _bucket_date(boundary)
            for cid, (entries, stamps) in histories.items():
                i = bisect.bisect_right(stamps, stamp) - 1
                if i < 0:
                    continue
                _, ivl, rtype = entries[i]
                weekly[(date, *card_group[cid])][_progression_bucket(ivl, rtype)] += 1
            boundary += 7 * 86400
    return daily, weekly


# ── writing the cache ─────────────────────────────────────────────────

def _connect_rw(cache_path):
    con = sqlite3.connect(cache_path, isolation_level=None, timeout=30.0)
    con.execute("pragma busy_timeout = 30000")
    con.execute("pragma journal_mode = wal")
    # The cache is fully derived and rebuilds from the collection in seconds, so a torn
    # write after a power cut costs nothing: the next poll rebuilds it. Durability is
    # therefore not worth the fsyncs -- they were most of a 10 s build.
    con.execute("pragma synchronous = off")
    con.execute("pragma temp_store = memory")
    return con


def _begin_immediate(con, attempts=5):
    """BEGIN IMMEDIATE, with a bounded retry.

    A deferred transaction that reads and then writes raises "database is locked"
    IMMEDIATELY on the upgrade, and no busy timeout retries it -- measured at 0.00 s
    against a 5 s timeout. Two threads write this file: the rebuild and the maturity
    gate's deck_limits write.
    """
    for attempt in range(attempts):
        try:
            con.execute("BEGIN IMMEDIATE")
            return
        except sqlite3.OperationalError:
            if attempt == attempts - 1:
                raise
            time.sleep(0.2 * (attempt + 1))


def _write(cache_path, meta, rows, stats, flagged, daily, weekly, roles, started):
    fresh = not os.path.exists(cache_path)
    con = _connect_rw(cache_path)
    try:
        have = {r[0] for r in con.execute(
            "select name from sqlite_master where type='table'")}
        if "words" not in have:
            con.executescript(_SCHEMA)
        _begin_immediate(con)
        try:
            # deck_limits survives: only the gate job can read Anki's deck-config
            # protobuf, so emptying it here would publish new_per_day as absent.
            for table in _REBUILT_TABLES:
                con.execute(f"delete from {table}")
            cols = ("simplified sort_field deck role key_kind template_kind template_name status "
                    "relearning blocked interval lapses overdue_days created_at card_count "
                    "preferred notetype pinyin_raw pinyin meaning_raw meaning sentence "
                    "sentence_meaning").split()
            con.executemany(
                f"insert into words({','.join(cols)}) values ({','.join('?' * len(cols))})",
                [tuple(r[c] for c in cols) for r in rows])
            con.executemany(
                "insert into deck_stats(deck, role, template_kind, notetype, total, "
                "studied, mature, new_left) values (?,?,?,?,?,?,?,?)",
                [(deck, roles.get(deck, ""), kind, nt, *vals)
                 for (deck, kind, nt), vals in stats.items()])
            con.executemany(
                "insert into flagged(simplified, deck, template_kind, template_ord, flag, "
                "status, suspended, pinyin, meaning, notetype) values (?,?,?,?,?,?,?,?,?,?)",
                flagged)
            con.executemany(
                "insert into reviews_daily(date, deck, template_kind, notetype, reviews, "
                "new, ms, mature_reviews, mature_passed) values (?,?,?,?,?,?,?,?,?)",
                [(*k, *v) for k, v in daily.items()])
            con.executemany(
                "insert into progression_weekly(date, deck, template_kind, notetype, "
                "mature, young, learning, relearning) values (?,?,?,?,?,?,?,?)",
                [(*k, v["mature"], v["young"], v["learning"], v["relearning"])
                 for k, v in weekly.items()])
            # Measured LAST, so it covers the projection AND the write. Measuring it
            # before the write reported 5.2 s for a 10.9 s build.
            meta["build_seconds"] = round(time.time() - started, 3)
            con.execute(
                "insert into meta(id, schema_version, generated_at, checked_at, "
                "paused_until, source_mod, build_seconds, card_count, note_count, today, "
                "next_day_at, day_offset, unexpected_decks, skipped_cards) "
                "values (1,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (meta["schema_version"], meta["generated_at"], meta["checked_at"],
                 meta["paused_until"], meta["source_mod"], meta["build_seconds"],
                 meta["card_count"], meta["note_count"], meta["today"],
                 meta["next_day_at"], meta["day_offset"], meta["unexpected_decks"],
                 meta["skipped_cards"]))
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise
        # A full-table replace writes the whole database into the WAL, and autocheckpoint
        # cannot reclaim it while any reader holds an older snapshot. Five long-lived pm2
        # readers is exactly that shape: six rebuilds grew a test WAL to 24 MB.
        con.execute("pragma wal_checkpoint(truncate)")
    finally:
        con.close()
    if fresh:
        # collection.anki2 is 0600 and this holds the same vocabulary. The umask is 0002
        # and the directory is 0775, so a new file would be world-readable.
        os.chmod(cache_path, 0o600)


# ── the trigger ───────────────────────────────────────────────────────

def poll(collection_path=None, cache_path=None):
    """Rebuild when `col.mod` moved. Returns the new meta on a rebuild, else None.

    There is no cheap "did anything really change" shortcut, on purpose. A signature over
    row counts and max(mod) is blind to a notetype rename, and blind to two writes inside
    one second, because cards.mod holds SECONDS while col.mod holds MILLISECONDS. A blind
    skip is permanent, because the skip also advances source_mod. Sampling the live
    collection every 30 s for 22 minutes recorded 0 spurious `col.mod` changes, so the
    shortcut buys nothing and costs a whole class of defect.
    """
    collection_path = collection_path or DEFAULT_COLLECTION
    cache_path = cache_path or CACHE_PATH
    mod = source_mod(collection_path)
    try:
        con = connect_ro(cache_path)
    except CacheError:
        return build(collection_path, cache_path)
    try:
        meta = read_meta(con)
    finally:
        con.close()
    if meta["source_mod"] == mod:
        touch(cache_path)
        return None
    return build(collection_path, cache_path)


def touch(cache_path=None, when=None):
    """Record that the cache was confirmed against the collection just now.

    Freshness is `checked_at`, never `generated_at`: a cache built six hours ago from a
    collection nobody touched is correct, not stale.
    """
    con = _connect_rw(cache_path or CACHE_PATH)
    try:
        _begin_immediate(con)
        con.execute("update meta set checked_at = ? where id = 1", (int(when or time.time()),))
        con.execute("COMMIT")
    finally:
        con.close()


def set_pause(cache_path=None, seconds=None):
    """Declare a maintenance window, so a deliberate stop is not read as staleness.

    freq_data/anki_op.sh stops the bot for the length of a write operation. `checked_at`
    then freezes, and every strict consumer would refuse. `seconds=None` clears it. A
    pause EXPIRES, so a script that dies cannot silence the check forever.
    """
    until = None if seconds is None else int(time.time()) + int(seconds)
    con = _connect_rw(cache_path or CACHE_PATH)
    try:
        _begin_immediate(con)
        con.execute("update meta set paused_until = ? where id = 1", (until,))
        con.execute("COMMIT")
    finally:
        con.close()
    return until


def write_deck_limits(limits, cache_path=None):
    """{deck name: new cards per day}, from the maturity-gate job.

    NOT from the builder. The value lives in a protobuf blob that only the anki library
    parses, and the builder has no library by design. The gate job already holds the
    collection open every five minutes, so this adds no lock and no new open.
    """
    now = int(time.time())
    con = _connect_rw(cache_path or CACHE_PATH)
    try:
        _begin_immediate(con)
        con.executemany(
            "insert into deck_limits(deck, new_per_day, updated_at) values (?,?,?) "
            "on conflict(deck) do update set new_per_day=excluded.new_per_day, "
            "updated_at=excluded.updated_at",
            [(deck, int(n), now) for deck, n in limits.items()])
        con.execute("COMMIT")
    finally:
        con.close()


# ── the reader ────────────────────────────────────────────────────────

def connect_ro(cache_path=None):
    """A read-only handle, with the schema version checked.

    NOTE for a consumer: the cache is a WAL database, so SQLite must be able to create
    and write `cache.db-shm`. That needs write permission on the DIRECTORY, even though
    the database itself is opened read-only. Every consumer runs as `vincent` today.
    """
    cache_path = cache_path or CACHE_PATH
    if not os.path.exists(cache_path):
        raise CacheMissing(f"no cache at {cache_path}; the bot builds it within 30 s of start")
    con = sqlite3.connect(f"file:{cache_path}?mode=ro", uri=True, isolation_level=None)
    try:
        row = con.execute("select schema_version from meta where id = 1").fetchone()
    except sqlite3.OperationalError as exc:
        con.close()
        raise CacheIncomplete(f"{cache_path} has no meta table yet ({exc})") from exc
    if row is None:
        con.close()
        raise CacheIncomplete(f"{cache_path} holds no meta row; a first build is in progress")
    if row[0] != SCHEMA_VERSION:
        con.close()
        raise SchemaMismatch(
            f"{cache_path} is schema {row[0]}, this module expects {SCHEMA_VERSION}")
    con.row_factory = sqlite3.Row
    return con


def read_meta(con):
    row = con.execute("select * from meta where id = 1").fetchone()
    if row is None:
        raise CacheIncomplete("no meta row")
    meta = {k: row[k] for k in row.keys()}
    now = int(time.time())
    meta["age_seconds"] = now - meta["checked_at"]
    meta["paused"] = bool(meta["paused_until"] and meta["paused_until"] > now)
    return meta


def assert_fresh(con, max_age_seconds=DEFAULT_MAX_AGE):
    """Raise CacheStale unless the bot confirmed the cache recently, or declared a pause.

    For a consumer that must be CORRECT. The bot's own HTTP handlers use read_meta and
    publish `age_seconds` instead: /api/status is documented never to fail, and a
    human-facing dictionary page reads it.
    """
    meta = read_meta(con)
    if meta["paused"]:
        return meta
    if meta["age_seconds"] > max_age_seconds:
        raise CacheStale(
            f"cache last confirmed {meta['age_seconds']}s ago (limit {max_age_seconds}s); "
            "the bot is probably down")
    return meta


_HAN = re.compile(r"^[一-鿿]+$")


def _is_plain_word(text):
    """dong-chinese's rule: 1 to 6 characters, every one Han.

    It belongs to ONE consumer, so it lives here in the reader and never in the builder.
    Applying it to the projection dropped 82,530 cards, 52 of them in live decks, and
    removed 355 words from /api/status.
    """
    return 1 <= len(text) <= 6 and bool(_HAN.match(text))


def known_words(con):
    """{simplified: status} for every word the user is actually studying.

    Any non-archive deck, any template, nothing blocked, and not `new`. This reproduces
    dong-chinese's backfill_known_words.py exactly: restricting it to the recognition
    role loses 5 words known only through their `Reverse` card.
    """
    out = {}
    for row in con.execute(
            "select simplified, status from words "
            "where role != ? and blocked is null and status != 'new'", (decks.ARCHIVE,)):
        word, status = row["simplified"], row["status"]
        if not _is_plain_word(word):
            continue
        if _STATUS_RANK[status] > _STATUS_RANK.get(out.get(word, "new"), 0):
            out[word] = status
    # dong's table carries two values, so `young` folds into `learning`.
    return {w: ("mature" if s == "mature" else "learning") for w, s in out.items()}


def due_words(con, limit=12):
    """Words waiting in a queue, most overdue first. Recognition role only.

    The scope is a decision, recorded in READ_CACHE_PLAN.md step 3: the tutor reads
    `role = recognition`, which is HSK, HSK7-9, non-HSK and Mined. It therefore skips the
    80 due cards in `Reverse` and the 27 in `Cloze`.
    """
    return [dict(r) for r in con.execute(
        "select * from words where role = ? and blocked is null "
        "and overdue_days is not null order by overdue_days desc, simplified limit ?",
        (decks.RECOGNITION, limit))]


def leech_words(con, limit=12):
    """Words the user keeps failing: lapsed repeatedly and still on a short interval."""
    return [dict(r) for r in con.execute(
        "select * from words where role = ? and blocked is null "
        "and lapses >= ? and interval <= ? "
        "order by lapses desc, interval asc, simplified limit ?",
        (decks.RECOGNITION, LEECH_MIN_LAPSES, LEECH_MAX_IVL, limit))]


def word_status(con, words):
    """{word: the row that REPRESENTS it}, for /api/status. Absent words map to None."""
    out = {w: None for w in words}
    if not words:
        return out
    marks = ",".join("?" * len(words))
    for row in con.execute(
            f"select * from words where preferred = 1 and simplified in ({marks})",
            tuple(words)):
        out[row["simplified"]] = dict(row)
    return out


def deck_words(con, deck, template_kind=RECOGNITION, notetype=VOCAB_NOTETYPE):
    """Every word in one deck at one template. RAISES for a deck the cache does not hold.

    A caller that must return [] for a missing deck -- /api/deck/{name}/words publishes
    that -- catches NotInCache at the HTTP boundary. "Missing" and "empty" must not look
    the same down here.
    """
    known = {r[0] for r in con.execute("select distinct deck from words")}
    if deck not in known:
        raise NotInCache(f"no deck {deck!r} in the cache; it holds {sorted(known)}")
    return [dict(r) for r in con.execute(
        "select * from words where deck = ? and template_kind = ? and notetype = ? "
        "order by created_at desc, simplified", (deck, template_kind, notetype))]


def deck_stats(con, deck_names=None, notetype=VOCAB_NOTETYPE):
    """{deck: {total, studied, mature, new_left, new_per_day}} summed over templates."""
    limits = {r["deck"]: r["new_per_day"] for r in con.execute("select * from deck_limits")}
    known = {r[0] for r in con.execute("select distinct deck from deck_stats")}
    names = list(deck_names) if deck_names is not None else sorted(known)
    out = {}
    for name in names:
        if name not in known:
            raise NotInCache(f"no deck {name!r} in the cache; it holds {sorted(known)}")
        row = con.execute(
            "select coalesce(sum(total),0) t, coalesce(sum(studied),0) s, "
            "coalesce(sum(mature),0) m, coalesce(sum(new_left),0) n from deck_stats "
            "where deck = ? and notetype = ? and template_kind = ?",
            (name, notetype, RECOGNITION)).fetchone()
        out[name] = {"total": row["t"], "studied": row["s"], "mature": row["m"],
                     "new_left": row["n"],
                     # NULL, never 0. The dashboard computes PACE = limit || 0 and then
                     # divides by max(1, rate), so a 0 becomes a projection thousands of
                     # days out instead of a visible gap.
                     "new_per_day": limits.get(name)}
    return out


def flagged(con):
    """{total, by_flag, cards} -- every flagged card, in every deck and note type."""
    cards = [dict(r) for r in con.execute(
        "select * from flagged order by flag, id")]
    counts = defaultdict(int)
    for card in cards:
        counts[card["flag"]] += 1
    return {"total": len(cards),
            "by_flag": [{"name": n, "count": c} for n, c in sorted(counts.items())],
            "cards": cards}


def reviews(con, days=30, deck_names=None):
    """[{date, reviews, new, minutes}] for the last `days` days, newest last."""
    marks, args = "", []
    if deck_names is not None:
        marks = f" and deck in ({','.join('?' * len(deck_names))})"
        args = list(deck_names)
    rows = {r["date"]: r for r in con.execute(
        "select date, sum(reviews) reviews, sum(new) new, sum(ms) ms "
        f"from reviews_daily where template_kind = ?{marks} group by date",
        (RECOGNITION, *args))}
    today = time.time()
    out = []
    for offset in range(days - 1, -1, -1):
        date = _bucket_date(today - offset * 86400)
        row = rows.get(date)
        out.append({"date": date,
                    "reviews": row["reviews"] if row else 0,
                    "new": row["new"] if row else 0,
                    "minutes": round((row["ms"] if row else 0) / 60000)})
    return out


def progression(con, deck_names=None, until=None):
    """[{date, Mature, Young, Learning, Relearning}] weekly, oldest first."""
    marks, args = "", []
    if deck_names is not None:
        marks = f" and deck in ({','.join('?' * len(deck_names))})"
        args = list(deck_names)
    cutoff = _bucket_date((until or time.time()) + 7 * 86400)
    return [{"date": r["date"], "Mature": r["m"], "Young": r["y"],
             "Learning": r["l"], "Relearning": r["r"]}
            for r in con.execute(
                "select date, sum(mature) m, sum(young) y, sum(learning) l, "
                f"sum(relearning) r from progression_weekly where date <= ?{marks} "
                "group by date order by date", (cutoff, *args))]


# ── a command line, so a shell script needs no python of its own ──────

def _main(argv):
    import argparse
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("action", choices=("build", "poll", "status", "pause", "unpause"))
    parser.add_argument("seconds", nargs="?", type=int, default=1800,
                        help="pause: how long the window may last (default 1800)")
    parser.add_argument("--cache", default=CACHE_PATH)
    parser.add_argument("--collection", default=DEFAULT_COLLECTION)
    parser.add_argument("--max-age", type=int, default=DEFAULT_MAX_AGE)
    args = parser.parse_args(argv)

    if args.action == "build":
        meta = build(args.collection, args.cache)
        print(f"built in {meta['build_seconds']}s: {meta['card_count']} cards, "
              f"today={meta['today']}, source_mod={meta['source_mod']}")
        return 0
    if args.action == "poll":
        meta = poll(args.collection, args.cache)
        print(f"rebuilt in {meta['build_seconds']}s" if meta else "unchanged")
        return 0
    if args.action == "pause":
        print(f"paused until {set_pause(args.cache, args.seconds)}")
        return 0
    if args.action == "unpause":
        set_pause(args.cache, None)
        print("pause cleared")
        return 0
    con = connect_ro(args.cache)
    try:
        meta = read_meta(con)
        state = "PAUSED" if meta["paused"] else (
            "STALE" if meta["age_seconds"] > args.max_age else "fresh")
        print(f"{state}: confirmed {meta['age_seconds']}s ago, built "
              f"{int(time.time()) - meta['generated_at']}s ago in "
              f"{meta['build_seconds']}s, {meta['card_count']} cards, today={meta['today']}")
        if meta["unexpected_decks"]:
            print(f"  UNEXPECTED DECKS: {meta['unexpected_decks']}")
        if meta["skipped_cards"]:
            print(f"  skipped cards: {meta['skipped_cards']}")
        return 0 if state != "STALE" else 1
    finally:
        con.close()


if __name__ == "__main__":
    import sys
    raise SystemExit(_main(sys.argv[1:]))
