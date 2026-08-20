# Plan: the shared read cache — version 2

**Status:** steps 1 and 2 are done and live. Steps 3-5 are not started.
This plan implements `READ_CACHE_BRIEF.md`.
**Version 2, 2026-08-19.** Version 1 went through three adversarial reviews. They found
32 defects in it. Every number below is measured again, because version 1's headline
numbers came from a prototype that carried a defect (§3.1).

Read `READ_CACHE_BRIEF.md` first. Where this plan disagrees with the brief, it says so
and gives the measurement.

---

## 1. Measured facts

Every number comes from a command run on 2026-08-19 against a copy of the live
collection. None is remembered.

| Fact | Value |
|---|---|
| `col.mod` changes on a write | yes: `1787179141392` → `1787180956069` |
| `col.mod` changes on open/close | **no** |
| `col.mod` moved in 18 minutes of idle running | **0 times** (37 samples, 30 s apart) |
| read `col.mod` read-only from the live file | 5 ms, WAL |
| read all 258,959 card+note rows | 1.3 s |
| **full rebuild, as built** | **6.2 s → 129,215 rows → 31.2 MB** |
| the same without the archive collapse | 224,912 rows → 48.7 MB |
| flagged cards | 43 |
| revlog rows, whole collection | 21,192 (truncated; known) |
| relearning cards (`type=3`) | 20 |
| cards whose `odid != 0` (filtered deck) | **0** — the risky path has no live data |
| cards in queue 3 (day-learn) | **0** — same |
| cards in queue 1 (intraday learning) | 36 |
| the 54 tests passed before this work | 25.4 s |
| the suite with the 43 cache tests | 94+43 tests, about 105 s |

The collection holds 8 decks and no subdecks. Card counts: Archive 213,434, Cloze 17,448,
non-HSK 9,950, Reverse 7,402, HSK7-9 5,420, HSK 4,859, Mined 446, Default 0.

## 2. Five corrections to the brief

1. **The bot does not hold an open collection handle.** It opens and closes per
   operation (`bot.py:100`, 17 call sites). The builder therefore uses its own read-only
   sqlite connection and never opens the anki library. It takes no lock.
2. **The projection is 129,215 rows and 31.2 MB, not ~55,000 rows.** A rebuild costs
   6.2 s, not 1.2 s. It still replaces a 111 MB snapshot.
3. **`status` needs four values.** `/api/hsk-levels` already separates `young` (a review
   card under 21 days) from `learning`. So `status` is `new` / `learning` / `young` /
   `mature`, and suspension is a separate column. The brief folds them together, which
   gives one fact two homes.
4. **There is no separate `due` table.** `overdue_days` is a property of a card, so it is
   a column on `words`. A second table could disagree with the first.
5. **`role` has five values, not four.** `decks.py:24` declares `RESERVED` and assigns it
   to `Default`. The cache stores it and the reader excludes it.

## 3. What the adversarial review changed

Three reviews ran in parallel: SQLite and Anki semantics, consumer contracts, and process
and operations. I verified their most damaging claims myself before I accepted them.

### 3.1 The version-1 prototype carried a defect that set the plan's numbers

**Version 1 measured the projection with dong-chinese's word filter applied** — keep only
1 to 6 pure Han characters. That filter belongs to one consumer, not to the cache.

Measured cost of that mistake:

* It drops **82,530 cards**. 52 of them sit in live decks: 21 in `Reverse`, 20 in
  `non-HSK`, 10 in `Cloze`, 1 in `HSK`.
* It removes **355 words** from `/api/status`, among them `可怕（的）`, `还好（了）`,
  `三Q/3Q`. The dictionary site would then say "not in your deck" for words that have
  cards.
* Version 1's "101,534 rows / 14.8 MB" came from the filtered run. The real figures are
  129,215 rows and 31.2 MB.

**The builder now stores every card.** The filter moves into `known_words()`, which is
the one reader that wants it.

### 3.2 Accepted findings

| # | Finding | Where it lands |
|---|---|---|
| 1 | The naive day number disagrees with Anki for 9 hours a day | §6.1 rule 6 |
| 2 | The content signature is blind to real changes | deleted, §6.1 rule 5 |
| 3 | `deck_stats` must carry `notetype` | §5 |
| 4 | `progression` cannot come from a daily aggregate | §5, `progression_weekly` |
| 5 | `recent` and two orderings need note age | §5, `created_at` |
| 6 | `direction` contradicts `DECK_REFERENCE.md` | §5, renamed `template_kind` |
| 7 | Raw-SQL name lookup fails on Anki's `unicase` collation | §6.1 rule 3 |
| 8 | Field 0 carries HTML; the key column must be canonical | §6.1 rule 4 |
| 9 | The primary key needs a written rank rule and `card_count` | §6.1 rule 7 |
| 10 | `status` cannot keep `/api/stats`'s published `studied` | §5, `relearning` |
| 11 | Two endpoints publish unstripped text | §5, raw and clean columns |
| 12 | `/api/flagged` publishes an `ord` integer | §5, `flagged.template_ord` |
| 13 | A `BEGIN` that reads then writes fails and no timeout retries it | §6.1 rule 8 |
| 14 | Nothing checkpoints the cache WAL | §6.1 rule 9 |
| 15 | `cache.db` would be world-readable | §6.1 rule 10 |
| 16 | `known_words` scoped to recognition loses 5 words | §7 step 2 |
| 17 | jiangchinese's "leech" is a substring match | §5, `lapses`; resolved in §11.1 |
| 18 | `POST /api/sync` must force a rebuild | §7 step 4 |
| 19 | `deck_limits` has an empty window and publishes 0 | §6.3 |
| 20 | The gate's `try/except` would hide a cache failure | §6.3 |
| 21 | Buried cards (`queue` -2/-3) have no representation | §5, `blocked` |
| 22 | The 6.2 s build must not run on the event loop | §7 step 1 |
| 23 | The reader never checks `schema_version` | §6.2 |
| 24 | Two consumers are missing from the list | §4 |
| 25 | The mtime/size write guard cannot detect a WAL write | §8, and §11 |
| 26 | The job wiring and the route have no test | §8 |
| 27 | The snapshot-ordering test needs an injection seam | §8 |
| 28 | `sortf` is not a column, and that test always passes | §8 |
| 29 | The fixture must redirect `CACHE_PATH` | §8 |
| 30 | Step 4's baseline diff cannot work across days | §7 step 4 |
| 31 | Step 3's rollback fails because `.env` is not in git | §10 |
| 32 | Step 2's stated diagnosis was wrong | §7 step 2 |

### 3.3 One simplification the review made possible

**The content signature is deleted.** Version 1 planned to skip a rebuild when `col.mod`
moved but a cheap signature matched. The review proved the signature is blind to a
notetype rename and to two writes in the same second, because `cards.mod` and `notes.mod`
hold seconds while `col.mod` holds milliseconds. A blind skip is permanent, because the
skip also advances `source_mod`.

The measurement removes the need for it: `col.mod` did not move once in 18 minutes of
idle running, so the AnkiWeb sync does not bump it. **Every `col.mod` change now triggers
a rebuild.** 6.2 s per real change is affordable, and a whole class of defect disappears.

## 4. The consumers

Seven, not five. The brief lists five.

| Service | Reaches Anki by | Moves to the cache |
|---|---|---|
| anki-bot (`:8103`) | the anki library, read and write | step 4, internal only |
| dong-chinese backfill (cron, 6 h) | the live file, `mode=ro` | **step 2** |
| jiangchinese-api (pm2) — **STOPPED 2026-08-20** | a 05:15 snapshot copy | **step 3** |
| chinese-dashboard (cron, 6 h) | anki-bot HTTP | no change |
| comprehensiblemandarin (pm2) | anki-bot HTTP | no change |
| **chinese-dict (`:3020`)** | anki-bot HTTP, proxies `/api/status` and `/api/card` | no change |
| **chinese-dashboard-refresh (`:3021`)** | anki-bot HTTP, posts `/api/sync` | no change |

Two readers stay on the collection **on purpose**, and the brief's "no consumer opens the
collection" does not cover them:

* `cli.py` — a human tool that also writes. It needs Anki's search syntax.
* `freq_data/weekly_report.py` — cron, Mondays 09:00. It reads per-card revlog history.
  It opens the collection with the anki library and contends with the bot for up to 60 s.
  This plan accepts that contention; it does not solve it.

## 5. The schema

`cache.db` lives at `/home/vincent/anki-headless/cache.db`, in WAL mode, mode `0600`.
Only the bot writes it.

**The canonical schema is `_SCHEMA` in `anki_cache.py`.** It is not repeated here: two
copies of a schema drift, and that is the defect class this whole plan exists to remove.
What matters about its shape:

| Table | Holds | Keyed by |
|---|---|---|
| `meta` | one row: freshness, `source_mod`, Anki's `today`, and what the build skipped | — |
| `words` | the projection | `(simplified, deck, key_kind)` |
| `deck_stats` | counts, per note type | `(deck, template_kind, notetype)` |
| `deck_limits` | `new_per_day`, written by the gate job only | `deck` |
| `flagged` | one row per flagged card, 43 today | a surrogate id |
| `reviews_daily` | revlog, bucketed | `(date, deck, template_kind, notetype)` |
| `progression_weekly` | the weekly maturity mix | `(date, deck, template_kind, notetype)` |

Columns worth naming, and why each exists:

* `simplified` is canonical; `sort_field` mirrors Anki's own `sfld`, which is what
  `/api/stats`' words and `/api/deck/{name}/words` publish today.
* `template_kind` (`recognition` / `speaking` / `cloze` / `other`) comes from the
  template's NAME, not from `ord` arithmetic. `flagged.template_ord` is the one place an
  ord survives, because `/api/flagged` publishes it.
* `status` is `new` / `learning` / `young` / `mature`; `relearning` is separate so
  `/api/stats` keeps its published `studied` (`type IN (1,2)`).
* `blocked` is `suspended` / `buried` / NULL, because `queue` also carries -2 and -3.
* `lapses` drives the leech rule; `card_count` records how many cards a row stands for;
  `preferred` marks the one row that represents a word for `/api/status`.
* `reviews_daily` and `progression_weekly` are keyed per DECK, not per role, so
  `/api/stats` can sum any requested deck subset.

Both review tables carry `ms`, not minutes, and the reader rounds — the same accumulator
`bot._deck_stats` uses.

Every table is a plain ROWID table. `without rowid` with a three-column text key made
every secondary index store that whole key again, and the file was 48.6 MB instead of
31.2 MB.

Seven schema decisions, each with its reason:

* **`template_kind`, not `direction`, and it comes from the template NAME.** The
  `templates` table gives each template's name directly, so no `ord` arithmetic is
  needed: `Hanzi-English` → `recognition`, `English-Speaking` → `speaking`,
  `Cloze-Recall` → `cloze`, anything else → `other`. Version 1 called ord 2 "cloze" and
  ord 1 "production". `DECK_REFERENCE.md:197-199` says **both** ords 1 and 2 are
  production-direction drills, so version 1 invented a third vocabulary for the same
  thing.
* **`template_ord` exists in exactly one table.** `/api/flagged` publishes an `ord`
  integer (`APIS.md:113`). The `flagged` table carries it so the contract survives. No
  other table has it, and no other consumer sees it.
* **The archive collapses to one row per word, with `key_kind = 'any'`.** No consumer
  needs a deck or a template inside the archive. Collapsing costs 129,215 rows and
  27.6 MB; keeping the detail costs 224,912 rows and 48.7 MB. Both are measured. The
  `flagged` table is exact and unfiltered, so a flag on an archive card still resolves.
* **Raw and clean text, both.** `APIS.md:122-123` states that `/api/stats`' `words` and
  `/api/deck/{name}/words` do **not** strip HTML, while `/api/flagged` does. One column
  cannot serve both, and the three existing cleaners disagree with each other.
* **`relearning` is its own column.** `/api/stats` counts `studied` as `type IN (1,2)`,
  which excludes the 20 relearning cards. `status` maps type 3 to `learning`. Keeping the
  published number needs both facts.
* **`blocked`, not a `suspended` boolean.** Anki's `queue` also holds -2 and -3 for buried
  cards. The collection has none today, but `config.lastUnburied` is set, so burying is in
  use. A buried card would otherwise look live with no due date.
* **`lapses` is stored; `tags` is not.** The one consumer that wanted a tag was
  jiangchinese's leech list, and §11.1 replaced the tag rule with a lapse rule. Nothing
  else reads a tag, so the column would be size with no reader. `lapses` is Anki's durable
  counter and survives the revlog truncation.

## 6. The module

One new file, `anki_cache.py`, beside `decks.py`. It imports the standard library and
`decks`, and nothing else. A test asserts that importing it does not import `anki`.

### 6.1 The writer

```python
SCHEMA_VERSION = 1
CACHE_PATH     = "/home/vincent/anki-headless/cache.db"

def source_mod(collection_path=...) -> int
def build(collection_path=..., cache_path=..., _after_mod_read=None) -> dict
def poll(collection_path=..., cache_path=...) -> dict | None
```

Ten rules. Each one exists because the review broke the version without it.

1. **One snapshot in.** `build()` opens the collection `mode=ro`, runs `BEGIN`, and reads
   `col.mod` **and** every row inside that one transaction. A `mod` read outside the
   snapshot records a state the cache does not hold, and the cache never catches up.
   `_after_mod_read` is a test seam, and nothing else may use it.
2. **`immutable` is never set.** It skips the WAL, so a committed row reads as absent.
3. **No name lookup in SQL.** `decks.name` and `notetypes.name` carry Anki's `unicase`
   collation, which plain sqlite3 does not have. Verified: `select id from decks where
   name='HSK'` raises `no such collation sequence: unicase`, and so does `order by name`.
   The builder reads `select id, name from decks` with no `WHERE`, converts `\x1f` to
   `::`, and compares in Python with case folding. `decks.py` gains one pure-Python
   resolver that takes `[(id, name)]`, and `decks.deck_ids_for` uses the same one. Two
   implementations of "does this deck exist" is how this project got three answers to
   that question before.
4. **The key column is canonical.** Field 0 carries HTML: 967 `ChineseSentences` notes,
   17 `ChineseVocabulary` notes and 1 `Basic` note differ from their `sfld`. Real values
   include `<span id="docs-internal-guid-…">建筑</span>` and `&nbsp;臭宝`. Six of those
   cards are live and studied, and nine are HSK words that `/api/hsk-levels` matches by
   string. `simplified` is cleaned; `raw` keeps the original.
5. **Every `col.mod` change rebuilds.** There is no signature and no skip. See §3.3.
6. **The day number comes from Anki's rule, not from `(now - crt) // 86400`.** Measured
   today: `col.sched.today` is 246 and the naive formula gives 247. `config.rollover` is
   4 and `config.creationOffset` is -540. The two agree from 04:00 to 19:00 UTC and
   disagree for the other 9 hours. A test asserts the builder's value equals
   `col.sched.today` — the only trustworthy oracle. `meta` publishes `today`,
   `next_day_at` and `day_offset` so a consumer can see which day it received.
7. **The rank rule is written down.** The primary key collapses cards, so one row wins.
   The rule is `bot.py:2325-2326`'s, ported verbatim: prefer `template_kind =
   recognition`, then not blocked, then a non-archive deck, then the longer interval.
   `bot.py` records what a wrong rule costs: ranking on interval alone named the archive
   for about 31,000 words; ranking on live-and-not-archived alone named a production deck
   for 23. `card_count` records how many cards the row stands for, so `deck_stats.total`
   stays a card count.
8. **The cache write uses `BEGIN IMMEDIATE`, with a bounded retry.** A deferred
   transaction that reads and then writes raises `database is locked` immediately, and no
   busy timeout retries it. Verified: the upgrade failed in 0.00 s against a 5 s timeout.
   The rebuild replaces `meta`, `words`, `deck_stats`, `flagged`, `reviews_daily` and
   `progression_weekly`. **`deck_limits` is exempt.**
9. **`pragma wal_checkpoint(TRUNCATE)` runs after each rebuild, and the WAL size is
   logged.** A full-table replace writes the whole database into the WAL. Verified on a
   synthetic case: six rebuilds with one reader holding a snapshot grew the WAL to 24 MB,
   and a passive checkpoint could not reclaim it.
10. **`os.chmod(cache_path, 0o600)` after creation.** The umask is 0002 and the directory
    is 0775, so a new file is world-readable. `collection.anki2` is 0600, and the cache
    holds the same vocabulary, meanings and sentences.

### 6.2 The reader

```python
class CacheMissing(RuntimeError)     # no file
class CacheIncomplete(RuntimeError)  # the file exists, meta is empty
class CacheStale(RuntimeError)       # checked_at is too old and no pause is declared
class SchemaMismatch(RuntimeError)   # meta.schema_version != SCHEMA_VERSION
class NotInCache(RuntimeError)       # a deck, role or notetype that does not exist

def connect_ro(path=CACHE_PATH)      # asserts schema_version
def read_meta(conn) -> dict          # includes age_seconds and paused
def assert_fresh(conn, max_age_seconds=900)
def known_words(conn) -> dict
def due_words(conn, limit)           # role=recognition, not blocked; see §7 step 3
def leech_words(conn, limit)         # same scope; lapses >= 3 AND interval <= 7; see §11.1
def deck_words(conn, deck, template_kind, notetype) -> list
def word_status(conn, words) -> dict
def deck_stats(conn, decks=None, notetype=None) -> dict
def flagged(conn) -> dict
def reviews(conn, days) -> list
def progression(conn) -> list
```

Four reader rules:

* **Every lookup raises.** `deck_words(conn, "Nope", ...)` raises `NotInCache`. Where a
  published contract returns `[]` for a missing deck, the **handler** converts. The
  library stays strict; the contract keeps its shape.
* **Three states, not two.** A missing file, an empty file and a stale file are different
  errors. Version 1 had one, and "missing" and "empty" looking the same is constraint 1
  of the brief.
* **Freshness has two modes.** `assert_fresh` is for consumers that must be correct:
  dong's backfill and jiangchinese. The bot's own handlers use `read_meta` and publish
  `age_seconds`, because `/api/status` is documented to never fail (`bot.py:2294`) and a
  human-facing dictionary page reads it through `chinese-dict`.
* **No consumer writes SQL against `cache.db`.** The schema stays in this module.

### 6.3 `deck_limits` comes from the gate job

`/api/stats` publishes each deck's configured new-cards-per-day. That value sits in a
protobuf blob that only the anki library parses, and the builder has no library.

* `_sync_gated_templates()` writes `deck_limits`. It already opens the collection every
  five minutes.
* **It writes in its own `try/except`.** `bot.py:3311-3340` wraps the whole gate body in
  one handler that returns `Template gates failed: …`. A locked cache must not report the
  maturity gate as failed.
* **`build()` seeds `deck_limits` from the previous cache** when one exists, so a rebuild
  never empties it.
* **A missing limit is `NULL`, never 0.** The dashboard computes
  `PACE = (a.limits.HSK) || 0` and then divides by `max(1, rate)`, so a 0 turns into a
  projected completion date thousands of days out. `/api/stats` omits the key instead.
* The bot writes `deck_limits` once at startup, before it serves.

### 6.4 The maintenance window

`freq_data/anki_op.sh:37` stops the bot for the whole of a write operation. `checked_at`
then freezes, and after 900 s every strict consumer refuses at once.

`anki_op.sh` writes `meta.paused_until` before it stops the bot, and clears it after the
restart. `assert_fresh` honours it: a declared pause is not staleness. A pause that
expires becomes staleness again, so a crashed script cannot silence the check forever.

## 7. The steps

### Step 1 — the projection, the cache, the trigger

Nothing outside this repo changes.

1. `.gitignore` first: `cache.db`, `cache.db-wal`, `cache.db-shm`. The file is 27.6 MB.
2. Write `anki_cache.py` (§5, §6). About 450 lines.
3. `decks.py`: add the pure-Python resolver from rule 3, and make `deck_ids_for` use it.
4. `bot.py`, applied with `tools/patch.py`:
   - build synchronously in `main_async` **before** `site.start()`, so no request is ever
     served without a cache;
   - extract `register_jobs(job_queue)` so the wiring is testable;
   - add `refresh_cache` at 30 s, running the build through `asyncio.to_thread` — a 3.4 s
     build on the event loop stalls every HTTP request and the Telegram bot;
   - add `POST /api/refresh`;
   - add `_write_deck_limits(col)` to `_sync_gated_templates`, in its own `try/except`.
5. `tests/support.py`: redirect `anki_cache.CACHE_PATH` to the temp directory, assert it
   is not the real path, and extend the exit-9 guard to `cache.db`.
6. `freq_data/anki_op.sh`: write and clear `meta.paused_until`.
7. `freq_data/anki_daily.sh`: add a staleness check beside the gate verify, so a dead
   cache reaches the same non-zero exit as a failed backup.
8. Write `tests/test_cache.py` (§8).
9. Run `tests/run.sh`. The 54 existing tests and the new ones must pass.
10. Restart `anki-bot` by the procedure in §9. Watch for one hour and record the real
    rebuild rate.

**Done when:** `cache.db` exists at mode 0600, `checked_at` stays under 30 s old, a card
suspended by hand appears within 30 s, and `POST /api/refresh` returns the new
`generated_at`.

### Step 2 — dong-chinese — DONE 2026-08-20

The path is `server/scripts/backfill_known_words.py`. Committed as dong-chinese
`9f2deef`.

**Result, verified rather than assumed.** The table the new script writes is
byte-identical to the one the old script produced: 2,672 words, mature 2,094, learning
578, none lost, none gained, no status changed. With `sqlite3.connect` recorded, the
script opens only `cache.db` (`mode=ro`) and `dongchinese.db`. It never opens
`collection.anki2` and never imports `anki`. A cache 5,026 s old makes it exit 1 with the
reason on stderr, so the 6-hourly cron reports a failure instead of writing day-old data.

Two deliberate behaviour changes: a stale cache is fatal rather than a fallback, and the
local deck-name fallback is gone. An empty result is refused too, because the table is
replaced wholesale and blanking it would un-highlight the whole reader.

**Version 1's diagnosis of the word-count gap was wrong.** It blamed `sfld` versus field 0.
Two reviews measured that independently and refuted it: `sfld` and field 0 give identical
sets, because the 985 notes where they differ are all `ChineseSentences`, which the Han
filter already excludes. The real causes are three:

| Rule | Known words |
|---|---|
| the current script, today | 2,671 |
| the same script, no Han/length filter | 2,677 |
| version 1's prototype (recognition cards only) | 2,666 |
| the script's docstring, an older day | 2,647 |

* The docstring's 2,647 is a stale measurement. Do not use it as the baseline.
* The Han/length filter is worth 6 words. It drops keys such as `还好（了）` and
  `是。。。的`, which can never match a segmented word.
* Restricting to recognition cards loses 5 words: 族谱, 校友, 母校, 理想主义, 缓解痛苦.
  Each is known only through its `Reverse` card. The current script has no such filter.

**Decision:** `known_words()` means "any non-archive deck, any template, not blocked,
status is not `new`", plus the Han/length filter. That reproduces today's 2,671 exactly.

1. Add `test_known_words_matches_the_old_backfill`. Copy the old logic's 30 lines into
   the test file; do not import the sibling repo, because `anki_daily.sh` runs the suite
   at 12:10 UTC and must not depend on another project's venv.
2. Rewrite the script to `import anki_cache`, call `assert_fresh(conn, 900)`, and write
   the same table. It stops importing `decks` and stops opening `collection.anki2`.
3. Run it and diff the table against the saved one.

### Step 3 — jiangchinese: fix, then restore

**The service is stopped.** `pm2 stop jiangchinese-api` ran on 2026-08-20, by the user's
decision, because §11 records two live defects in what it serves. The public site
`jiang.comprehensiblemandarin.com` returns 502 while it is stopped. `pm2 start
jiangchinese-api` restores it in one command, with no code change.

This changes what step 3 is. It is no longer a migration of a running service. It is the
repair that lets the service come back. Two consequences:

* **Nothing is time-critical.** No user waits on this step, so it can take the time the
  other steps need.
* **The restore is the acceptance test.** The service comes back only when `get_due()` and
  `get_leeches()` are both correct, not when the code merely runs.
* **The 05:15 cron still copies 111 MB every day for a stopped service.** Leave it until
  the restore succeeds — it is the rollback path — then delete the cron line and
  `data/anki-snapshot.anki2` together.
* **Nobody may run `pm2 save` while the service is stopped.** The dump would record it as
  stopped, and it would not come back after a reboot. See §9.

**Two decisions, both answered on 2026-08-20. Nothing blocks step 3 now.**

*Decision A — what is a "leech"? **Answered 2026-08-20.*** A leech is a card with
`lapses >= 3` whose `interval` is still `<= 7` days. It is not Anki's `leech` tag. The
measurements and the reasoning are in §11.1. `leech_words()` implements exactly this, and
a test pins it.

*Decision B — which decks should jiangchinese read? **Answered 2026-08-20.*** Both
functions read **`role = recognition`** and exclude blocked cards. That role is exactly
`HSK`, `HSK7-9`, `non-HSK` and `Mined`, which is what the user named. Write the role,
never the four names — a rename must not reach this code.

Recorded consequence: the tutor will not drill the 80 due cards in `Reverse` or the 27 in
`Cloze`, even though `Reverse`'s template is `English-Speaking` ("say it out loud"). The
user chose the narrower scope with those numbers in view. Leeches are unaffected: all 69
leech words already sit in the recognition decks.

The scope was accidental before this decision, not chosen. The two functions disagreed:

| Function | Deck scope today | Card filters today |
|---|---|---|
| `get_due()` | every non-archive deck | `ord 0`, queues 1/2/3, not archived |
| `get_leeches()` | **none — it queries `notes` alone** | **none: no card join, no deck, no suspension, no order** |

So `get_leeches()` can return an archived, suspended note the user has never studied, and
it returns whichever 12 rows SQLite reaches first. `get_due()` is scoped and
`get_leeches()` is not, and nothing records why.

The cache makes the scope one line, because `words` carries `deck`, `role`,
`template_kind` and `blocked`.

**The archive needs no separate rule under this decision.** `role = recognition` already
excludes it. The `blocked` filter is a second, independent guard: the archive holds
213,434 cards and 0 of them are live, but that property is maintained by
`enforce_archive_suspended`, not guaranteed. Two filters mean one failure does not leak
parked words into the tutor.

**Two decisions are now answered, so step 3 is unblocked.**

The work:

1. Rewrite `backend/app/services/anki.py` to read `cache.db`. Keep `Word`, `get_leeches()`
   and `get_due()` unchanged in shape. `resolve_pinyin` stays.
2. **Keep the environment variable named `ANKI_SNAPSHOT_PATH` and change only its value.**
   The `.env` is not in git, so a `git revert` of a renamed variable leaves the reverted
   code reading an unset name and serving nothing — a silent rollback failure.
3. Update `backend/app/tests/test_anki.py`.
4. Compare `get_due(12)` and `get_leeches(12)` before and after, in one process. Expect
   `get_due` to change: the old day boundary is wrong (§11.2). Record the new list and
   check it by hand against Anki.
5. `pm2 start jiangchinese-api`. Confirm `https://jiang.comprehensiblemandarin.com`
   answers 200. Keep the 05:15 cron and the snapshot for seven more days.

### Step 4 — the bot's own endpoints

No consumer changes. `/api/status`, `/api/hsk-levels`, `/api/stats`,
`/api/deck/{name}/words` and `/api/flagged` read `cache.db`.

`POST /api/sync` must force a rebuild synchronously before it returns. Today it clears the
in-process caches (`bot.py:2656-2657`) so the next read is fresh, and
`chinese-dashboard-refresh` depends on that: it posts `/api/sync` and then immediately
runs `build_stats.py`. Without the forced rebuild the dashboard renders pre-sync numbers.

**Verification is an A/B test in one process, not a JSON baseline.** Version 1 planned to
diff against a baseline captured days earlier. The user studies daily, so every count
would differ and the diff would be unreadable. Instead the test runs the old function and
the new function against one collection copy and asserts equality. The captured baseline
stays only as a smoke check of the response shape.

Two known differences to pin, not to fix here:

* `/api/stats` counts `studied` as `type IN (1,2)` and `/api/hsk-levels` counts type 3 as
  `learning`. They disagree today over 20 cards. Keep both published numbers.
* `/api/deck/{name}/words` returns unstripped text. The `raw` columns preserve that.

### Step 5 — remove what the cache replaced

1. Delete `_status_cache`, `_stats_cache`, `_flagged_cache` and `_hsk_stats_cache`.
   Check every reference first: `handle_api_sync` uses two of them.
2. Decide the degraded-mode policy explicitly and test it. Today four endpoints serve a
   stale in-process snapshot rather than failing. After step 5 they serve `cache.db` with
   an `age_seconds` field.
3. Update `APIS.md`, `DECK_REFERENCE.md`, `README.md` and `tests/README.md` (which says
   46 tests; the suite runs 54).

## 8. The tests

In `tests/test_cache.py`. Each names a defect. **Check each by reverting its fix.**

| Test | The defect it pins |
|---|---|
| `test_rebuild_follows_a_write` | a cache that never notices a change |
| `test_no_rebuild_without_a_write` | `generated_at` holds, `checked_at` moves |
| `test_mod_is_read_in_the_same_snapshot` | uses `_after_mod_read` to commit a write mid-build; without the seam the correct and broken versions agree |
| `test_the_cache_job_is_registered` | a background job that nobody calls — this project has two recorded cases |
| `test_refresh_endpoint_is_routed` | the route exists on `create_web_app()` |
| `test_refresh_returns_the_new_generated_at` | acceptance checkbox 5 |
| `test_build_runs_off_the_event_loop` | a 3.4 s stall on every request |
| `test_schema_holds_no_anki_columns` | scans for `ord`, `queue`, `due`, `did`, `odid`, `mid`, `nid`, `cid`, `flags`, `usn`; `flagged.template_ord` is the one declared exception |
| `test_today_matches_ankis_own_day` | the 9-hour-a-day off-by-one |
| `test_overdue_days_normalises_the_three_units` | the 9-days-becomes-250 bug; the fixture must CONSTRUCT the filtered-deck and day-learn cases, because the collection has 0 of each |
| `test_buried_cards_are_blocked_not_live` | `queue` -2 and -3 |
| `test_unknown_queue_value_raises` | a silent default |
| `test_deck_lookup_never_uses_sql_name_matching` | the `unicase` failure |
| `test_simplified_is_canonical` | HTML in the key column |
| `test_key_collisions_use_the_written_rank` | the archive-named-for-31,000-words bug |
| `test_card_count_sums_to_meta_card_count` | a row that silently stands for many cards |
| `test_a_missing_deck_raises` | the build refuses rather than writing a short table |
| `test_a_renamed_deck_stops_the_cache` | a rename is loud within 30 s |
| `test_reader_raises_for_an_unknown_deck` | "missing" and "empty" must not look the same |
| `test_missing_empty_and_stale_are_three_errors` | `CacheMissing` / `CacheIncomplete` / `CacheStale` |
| `test_schema_version_mismatch_raises` | old code reading a new shape |
| `test_paused_cache_is_not_stale` | `anki_op.sh` must not take down five consumers |
| `test_a_rebuild_preserves_deck_limits` | rule 8's exemption |
| `test_missing_limit_is_null_not_zero` | the thousand-day projection |
| `test_stale_cache_raises` | a consumer serving day-old data |
| `test_archive_words_are_never_known` | the 313-word reader overcount |
| `test_blocked_words_are_never_known` | the same overcount, other half |
| `test_template_kind_comes_from_the_template_name` | the ord-based guess |
| `test_build_never_writes_to_the_collection` | asserts the MECHANISM: the URI contains `mode=ro` and not `immutable`, an `UPDATE` on the builder's connection raises, and `col.mod` is unchanged |
| `test_anki_cache_does_not_import_anki` | acceptance checkbox 2 |
| `test_cache_file_is_not_world_readable` | mode 0600 |
| `test_leech_rule_is_lapses_not_the_tag` | a card tagged `rewritten::leech` with 0 lapses must NOT appear; a card with 3 lapses and a 2-day interval must; a card with 9 lapses and a 60-day interval must not |
| `test_tutor_scope_is_the_recognition_role` | a due card in `Reverse` and a leech card in the archive must not reach `due_words` or `leech_words`; the scope resolves through the role, not through four deck names |
| `test_known_words_matches_the_old_backfill` | step 2's migration proof |

Two tests move out of this file:

* `test_sort_field_is_field_zero` goes to `tests/test_placement.py`. `sortf` is not a
  column — it lives in the notetype config blob — and its value is a fact about the
  collection, not about `anki_cache`. It can never fail on a code defect.
* The write guard in `tests/support.py` needs its own fix; see §11.

## 9. The restart procedure

`pm2 restart anki-bot` does not rewrite the pm2 dump, so it is safe on its own. Follow
this order:

1. `pm2 list`. Record `anki-bot`'s status and confirm nothing else is unexpectedly down.
2. `pm2 restart anki-bot`. Never `pm2 restart all` and never `pm2 restart chinese`.
3. `pm2 list` again. Confirm `anki-bot` is `online` and nothing else changed.
4. **Do not run `pm2 save`.** This plan adds no pm2 app and removes none, so the dump must
   not change.

Two windows make `pm2 save` actively destructive right now:

* `jiangchinese-api` is deliberately stopped (§7 step 3). A save records it as stopped,
  and it does not come back after a reboot.
* `anki_op.sh` holds `anki-bot` stopped for the length of a write operation. The same
  applies.

State recorded on 2026-08-20, before and after the stop: 35 apps, 33 online, with
`conscription-poll` and `conscription-backfill` already stopped. After the stop: 32
online. Nothing else changed.

## 10. Rollback

| Step | How | The trap |
|---|---|---|
| 1 | revert, restart `anki-bot`, delete `cache.db` | none; no consumer changed |
| 2 | revert the script and re-run it | none; it rebuilds from the collection |
| 3 | revert the service and restart | **the `.env` is not in git.** Step 3.2 keeps the variable name for this reason. Record the old value in the commit message. |
| 4 | revert, restart `anki-bot` | the HTTP contracts never changed |
| 5 | revert | `handle_api_sync` references two of the deleted caches |

## 11. Live defects this review found, outside the migration

Three problems exist today. None is caused by this plan.

Defects 1 and 2 are the reason `jiangchinese-api` is stopped. They no longer reach a user,
so they block only the restore in §7 step 3. Defect 3 is live and affects this repo's
test suite now.

1. **jiangchinese's leech list is not Anki leeches. Resolved 2026-08-20: the rule changes
   from a tag to a lapse count.**

   `anki.py:150` matches `tags like '%leech%'`. Four rules, measured on the collection:

   | Rule | Words |
   |---|---|
   | Anki's real `leech` tag | **1** |
   | the substring `%leech%` the code runs | 118, every one `rewritten::leech` |
   | the 2026-07-16 at-risk rule (`type=2`, ivl 1-2d, ≥3 Agains) | 53 |
   | **`lapses >= 3` and `interval <= 7` — the adopted rule** | **69** |

   The feature itself is worth keeping. `practice.py:44-49` builds the pack and
   `instructions.py:37` tells the tutor to "Prioritize (leech) words". The `hsk-leech-watch`
   memory of 2026-07-16 reached the same conclusion independently: it named 11 chronic
   leeches — 然而, 主持, 原则, 从而, 采取, 制定, 选择, 相似, 至今, 人士, 其实 — called them
   the heritage-speaker gap, and recommended sentence-context practice over grinding. A
   speaking tutor is that practice.

   The adopted rule returns 解雇, 然而, 制定, 主张, 达成, 意识, 综合, 此外, 实施, 从而,
   选择 at the top. Four of those are on the 07-16 chronic list.

   Three reasons for `lapses` over the alternatives:
   * The tag finds 1 word, so the mode is empty. The cause of the gap between 1 tagged
     note and 16 cards with 8 or more lapses is UNVERIFIED.
   * `cards.lapses` is durable. The 07-16 rule counts "Agains" from the revlog, and the
     revlog holds 21,192 rows for 258,959 cards. It is truncated, so it undercounts.
   * The interval bound matters. A card with 9 lapses now sitting at 60 days is relearned,
     not a leech.

   The 07-16 buckets stay valid for the HSK at-risk re-runs they were written for. They are
   a different measurement from this one; do not merge them.
2. **jiangchinese's due list uses the wrong day boundary.** `anki.py` computes
   `today = (now - crt) // 86400`. Measured today: that gives 247 where Anki gives 246.
   The two disagree for 9 hours of every day, so every card reads one day more overdue.
   Step 3 fixes it as a side effect.
3. **The test suite's write guard cannot detect a write to the real collection.**
   `tests/support.py:35` records `(st_size, st_mtime_ns)` and checks them at exit. The
   collection is in WAL mode. Verified: suspending 50 cards left size and mtime
   byte-identical while a reader saw the change. The guard would pass. It needs to compare
   `col.mod` and a row count, or to include the `-wal` and `-shm` files.

## 12. What step 1 actually produced, and three defects it found

Built 2026-08-20 on branch `read-cache`.

| File | Change |
|---|---|
| `anki_cache.py` | new, ~830 lines: the schema, the builder, the trigger, the reader, a CLI |
| `decks.py` | `+resolve_rows`, `+missing_from_rows`, `+unexpected_in_rows`, `+normalize_name` |
| `bot.py` | `refresh_cache` at 30 s, `POST /api/refresh`, `register_jobs`, `_write_deck_limits`, a synchronous build before serving, and `/api/sync` forcing a rebuild |
| `tests/support.py` | redirects `CACHE_PATH`; the write guard now compares `col.mod` |
| `tests/test_cache.py` | new, 43 tests |
| `freq_data/anki_op.sh` | declares a cache pause, rebuilds and unpauses after the op |
| `freq_data/anki_daily.sh` | `anki_cache.py status`, on the same non-zero-exit path as a failed backup |
| `.gitignore` | `cache.db` and its sidecars |

**Verification against the live system.** The cache reproduces `/api/stats` exactly: all
16 values across HSK, HSK7-9, non-HSK and Mined — total, studied, mature, new_left —
match the running endpoint, and `flagged` matches at 43. `known_words()` returns 2,671,
the same set the current dong script produces, with zero words invented or lost.

Three defects were found while building it. Each is the kind this plan exists to stop.

1. **`card_count` reset on every replacement, losing 540 of 258,959 cards.** When a
   better-ranked card replaced a row, the new row started its count at 0 and discarded
   what the previous winner had accumulated. `test_card_count_sums_to_the_cards_read`
   caught it; nothing else would have, because every individual row looked right.
2. **Redirecting `anki_cache.CACHE_PATH` in the fixture redirected nothing.** Python binds
   a default argument when the `def` runs, so `cache_path=CACHE_PATH` captured the module
   value at import. A handler test therefore wrote the LIVE `cache.db`. The new guard in
   `tests/support.py` caught it on its first run. Every path is now resolved at call time.
3. **`sortf` is not a column and `sfld` is not raw.** Anki keeps `sfld` as its own stripped
   copy of the sort field and maintains it, so the planned `sortf == 0` test was
   impossible as written and the "unstripped" assumption about `/api/deck/{name}/words`
   was half wrong: that endpoint publishes Anki's stripped `sfld` for the word and RAW
   fields for pinyin and meaning. The schema now mirrors both.

**Two measurements that changed the design during implementation.**

* `without rowid` on a three-column text key made every secondary index store the whole
  key again: 48.6 MB. Plain ROWID tables with two indexes give 31.2 MB.
* Sorting rows by primary key before insert gave no gain (6.4 s against 5.9 s), so it was
  removed rather than kept as decoration.

**Still to do in step 1:** restart `anki-bot` by the §9 procedure, then watch for an hour
and record the real rebuild rate. That number decides whether risk 1 in §8 is real.
