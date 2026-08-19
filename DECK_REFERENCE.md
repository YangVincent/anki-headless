# Anki Deck Reference

## Overview

Chinese vocabulary study system built around HSK 3.0 levels 1-9, with integrated character-level learning (via separate "Hanly" app) and automated mnemonic generation. Runs on a headless Anki server with a Claude-powered Telegram bot (`anki-bot`) for daily card management.

---

## Key Numbers

*Verified against the collection 2026-08-04. These drift — re-measure before relying on them.*

| Metric | Count |
|---|---|
| Total cards | 258,959 |
| Active (non-suspended) | 22,173 |
| Suspended (archived) | 236,786 |
| Learning | 86 |
| Review | 2,791 |
| New | 256,052 |

---

## The deck list — eight decks, and that is all

*Consolidated 2026-08-19, down from 26. Counts verified the same day; they drift.*

| Deck | Cards | Unsuspended | Preset | What it is |
|---|---|---|---|---|
| **HSK** | 4,859 | 4,673 | `HSK (25/day)` — 25 | HSK 3.0 levels 1-6, recognition. Single-character words excluded (studied in Hanly). Level asc, then frequency desc. |
| **HSK7-9** | 5,420 | 5,393 | `HSK` — 10 | HSK 7-9 recognition, tagged `HSK::HSK7-9`. |
| **non-HSK** | 9,950 | 8,660 | `HSK` — 10 | Frequency-ordered vocabulary outside HSK 3.0. |
| **Mined** | 446 | 317 | `HSK` — 10 | Words added from anywhere, not in HSK. New arrivals go to the front. |
| **Reverse** | 7,402 | 2,040 | `HSK` — 10, **deck override 25** | Production (`English-Speaking`) cards, maturity-gated. |
| **Cloze** | 17,448 | 1,929 | `HSK` — 10 | Cloze (`Cloze-Recall`) cards, maturity-gated. Renamed from `Vocab Cloze`. |
| **Archive** | 213,434 | **0** | `Default` — 10 | Everything parked. Always suspended. |
| `Default` | 0 | 0 | `HSK` — 10 | Anki reserves deck id 1 and will not let it be deleted. |

**`decks.py` is the single definition — the only file in any repo that contains a deck-name
literal.** It declares each deck's ROLE, not just its name, and everything else derives:

```python
RECOGNITION_DECKS   # ('HSK', 'HSK7-9', 'non-HSK', 'Mined')
PRODUCTION_DECK     # 'Reverse'
CLOZE_DECK          # 'Cloze'
ARCHIVE_NAMES       # ('Archive', 'Hidden')  -- current + every legacy name
NEW_WORDS_DECK      # 'Mined'
gate_sources(CLOZE) # ('HSK', 'HSK7-9', 'non-HSK', 'Mined')
```

Callers ask for a role, never a name: "where do new words go", not "Mined". Rename a deck
in `decks.py` and every use follows — the six duplicated tuples that used to spell the
names out are gone.

The `gates` field per deck is what makes the two source lists differ, visibly: `Mined`
counts for `cloze` and not for `production`. That is a deliberate choice, and its
consequence (249 production cards for mined words can never be released) is now readable
in one line instead of implied by two tuples that happen not to match.

`check_target_deck()` refuses any write to a name outside `ALL_NAMES`, and startup logs
`UNEXPECTED DECKS` if the collection grows one. `GET /api/decks` serves the same data for
anything that cannot import the module.

Consumers, and how each gets the list:

| Consumer | How |
|---|---|
| `bot.py`, `freq_data/*.py` | `import decks` |
| `dong-chinese` backfill, `jiangchinese` anki.py | `import decks` via the anki-headless path they already hardcode |
| `chinese-dashboard/build_stats.py` | `GET /api/decks` — it is HTTP-only by design |

Each of the three sibling files keeps ONE literal fallback, used only if that lookup fails.
Those four lines are the only deck names outside `decks.py` in any live file.

The bot's system prompt no longer contains a hand-written deck table. `_deck_table()` builds
it from `decks.py` at import, so a rename cannot leave the model naming decks that are gone.
The card counts that used to sit in it are removed — `list_decks` returns live ones.

**Verified by renaming.** Changing `Mined` to `Foraged` and `Reverse` to `SpeakIt` in
`decks.py` alone, with no other edit, changed `RECOGNITION_DECKS`, `NEW_WORDS_DECK`,
`PRODUCTION_DECK`, `bot.DEFAULT_DECK`, `bot.REVERSE_DECK`, both gate source lists,
`ALLOWED_DECKS`, the prompt table and the `/api/decks` payload.

`freq_data/lint_deck_names.py` reports scripts that name a deck which no longer exists. It
finds **43 of 61** one-shot scripts, mostly naming `Vocab` (37) — a deck retired long before
this consolidation. None is in the live path; each is a silent no-op if re-run.

**`Archive` replaced the `Hidden::` subtree.** It absorbed `Hidden::Archive::{Words,
Sentences,Characters}`, `Hidden::Personal{,-reverse}`, `Hidden::hanly-grammar{,-reverse}`,
`Hidden::hanly-proper-nouns`, `Hidden::TingChinese - Saved Words`, `Hidden::cli{,-reverse}`
and `Hidden::Characters`. The `Mined::三体` and `Mined::十日终焉` subdecks folded into `Mined`.
Card and note totals were identical before and after: 258,959 and 132,625.

`bot.ARCHIVE_DECK_NAMES` still lists `Hidden` beside `Archive`, so the archive test stays
correct against a pre-migration backup. Two downstream consumers carry the same pair:
`dong-chinese/server/scripts/backfill_known_words.py` and
`jiangchinese/backend/app/services/anki.py`.

**Nothing is deleted from `Archive`.** 66,382 notes exist ONLY there — 30,556 vocabulary
words, 7,506 characters, all 28,320 sentences. They are the user's staged backlog and are
promoted with `tag_notes` + `mined`, never re-created.

---

## The archive shares the `Simplified` field name — a word search returns "duplicates"

*Verified against the collection 2026-08-19.*

**A `Simplified:<word>` search returns the live card plus up to four archived notes for the
same word. They are not duplicates.** This has already produced one wrong recommendation from
`anki-bot` ("safe to delete", 2026-08-19).

Four note types make up one complete imported HSK 3.0 deck, **11,042 notes each**:

- `Basic - new hsk 3.0 xiehanzi v3 - audio`
- `Basic - new hsk 3.0 xiehanzi v3 - pinyin-zhuyin`
- `Basic - new hsk 3.0 xiehanzi v3 - write`
- `Basic - new hsk 3.0 xiehanzi v3 - meaning`

Every card of all four sits in a `Hidden::` deck. Their field 0 is named **`Simplified`** —
the same name the live `ChineseVocabulary` note type uses. Anki's `Simplified:说服` therefore
matches five notes: one live HSK card and four archived ones.

Two more facts that make this read wrongly:

1. **A live note spans decks.** The `ChineseVocabulary` note for 说服 has ord 0 in `HSK`,
   ord 1 in `Hidden::Archive::Words` and ord 2 in `Vocab Cloze`. Any tool that reports one
   deck per note reports whichever card comes first and hides the rest.
2. **`Hidden::` is not fully suspended.** It holds 219,218 cards, of which 1,058 are
   unsuspended. `Hidden::Archive::*` is 214,006 cards with 213,981 suspended; the live
   remainder sits in `Hidden::hanly-reverse`, `Hidden::Personal` and similar, on purpose.
   Do not assume "Hidden" means "suspended", and do not assume "suspended" means "junk".

`bot.py` now reports `archived: true` for any note whose every card is under `Hidden::`
(`_archived_note_ids`). `search_notes` splits its hits into `live_note_ids` and
`archived_note_ids`, `get_notes_detail` returns the full `decks` list, and `delete_notes`
refuses archived notes unless it is called with `include_archived: true`.

---

## Cloze cards are CUSTOM, not Anki-native — don't conclude they're missing

There are **no Anki cloze note types in this collection** (`model type` is 0 everywhere, no
`{{cloze:}}` in any template, zero notes containing `{{c1::}}`). Cloze is implemented instead
as a third `ChineseVocabulary` template, **`Cloze-Recall`**, gated on a field:

```
{{#SentenceSimplifiedCloze}}
  Fill the blank — the word meaning "{{Meaning}}". Say it.
  {{SentenceSimplifiedCloze}}
{{/SentenceSimplifiedCloze}}
```

The blank is literal `[ ]` in `SentenceSimplifiedCloze` (e.g. `他[ ]很守时。`). **17,441 of
49,653** vocabulary notes have one, and their Cloze-Recall cards live in the `Vocab Cloze`
deck — which is why that deck contains only `ChineseVocabulary` notes and appears, wrongly, to
have no cloze in it.

**Check by rendering a card, not by inspecting note-type names or model flags** — every
name/flag-based check says this collection has no cloze, and every one of them is wrong.

Templates: `Hanzi-English` (ord 0) · `English-Speaking` (ord 1, "Express this in Mandarin. Say
it out loud") · `Cloze-Recall` (ord 2). Ords 1 and 2 are both **production-direction** drills —
cue is the meaning, you generate the Chinese aloud — as opposed to ord 0's recognition.

**External consumer (2026-08-04):** comprehensiblemandarin's Write module reads `Vocab Cloze`
through anki-bot's `GET /api/deck/{name}/words?ord=2` to source its vocabulary writing prompts —
it wants the production direction, so it must pass `ord=2` explicitly (the param defaults to 0).
Because the deck holds *only* ord-2 cards, an ord-0 query against it returns `[]`, which is
indistinguishable from a missing deck — that ambiguity is exactly the bug the param was added to
fix. Contract in `~/chinese-projects/APIS.md`; only the 25 studied cards are eligible, per the
status>=1 filter, which is why that consumer's word pool is small.

### The connectives set (2026-07-31) — built as `Vocab Cloze::Connectives`, since dissolved

> **Status 2026-08-04: the subdeck no longer exists.** No deck matching `Connectives` is in the
> collection. Its cards now sit directly in the parent `Vocab Cloze`, and **the isolation that
> was the whole point of the subdeck is gone** — `Vocab Cloze` runs on the shared `HSK` preset
> (10/day), not `Default`. The connectives no longer have their own daily allocation; they
> queue behind ~963 other unsuspended new cloze cards competing for the same 10/day.
>
> The visible consequence: of `Vocab Cloze`'s 16,749 cards, only **25 have ever been studied**
> (3 learning, 22 review) and 15,760 are suspended. Of the connectives named below, only
> 然而 / 从而 / 尽管 have entered learning; 此外 反之 换句话说 由此可见 相对而言 综上所述
> 未必 毕竟 势必 一般而言 总的来说 诚然 具体而言 总体而言 在某种程度上 are all still new
> and unsuspended — queued, but behind everything else.
>
> The exclusion of the already-mature ones was implemented by **suspension**, and only partly:
> 因此 / 于是 / 否则 are suspended as intended, but 不过 / 而且 / 另外 are unsuspended and new,
> so they are back in the queue despite being known. If you rebuild this set, that inconsistency
> is the thing to fix first.
>
> Whether the subdeck was merged deliberately or lost in a later reorganization is not recorded.
> The paragraphs below describe the **build** as performed on 2026-07-31 and remain accurate as
> history — including the note-level repairs, which persist in the collection.

Cloze-Recall cards for written-register discourse glue: logical connectives → formal frames →
stance adverbs (然而 从而 尽管 此外 反之 换句话说 由此可见 相对而言 综上所述 未必 毕竟 势必 …).
Built as its own subdeck on the `Default` preset (10/day), isolated from the shared `HSK` preset
— see the status note above for why that description no longer holds.

Selection rule: a connective that is **not yet mature** *and* **has a cloze sentence**. Twelve
already-mature ones (因此 于是 不过 而且 另外 否则 …) are deliberately excluded — they're known.

Seven had no usable cloze sentence and were built on 2026-07-31: four existing notes
(综上所述 一般而言 总的来说 诚然) had their sentence fields filled — they were sitting in
`Hidden::Archive::Words`, so the *conditional* Cloze-Recall template had never generated a card
— and three (具体而言 总体而言 在某种程度上) had no note at all and were created in `non-HSK`
following 相对而言's shape. Sentences came from the dong-chinese reading corpus where it had
one, otherwise written. **Their `Meaning` fields were rewritten**: the prompt is "the word
meaning {{Meaning}}", and 综上所述 read "to summarize" while 总的来说 read "Summing up" —
identical glosses make the card unanswerable, so near-synonyms need discriminating meanings.

Note: 综上所述 / 一般而言 / 总的来说 / 诚然 still have their recognition (ord-0) cards suspended
in the archive — they have a production card but no recognition card.

#### The leech detour, and what it teaches

This deck began as `Vocab Cloze::Leeches` (19 leech-tagged words) before being rebuilt on a
connective criterion. Two lessons worth keeping:

- **`leech` is a note-level tag**, so `tag:leech` returned 57 cards for only 19 words (each
  word's three cards); only the ord-0 vocab cards had actually lapsed.
- **The tag is sticky — Anki never removes it.** All 19 described history, not current state:
  17 were already recovering with intervals up to 17 days. Selecting on `tag:leech` selects on
  *what was once hard*, which is close to the opposite of *what still needs work*. The tags
  were cleared on 2026-07-31 so `tag:leech` means something again.

Leeches and connectives barely overlap — 4 words of 103. Leeches are recognition failures;
missing connectives are mostly words never studied at all, and you cannot leech a word you have
never seen.

#### Don't use `shift_existing=True` for a small repositioning

`reposition_new_cards(..., shift_existing=True)` on 19 cards bumped the queue position of
**255,749** unrelated new cards to make room, dirtying them all for sync. Relative order was
preserved and no review card was rescheduled, so it was harmless — but the blast radius was
four orders of magnitude larger than the edit. Use `shift_existing=False` unless you genuinely
mean to renumber the whole collection.

---

## Options Presets (daily limits) — READ BEFORE CHANGING ANY LIMIT

⚠️ **Deck options in Anki belong to a shared *preset*, not to a deck.** Editing "new cards/day"
from a deck's options screen edits every deck that shares that preset. As of 2026-07-27 this
collection had **all 24 decks on a single preset** named `HSK`, so changing the HSK deck's
limit would silently have changed HSK7-9, non-HSK, Vocab Cloze, Mined and every archive deck
at the same time.

Current assignment:

| Preset | new/day | rev/day | Used by |
|---|---|---|---|
| `HSK (25/day)` | 25 | 1000 | **HSK deck only** (split out 2026-07-30) |
| `HSK` | 10 | 1000 | the other 23 decks |

**Rule: to change one deck's limit, give it its own preset — never edit a shared one.** Clone
the existing preset so learning steps, new-card order and the review limit carry over, then
change only `new.perDay`:

```python
from anki.collection import Collection
col = Collection("/home/vincent/anki-headless/collection.anki2")
shared = col.decks.config_dict_for_deck_id(col.decks.id_for_name("HSK"))
new_id = col.decks.add_config_returning_id("HSK (25/day)")
c = col.decks.get_config(new_id)
keep = (c["id"], c["name"])
c.update({k: v for k, v in shared.items() if k not in ("id", "name", "mod", "usn")})
c["id"], c["name"] = keep
c["new"]["perDay"] = 25
col.decks.update_config(c)
d = col.decks.by_name("HSK"); d["conf"] = new_id; col.decks.save(d)
col.close()
```

Audit which deck is on which preset (do this *before* every limit change):

```python
for d in sorted(col.decks.all_names_and_ids(), key=lambda x: x.name):
    if col.decks.get(d.id).get("dyn"): continue
    c = col.decks.config_dict_for_deck_id(d.id)
    print(f"{d.name:38} {c['name']:16} {c['new']['perDay']:3d}")
```

### Two things that override the preset

1. **`newLimitToday` / `reviewLimitToday`** — per-deck "Today only" limits, stored on the deck,
   not the preset. Shaped `{'limit': 100, 'today': 182}` where `today` is a day index; they
   apply **only** when `today == col.sched.today` and are inert otherwise. HSK and non-HSK
   carried stale day-182 copies (limit 100) for ~44 days; cleared 2026-07-30. If a limit
   appears to be ignored, check these first.
2. **Custom Study / filtered decks** — bypass the preset entirely. Actual intake has ranged
   **4–124 new cards/day against a 10/day preset limit** (124 on 2026-07-13), so the preset
   limit describes normal study only. There is a `Custom Study Session` filtered deck in the
   collection. Don't conclude a limit is broken from intake numbers alone.

There are also **9** orphaned presets (`Languages`, `Chinese Characters`, `Chinese Vocabulary`,
`Chinese Sentences`, `Vocab Cloze`, `Mined`, `HSK7-9`, `Hanly Gap`, and one of the two
`Default`s — id 1765895986398). The other `Default`, id 1, **is** in use by `Mined::三体`.
Leftovers
from the 2026-07-27 collapse onto one preset. Harmless, but don't assume a preset named after
a deck is the one that deck uses. Verify with the audit above.

### Verifying a limit change actually took

`sync_collection` returns **"Synced (no changes needed)" even when it did push** — see Sync
below. Don't trust the message; check the USN:

```python
d = col.decks.by_name("HSK")
print(d["usn"])            # -1 = still pending upload; a positive number = server-assigned, pushed
print(col.db.scalar("select ls from col") >= col.db.scalar("select mod from col"))  # True = in sync
```

Also confirm the scheduler agrees, remembering it subtracts cards already done today:

```python
col.sched.deck_due_tree()  # HSK node's new_count == perDay minus today's intake
```

Back up before writing: `cp collection.anki2 /home/vincent/backups/anki/collection.anki2.$(date +%Y%m%d-%H%M%S).bak`

`anki-bot` opens and closes the collection per operation (it does **not** hold it open), so an
external write is safe; it will see the change on its next operation.

---

## Character Learning (Hanly Integration)

- "Hanly" is a standalone mobile app for character (handwriting) learning
- Progress exported as JSON: `hanly_july_8_2026.json`
- 793 characters at 100% mastery, 1,498 in progress
- Many due review/learning cards contain characters the user hasn't started in Hanly → those cards get reset to new (reappear at end of new queue)
- Hanly Gap characters (characters not yet in the HSK deck) merged into HSK deck before their anchor word
- Character notes use `ChineseCharacters` note type (Simplified, Pinyin, Meaning, Components, Notes)

## Mnemonics

- Character-breakdown format applied to 1,235 HSK 3-4 cards
- Pattern: `Mnemo: 民(people) + 主(master) = democracy`
- Stored in the `Notes` field of `ChineseVocabulary` notes
- Cards tagged `mnemonic`
- Uses character meanings from `ChineseCharacters` notes
- Custom mnemonics added for connector words: 从而, 此外, 而且, 反而, 进而

---

## HSK 3.0 Coverage

*Counted from `freq_data/hsk30_official.json`, which is the source the code reads. Every
number in this table was previously wrong; three different totals were in circulation
(10,440 here, 10,978 in a bot.py comment, 10,440 in build_stats.py) and none matched the file.*

| Level | Words in HSK 3.0 | Status |
|---|---|---|
| 1 | 506 | All in HSK deck |
| 2 | 750 | All in HSK deck |
| 3 | 950 | All in HSK deck |
| 4 | 973 | All in HSK deck |
| 5 | 1,058 | All in HSK deck |
| 6 | 1,120 | All in HSK deck |
| 7-9 | 5,603 | In HSK7-9 deck |
| **Total 1-9** | **10,960** | Covered across both HSK decks |

---

## Data Files

| File | Contents |
|---|---|
| `freq_data/hsk3_vocab.json` | 73,082 entries (HSK 3.0 + extended) |
| `freq_data/calib50.json` / `calib75.json` | Difficulty calibration data |
| `hanly_july_8_2026.json` | Hanly app progress export |

---

## Key Scripts (quality/)

| Script | Purpose |
|---|---|
| `merge_characters_into_hsk.py` | Merge Hanly Gap characters into HSK deck before anchor word |
| `create_hsk79_deck.py` | Create HSK7-9 deck with orphan chars + 7-9 word cards |
| `add_missing_char_cards.py` | Create ChineseCharacters notes for missing HSK chars |
| `add_mnemonics.py` | Batch-add character-breakdown mnemonics to HSK3/4 cards |
| `reorganize_hsk_decks.py` | Split HSK vocab to HSK/non-HSK decks, tag by level |
| `add_missing_hsk_words.py` | Add HSK 3.0 1-6 words missing from deck |
| `resort_hsk_by_level.py` | Sort HSK deck new cards by level then frequency |
| `resort_non_hsk.py` | Sort non-HSK deck by frequency |
| `backfill_hsk_freq.py` | Add frequency badges to HSK notes |
| `check_hsk_coverage.py` | Audit HSK deck coverage against 3.0 standard |

---

## Telegram Bot (anki-bot)

- Runs under pm2 as `anki-bot`
- Uses Claude via single-loop tool-calling architecture with 24 tools
- 8 read-only (search, get stats, list decks, etc.)
- 2 card creation (`add_chinese_vocab`, `add_general_card`)
- 5 modification (suspend, unsuspend, tag, delete, move)
- 1 sync tool
- Commands: `/status`, `/decks`, `/log`, `/clear`, `/help`
- Default deck: `DEFAULT_DECK` in `.bot_config.json` names
  `Knowledge::Languages::Chinese::Vocabulary`, **which does not exist**. `add_chinese_vocab`
  falls back to `Mined` (and `promote_to_vocab` moves the card there anyway). Before
  2026-08-19 the fallback was absent, so Anki filed 199 cards into `Default`.

---

## Sync

- Full sync upload can cause issues: sometimes reports "Already in sync, no changes needed" despite local changes
- `anki-bot` periodic sync runs in background and generally resolves this
- Before `pm2 save`: verify all 12+ PM2 services are running

---

## Notes

- Single-character words excluded from HSK deck (studied separately in Hanly)
- Reverse/production cards are suspended by default (deferred strategy)
- ~2,092 cards flagged for quality issues (audio-sense mismatch, etc.)
- 4,677 cards identified as needing quality improvement (ongoing campaign)
