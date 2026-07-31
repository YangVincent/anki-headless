# Anki Deck Reference

## Overview

Chinese vocabulary study system built around HSK 3.0 levels 1-9, with integrated character-level learning (via separate "Hanly" app) and automated mnemonic generation. Runs on a headless Anki server with a Claude-powered Telegram bot (`anki-bot`) for daily card management.

---

## Key Numbers

| Metric | Count |
|---|---|
| Total cards | 259,035 |
| Active (non-suspended) | ~20,000 |
| Suspended (archived) | 238,551 |
| Learning | 110 |
| Review | 1,554 (214 due) |
| New | 257,397 |

---

## Active Study Decks

Each deck uses a **Word** note type (Simplified, Pinyin, Meaning, POS, SentenceSimplified, SentencePinyin, SentenceMeaning, Frequency, Notes, Audio) and a **Cloze** note type for sentence practice.

| Deck | Cards | Description |
|---|---|---|
| **HSK** | 5,705 | HSK 3.0 levels 1-6. Single-character words excluded (studied in Hanly). Sorted by level then frequency. |
| **HSK7-9** | 4,790 | HSK 7-9 word cards + 47 orphan character cards. All tagged `HSK::HSK7-9`. |
| **non-HSK** | 10,964 | Frequency-ordered vocab not in HSK 3.0 1-9. Sorted by frequency (high to low). |
| **Vocab Cloze** | 16,656 | Cloze-deleted sentence cards from all above sources. |

## Archived Decks (Hidden, all suspended)

| Deck | Cards | Contents |
|---|---|---|
| `Hidden::Archive::Words` | 96,733 | Legacy word backup pool |
| `Hidden::Archive::Sentences` | 84,657 | Legacy sentence pool |
| `Hidden::Archive::Characters` | 34,070 | Legacy character pool (some moved to HSK deck) |
| `Hidden::hanly-reverse` | 4,460 | Production/reverse cards deferred for later |
| `Hidden::hanly-proper-nouns` | 346 | |
| `Hidden::hanly-grammar` | 266 | |
| `Hidden::Personal` + `:reverse` | 87 | |
| `Hidden::TingChinese - Saved Words` | 9 | |

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

### `Vocab Cloze::Connectives` (2026-07-31) — 61 cards

Cloze-Recall cards for written-register discourse glue: logical connectives → formal frames →
stance adverbs (然而 从而 尽管 此外 反之 换句话说 由此可见 相对而言 综上所述 未必 毕竟 势必 …).
Own subdeck on the `Default` preset (10/day), isolated from the shared `HSK` preset.

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

There are also 10 orphaned presets (`Languages`, `Chinese Characters`, `Chinese Vocabulary`,
`Chinese Sentences`, `Vocab Cloze`, `Mined`, `HSK7-9`, `Hanly Gap`, two `Default`s) used by
**0 decks** — leftovers
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

| Level | Words in HSK 3.0 | Status |
|---|---|---|
| 1 | 278 | All in HSK deck |
| 2 | 172 | All in HSK deck |
| 3 | 468 | All in HSK deck |
| 4 | 955 | All in HSK deck |
| 5 | 1,559 | All in HSK deck |
| 6 | 1,762 | All in HSK deck |
| 7-9 | 5,246 | In HSK7-9 deck |
| **Total 1-9** | **10,440** | Covered across both HSK decks |

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
- Uses Claude via single-loop tool-calling architecture with 16 tools
- 8 read-only (search, get stats, list decks, etc.)
- 2 card creation (`add_chinese_vocab`, `add_general_card`)
- 5 modification (suspend, unsuspend, tag, delete, move)
- 1 sync tool
- Commands: `/status`, `/decks`, `/log`, `/clear`, `/help`
- Default deck: `Knowledge::Languages::Chinese::Vocabulary` (not used — cards go to HSK/non-HSK)

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
