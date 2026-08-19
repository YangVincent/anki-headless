# Brief: a shared read cache for the Anki collection

**Status:** not started. This is a specification, not a description of what exists.
**Written:** 2026-08-19, after a session that found and fixed ~40 defects, about half of
them introduced by the fixes themselves. The constraints below are the lessons from that.

---

## The task in one sentence

Five services read one Anki collection three different ways; replace that with **one small
derived cache that the bot owns and everyone else reads**, so no consumer ever opens the
collection or knows Anki's schema.

---

## What exists today

Measured 2026-08-19, not remembered.

```
  freq_data/ + tools/     operations: gate runner, backups, lint, source patching
  cli.py            734   a direct human CLI
  bot.py          3,457   the maturity gate, 24 tools, Telegram, HTTP, prompts
  decks.py          320   THE deck list, by role; resolves a role to deck IDs
  anki 25.09.2            the only safe writer
  collection.anki2        258,959 cards, 132,625 notes, 111 MB
```

Eight decks, and that is the whole collection: `HSK`, `HSK7-9`, `non-HSK`, `Mined`,
`Reverse`, `Cloze`, `Archive`, `Default`. `decks.py` declares each deck's ROLE
(recognition / production / cloze / archive / reserved) and resolves a role to deck IDs.
Callers ask for a role and never for a name.

### The five consumers

| Service | Reaches Anki by | Direction |
|---|---|---|
| **anki-bot** (pm2, `:8103`) | the Anki library, directly | **read + write** |
| jiangchinese-api (pm2) | a snapshot copy taken at 05:15 | read |
| dong-chinese backfill (cron, 6h) | the live file, `mode=ro` | read |
| chinese-dashboard (cron, 6h) | HTTP only | read |
| comprehensiblemandarin (pm2) | HTTP only | read |

### Three caches already exist, each worse than the one proposed

| Cache | Staleness | Shape | Problem |
|---|---|---|---|
| bot's in-memory `_status_cache`, `_stats_cache`, `_flagged_cache` | 60s TTL | derived | per-process, lost on restart, invisible to others |
| jiangchinese's snapshot | up to **24h** | a full 111 MB copy in Anki's schema | large, stale, and schema-coupled |
| dong-chinese's `known_words` table | 6h | derived | already exactly the right idea, for one consumer |

---

## Why

**Consumers need about 2% of the collection, and pay a lock and a schema dependency for it.**

```
the whole collection            258,959 cards, 111 MB
everything the consumers need    ~55,000 rows
producing each derived view      ~1.2s
```

Four specific gains:

1. **One reader path instead of three.**
2. **The single-open-handle constraint disappears for readers.** Anki allows exactly one
   open handle. Readers contend with the bot today; SQLite in WAL mode gives one writer and
   unlimited readers, which is the shape this system actually wants.
3. **Consumers stop knowing Anki's schema.** Every consumer breakage in the 2026-08-19
   session came from schema knowledge leaking outward: deck names, `ord`, `queue`, and the
   three meanings of `due`. A cache with its own columns ends that class.
4. **Staleness becomes a number instead of an accident.** jiangchinese cannot currently
   tell whether its snapshot is 20 minutes or 20 hours old.

---

## The design

```
collection.anki2 ──[the bot, sole writer]──▶ cache.db ──▶ every consumer (read-only)
                                                │
                          meta(generated_at, source_mod, schema_version)
                          words(simplified, deck, role, status, interval, suspended)
                          deck_stats(deck, role, total, studied, mature, new_left)
                          due(simplified, overdue_days, kind)
```

**Rules:**

- **One writer.** Only the bot writes `cache.db`. Consumers open it read-only.
- **Rebuild on `col.mod` changing, not on a call site.** Anki bumps `col.mod` on every
  write. Triggering on that removes the whole class of "someone forgot to invalidate".
  This must be a test, not a comment.
- **`meta` travels with the data.** `generated_at`, the `source_mod` it was built from, and
  a `schema_version`. A consumer asserts on freshness and refuses stale data loudly.
- **`POST /api/refresh`** forces a rebuild and returns the new `generated_at`. This is the
  "ask Anki to push an update" half of the idea; the rest is automatic.
- **The cache holds derived facts, never Anki's schema.** No `ord`, no `queue`, no raw
  `due`, no deck ids. `status` is a word: `new` / `learning` / `mature` / `suspended`.

---

## Constraints, each learned by breaking something

Do not treat these as style preferences.

1. **Anki reports "missing" and "nothing" identically.** `col.decks.id_for_name()` returns
   `None`; `find_cards("deck:X")` returns 0 for a deck that does not exist, which is
   indistinguishable from "no cards match". Neither raises. Two background jobs and a daily
   cron ran for months achieving nothing because of this. Every lookup must raise.
2. **`cards.due` holds three different units** — a queue POSITION on a new card, a DAY
   NUMBER on review and day-learn, a UNIX TIMESTAMP on intraday learning — and a card on
   loan to a filtered deck keeps its real value in `odue`. Mixing them turned a card due in
   9 days into one 250 days overdue. The cache must expose `overdue_days`, already
   normalised, so no consumer touches `due` again.
3. **Anki allows ONE open collection handle.** Any script that writes must stop the bot
   first — that is what `freq_data/anki_op.sh` is for. The cache builder runs inside the
   bot, which already holds the handle.
4. **Deck names are user-editable labels.** A rename in the Anki desktop client is a schema
   change with no migration and no error. Four consumers hardcoded a deck name and three
   broke silently on 2026-08-19. The cache stores `role` beside `deck` so a consumer can
   key on the role and never on the name.
5. **Suspension has exactly one owner: the maturity gate** (`bot._apply_template_gate`).
   The cache reports state; it must never write to the collection.
6. **A card with `reps > 0` is never suspended by automation.** Removing something the user
   has studied is worse than an inconsistent deck.

---

## Order of work

One consumer at a time. Do not migrate them together.

1. **Build the projection and `cache.db`.** Tests first: the rebuild trigger, the schema,
   and freshness. Nothing else changes yet.
2. **Move dong-chinese.** It already reads a derived table (`known_words`), so this is the
   smallest change and the clearest proof the shape is right.
3. **Move jiangchinese.** This retires the 24-hour snapshot and the 05:15 cron.
4. **Move chinese-dashboard and comprehensiblemandarin.** Their HTTP endpoints become cache
   reads and get faster.

Rough size: ~150 lines for the projection, a few lines per consumer.

---

## Acceptance

- [ ] `cache.db` rebuilds automatically when `col.mod` changes, proven by a test that
      mutates the collection and asserts the cache followed.
- [ ] A consumer reading `cache.db` never opens `collection.anki2` and never imports anki.
- [ ] Every table carries no Anki schema: no `ord`, `queue`, raw `due`, or deck id.
- [ ] `meta.generated_at` is present, and at least one consumer refuses stale data.
- [ ] `POST /api/refresh` returns the new `generated_at`.
- [ ] The existing 54 tests still pass (`tests/run.sh`).
- [ ] New tests cover the rebuild trigger and staleness. A test that passes on code with
      the defect is a broken test — check by reverting the fix.

---

## Do not

- **Do not cache the collection.** That is jiangchinese's snapshot today: full size, Anki's
  schema, and stale. All the value is in projecting to a small, stable shape.
- **Do not let the cache write to the collection.** It is a read model.
- **Do not migrate all consumers at once.** One at a time, each verified.
- **Do not claim it is done without executing it.** Every defect in this project was found
  by running code against a copy and constructing the state it forbids. Three separate
  claims of "this is thorough" were each wrong within hours.

---

## Working notes for whoever picks this up

- **Tests:** `tests/run.sh` — 54 tests, ~25s. The fixture copies the collection, redirects
  `bot.COLLECTION_PATH`, gives each test a fresh copy, and aborts with exit 9 if the real
  file is touched. Read `tests/README.md` first.
- **Editing source:** use `tools/patch.py`. It validates every anchor before writing
  anything, reports all failures together, compiles the result, and scans for undefined
  names. The ad-hoc alternative silently discarded edits three times in one session.
- **Collection scripts:** use `tools/collection_op.py`. Dry-run by default, checks that set
  the exit code, and an error if a writing run records no changelog entry.
- **Mutating the collection:** always via `bash freq_data/anki_op.sh <label> <script> --apply`.
  It stops the bot, waits for the lock, takes a WAL-safe backup, runs, and restarts.
- **The deck list:** `decks.py`. Never write a deck name anywhere else.
- **Related docs:** `DECK_REFERENCE.md` (decks, the gate, presets),
  `~/chinese-projects/APIS.md` (cross-project contracts).
