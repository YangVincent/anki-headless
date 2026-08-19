# Vocab system — frequency-ordered Chinese learning

> **Deck names.** No script here spells a deck name out. They come from `decks.py`, which
> declares each deck's role, and `freq_data/lint_deck_names.py` keeps that at zero.
>
> `freq_data/applied/` holds 45 one-shot scripts retired on 2026-08-19. Every one names a
> deck that no longer exists, so every one is a silent no-op if re-run. See the README
> there before re-using any of them.

Tooling that turned a scattered Anki collection into a single **frequency-ordered "Vocab" deck**,
with pipelines for generating example sentences and character mnemonics.

Built for a **heritage speaker** whose goal is reading (novels, business/finance media like 小Lin,
papers). Bottleneck is *word knowledge*, not character decoding — so the deck is **word-first,
frequency-ordered**, not gated on character mastery. See "Design decisions" below.

---

## Data sources

| Source | What | Where | Role |
|---|---|---|---|
| **CC-CEDICT** | dictionary, ~120k headwords (pinyin + definitions) | `/home/vincent/chinese-projects/dong-chinese/Resources/cedict_ts.u8` | meaning / pinyin / traditional |
| **wordfreq** (+`jieba`) | word frequencies (Zipf), 334k words | pip, in `.venv` | ordering, gap-finding |
| **pypinyin** | hanzi → tone-marked pinyin | pip, in `.venv` | card pinyin |
| **Hanly export** | character-learning progress | `june_hanly.json` | informational only (NOT a gate) |
| **HSK 3.0 word list** | official 2021 standard, 11,092 band entries → 10,978 distinct words | `hsk30_official.json` (built by `build_hsk30_official.py` from `hsk30_source.csv`) | HSK levels: deck tags, queue order, dashboard denominators |

**`hsk3_vocab.json` is superseded and wrong — do not use it for levels.** It was parsed out of the
HSK 1-6 Vocabulary PDF text in `chunks/`, whose layout is a fixed six lines per record (Num, Level,
Word, Pinyin, Word Class, Meaning). Entries whose Meaning wrapped to a second line desynchronised the
reader, so from about entry 500 on, the Level belonged to a different word than the one it was
attached to: 62% correct over the first 500 entries, 20-25% after, and only **31% correct** across
HSK 1-6. Word/pinyin/gloss stayed aligned (pinyin matches the official list on 9261/9294), which is
why `build_hsk30_official.py` carries the glosses over and replaces only the levels. The builder
refuses to run unless the source reproduces the published band sizes
(500/772/973/1000/1071/1140/5636), which is the check that caught this. Several one-off repair
scripts in this directory still reference the old file; they are history, not tools to re-run.

Frequency note: **Zipf** = log10(per-billion-word freq). Zipf≥5 ≈ very common, ≥4 common, ≥3.5 the
deck cutoff, <3 gets noisy (proper nouns + segmentation fragments). Always filter the raw frequency
list to "in CC-CEDICT AND not a proper noun (capitalized pinyin)" — that drops ~65% junk.

---

## The Vocab deck

- **~15.2k new cards**, frequency-ordered (most common first), one card per word (deduped).
- Built by merging the old `hanly` deck + unarchiving `Archive::Words` for the **Zipf≥3.5 clean
  target (~14.2k words)**; 94% already existed, only ~875 needed generating.
- **Forward (recognition) cards only** — notetype `ChineseVocabulary`, template ord0 "Hanzi-English".
  Reverse/production (`hanly-reverse`, archive ord1) left **suspended** — deferred until you want
  active production practice.
- `Archive::Words` (~54k forward cards) kept **suspended** as a backup source pool.

---

## Tools  (`freq_data/`, run with `/home/vincent/anki-headless/.venv/bin/python`)

### Safety wrapper — use for EVERY mutation
```bash
bash freq_data/anki_op.sh <label> <python_script> [args]
```
Auto-backup → stop `anki-bot` → wait for the collection lock → run the script → restart the bot once.
`collection.anki2` is single-writer; the bot and scripts must not open it at the same time.
**The op script must verify (print results) before it exits** — the bot restarts only after, so do all
write+verify in the one stopped-bot window (never verify after restart, or you race the startup sync).
Read-only checks can run directly (retry on lock).

### Frequency analysis (read-only)
- `analyze_order.py` — queue order vs frequency (inversions).
- `analyze_gaps.py` — coverage + missing common words.
- `build_report.py` — per-card CSV (`REPORT_per_card.csv`) + missing-words CSV.

### Example-sentence generation
1. Build an input file: `[{word, gloss, ...}]` (e.g. `gen_gaps/gap_input.json`).
2. Run a **sonnet Workflow** (see `gen-gap-sentences` / `gen-anki-sentences` scripts): N agents,
   40 words each, each reads its slice and writes `out_batch_<i>.json` with
   `{word, sent_simp, sent_trad, pinyin, english}`.
3. `apply_sentences.py --apply` (via wrapper) — fills 6 `Sentence*` fields; bolds the word and
   derives `[ ]` cloze in code; validates the word appears in the sentence.

### Character-mnemonic generator (post-Hanly tool)
```bash
.venv/bin/python freq_data/char_gen.py 残 酷 谬 …      # Claude → chars/char_cards.json
# RETIRED to freq_data/applied/ — its target deck `Characters` no longer exists.
# bash freq_data/anki_op.sh chars freq_data/char_apply.py --apply
```
`char_gen.py` calls Claude (key from `.bot_config.json`) to decompose each character + write a
Hanly-style mnemonic. `char_apply.py` **enriches** an existing `ChineseCharacters` card's `Notes`
field, or **creates** a new one in the `Characters` deck. Use on-demand for characters that trip you.

### Wild-add (Telegram bot) + frequency re-sort
The `anki-bot` Telegram/HTTP bot now files added words into **Vocab**, tags them **`mined`**, and
places them at the **front of the queue** (next-up) — `bot.promote_to_vocab()`, called automatically
by `add_chinese_vocab` and by `tag_notes` with the `mined` tag. Reverse card is suspended.
The bot also has a **`lookup_frequency`** tool (`bot.freq_tier()`) — ask it how common a word is
(very common → rare).
```bash
# periodically re-sort the backbone by frequency; 'mined' cards stay pinned at the front
bash freq_data/anki_op.sh resort freq_data/resort_hsk_queue.py --apply
# (resort_vocab.py is retired to freq_data/applied/ — it re-sorted the `Vocab` deck,
#  which became HSK / HSK7-9 / non-HSK. resort_hsk_queue.py is the canonical re-sort.)
```

### HSK / HSK7-9 new-queue order (canonical)
```bash
bash freq_data/anki_op.sh resort-hsk freq_data/resort_hsk_queue.py --apply
```
The rule (2026-07-09): **words by HSK level, then by zipf frequency descending within the
level; every single-character card immediately before the first word that uses it.**
Characters used by no *new* word in their deck (their words are already studied) go to the
tail by frequency — ~176 in HSK, 1 in HSK7-9. Suspended new cards are positioned too, so
they land correctly whenever unsuspended. The script self-verifies all three invariants.

Supersedes `quality/resort_hsk_by_level.py` (words only — it repositions every `type=0 ord=0`
card by word key, so the ~1,000 interleaved `ChineseCharacters` cards, which carry no HSK
level tag, would all be flung to the back) and the placement pass in
`quality/place_gap_chars.py`. Don't run those against HSK any more.

### New-cards/day limit
```bash
bash freq_data/anki_op.sh newlimit freq_data/set_new_per_day.py --deck HSK --per-day 10 --apply
```
Edits `new.perDay` on the preset the deck **already** uses (dry-run without `--apply`) and
pushes to AnkiWeb. It refuses to create a preset: a fresh one comes with Anki's *stock*
defaults (`new.order=RANDOM`, `fsrsParams6=[]`, `autoplay=True`, …), which has silently
wrecked this collection's scheduler before. Verification is a **full recursive diff** of the
preset before vs after — `new.perDay` plus `mod`/`usn` are the only tolerated changes — and it
warns if other decks share the preset.

**Since 2026-07-27 there is exactly one preset in use: `HSK`, on all 24 decks** (see
*One preset for everything* below). So `--per-day` now changes the limit for the whole
collection, and the "other decks share this preset" warning will always fire. To give one
deck its own limit, set a deck-level override rather than making a new preset.

### Novel deck — 十日终焉·囚笼  (2026-07-27)

```bash
# RETIRED to freq_data/applied/ — `Mined::十日终焉` folded into `Mined` on 2026-08-19.
# .venv/bin/python freq_data/applied/novel_deck_apply.py --col <copy>    # dry run
.venv/bin/python freq_data/novel_deck_apply.py --dump-pool /tmp/p.json   # pool for screening
.venv/bin/python freq_data/novel_deck_screen.py --pool /tmp/p.json       # drop names/non-words
bash freq_data/anki_op.sh novel-deck freq_data/novel_deck_apply.py --apply
bash freq_data/anki_op.sh novel-fix  freq_data/novel_deck_apply.py --refresh --apply
```
`Mined::十日终焉`, 200 cards on the existing **Mined** preset, ordered by in-book frequency
(139× → 4×). The premise "next 200 new words" did not survive measurement: of the 2,212
dictionary words in the book worth studying, only **31** have no card at all. 765 are already
studied, 704 sit unseen in **HSK** and 406 unseen in other active decks — all left alone — so
the deck is 183 never-seen cards gathered out of `Hidden::Archive` (which already carry pinyin,
gloss and audio) plus 17 new notes. `novel_deck_apply.py` asserts HSK/HSK7-9 card counts are
byte-identical before and after; it moves nothing out of any active deck and creates no
duplicates.

Two passes are not optional. `novel_deck_screen.py` (LLM, book sentences as evidence) drops
character nicknames that are also real words — jieba's tagger misses them precisely *because*
they are ordinary words — plus segmentation artifacts: 潇潇, 对齐 (对+齐夏), 无表情, 屋外, 床边.
`--refresh` repairs field content in place: the hetushu scrape splices `_图_书` and bare
domains mid-sentence, and CEDICT pinyin is numbered (`suo3 tou5`) where the deck uses
diacritics. First build needed 154 sentence and 24 pinyin fixes.

`study_list_shiri_zhongyan_vol1.json` is **not** a usable source for this — it ranks raw jieba
tokens, so only 14 of its top 200 are dictionary words. Count from the book text instead.

### FSRS tuning  (2026-07-27)

```bash
bash freq_data/anki_op.sh fsrs-tune freq_data/fsrs_tune.py --apply
bash freq_data/anki_op.sh fsrs-report freq_data/fsrs_tune.py --report   # weeks later
```
Refits `fsrsParams6` on `preset:"HSK"` history (optimizer re-run in-script, not pasted) and sets
`desiredRetention` 0.93 → 0.90. Full recursive preset diff gates the write, same rule as
`set_new_per_day.py`. Existing cards keep their due dates.

> Later the same day every deck was moved onto this preset, so **these parameters now
> schedule the whole collection**, not just HSK. The measurements below are still HSK-only —
> that is the only deck with enough history to fit against. Fitting one deck's history and
> applying it collection-wide is deliberate: the alternative was leaving five other presets on
> Anki's factory defaults, which describe nobody's memory in particular. Re-fit against
> `preset:"HSK"` regardless; a search over all decks would drown the signal in the archive
> decks' near-empty histories.

**The measurement matters more than the change.** HSK true retention was 78.9% against a 93%
target, but that gap is not a scheduling failure — retention *rises* with interval (64% at ≤1d,
96% at >90d), which is backwards for a forgetting curve and is a selection effect. The deck is
two populations: words known on sight (64% of cards, first grade Easy, 92.9% retention, 29% of
review load) and words being learned (first grade Again, **71.7% retention, 63% of review
load**). FSRS had already sorted them; the hard third fails at 1-day intervals, i.e. it has
bottomed out and no parameter fixes it.

`compute_optimal_retention` returns **0.700** — the floor of the allowed range, meaning the
simulator degenerated (new cards capped at 10/day cap knowledge growth, so retention reads as
pure cost). Distrust boundary values. The real 365-day tradeoff: 0.93 → 0.90 costs ~62 words
known and saves ~3,600 reviews.

`fsrs_baseline.json` snapshots retention split by population + the worst 25 words, so `--report`
can answer whether the *hard* words improved rather than the aggregate.

### Bound-character parking  (2026-07-27)

```bash
bash freq_data/anki_op.sh park-chars freq_data/park_bound_chars.py --apply
bash freq_data/anki_op.sh unpark     freq_data/park_bound_chars.py --undo --apply
```
Suspends single-character cards that are **never studied**, unsuspended, and whose standalone
word frequency is below zipf 4.0 (`wordfreq`, sanity-checked: 人 6.74, 的 7.79, 衬 3.11).
400 cards parked; 333 unseen character cards stayed because those characters *are* words
(脱, 演, 降). Studied cards are never touched — the script asserts the studied count is
unchanged. Tag `parked::bound-character`, suspend not delete.

Why: of 1,082 single-character HSK cards, 733 were unseen and 400 of those are characters that
never stand alone — **274 of them one half of a two-character word whose other half is also a
separate card**. 咳 and 嗽 were scheduled individually; the word is 咳嗽. 乒 has no meaning
without 乓. These were already the worst cards in the deck: single characters lapse 3+ times at
twice the rate of words (15% vs 7%), 71.8% vs 80.2% retention. The character knowledge is still
worth having — it comes from meeting 幽 inside 幽默 and 幽静, which the word cards already do.

### One preset for everything  (2026-07-27)

```bash
bash freq_data/anki_op.sh unify-presets  freq_data/unify_presets.py --apply
bash freq_data/anki_op.sh undo-presets   freq_data/unify_presets.py --undo --apply
```
All 24 non-filtered decks now use the **HSK** preset, and `autoplay` is off on every preset
including the unused ones. Previous assignments are in `preset_backup.json`.

Six presets were in use and had drifted 22–24 fields apart; only HSK had FSRS parameters fitted
to real history. Four more presets — `Chinese Characters`, `Chinese Sentences`,
`Chinese Vocabulary`, `Languages` — had **no decks at all**, leftovers from a CrowdAnki import
still carrying `crowdanki_uuid` and FSRS *v4* `fsrsWeights`. They were muted and left in place;
deleting a preset re-homes its decks unpredictably.

Behaviour changes worth remembering when something looks odd later:
- `non-HSK` went from 20 new cards/day to 10 (9,074 cards — the biggest non-HSK deck)
- `Characters::Hanly Gap` went 8/day → 10
- leech action is now **suspend at 10 lapses** everywhere, where most decks previously
  **tagged at 8**. Cards will start disappearing from those decks on their own.
- learning steps gained the 1-hour step (1m/10m/1h) everywhere

The script creates and deletes nothing — it only reassigns `deck["conf"]` and flips `autoplay`.
Creating a preset is what silently restores stock `new.order`/`fsrsParams6`/`autoplay`.

### Leech rewriting  (2026-07-27)

```bash
.venv/bin/python freq_data/leech_rewrite.py            # -> leech_rewrite.json (LLM)
bash freq_data/anki_op.sh leech-rewrite freq_data/leech_apply.py --apply
bash freq_data/anki_op.sh undo-text     freq_data/leech_apply.py --undo --apply
```
118 HSK cards had lapsed 3+ times. **112 already had example sentences**, so context was not the
missing piece. Three distinct failures, three fixes:
- **connectives** (然而, 以及, 此外, 进而, 从而) — all gloss to "however"/"in addition"/"thus",
  so nothing on the card distinguishes them from 但是/可是/不过/却. The contrast *is* the card;
  it goes in `Notes`.
- **abstract words** (原则 "principle") — correct translation, no hook. Fix is collocations.
- **characters** (22) — several glosses simply wrong: 幽 was "Humor", which is 幽默's meaning
  (and 幽默 is a phonetic loan, so its characters mean nothing); 符's example sentence was an
  anime fragment. 13 wrong or misleading glosses found in total.

`leech_apply.py` writes `Meaning`/`Notes`/`SentenceSimplified`/`SentenceMeaning`, clears
`SentencePinyin` (it belonged to the replaced sentence), and leaves `Pinyin` alone — the markup
in it is tone colouring, not junk. Originals go to `leech_backup.json` first. It also parks the
characters marked `learn-in-word`, **but only single characters**: the flag came back on 放弃
too, a common word with no replacement given, and parking it would have been a real loss. 祝 is
excluded by name — flagged, but it genuinely stands alone (祝你生日快乐).

---

## Design decisions (why it's built this way)

- **Word-first, frequency-ordered.** A heritage speaker can mostly decode characters; the gap is
  knowing words. Frequency = usefulness order. Character-readability is NOT a gate.
- **Hanly and Anki are decoupled** (no tagging pipeline) but complementary: Hanly builds character
  memory anchors (finish it ~1200 chars), Anki builds words on top. After Hanly, learn new characters
  in context + the mnemonic generator for friction cases.
- **Reverse deferred.** Recognition first; production cards already exist (suspended) for later.
- **Cutoff Zipf≥3.5** (~14k clean words) — comprehensive for the goal, ends naturally, avoids the
  noisy <3 tail. Deeper is fine for a heritage speaker (the easy head is cheap) but 3.5 stays clean.

## Roadmap / pending
- [x] Apply the gap-card sentences + create those cards in Vocab, reposition by frequency (873 cards).
- [x] Wild-add: bot adds → Vocab + tag `mined` + front-of-queue; `resort_vocab.py` excludes `mined`.
- [x] `lookup_frequency` tool in the bot.
- [ ] Audio for generated sentences (deck uses HyperTTS/Forvo) — separate TTS pass. (Not planned.)
- [ ] Optional: reverse/production deck when ready; ground char decomposition in Make-Me-a-Hanzi data.
- [ ] **2026-08-17: run `fsrs_tune.py --report`.** Open question is whether the 71.7% "had to
      learn" population moved at all. If it has not, scheduling is confirmed irrelevant for those
      and the answer is card design — rebuild the remaining leeches as sentence/cloze cards
      rather than word→gloss. Also worth re-running `leech_rewrite.py` on whatever the *new*
      3+-lapse set is, and re-optimising params once ~1-2k more reviews have accumulated.
- [ ] The 118 rewritten descriptions were spot-checked, not all read. `放弃` was mislabelled
      `learn-in-word` by the same pass; skim the rest as they come up in review.
- [ ] Watch for cards quietly vanishing from `non-HSK` / `Vocab Cloze` / `Mined`: those decks
      previously only *tagged* leeches at 8 lapses and now **suspend** them at 10. That is the
      intended behaviour, but the first time a deck shrinks by itself it will look like a bug —
      check `tag:leech is:suspended` before assuming anything broke.
- [ ] Page-reading endpoint (`page_read.py`) is parked at 54% recall / 87% precision on page 006
      and is wired into nothing. Untried levers: more bands, unioning independent passes, and
      full-resolution source photos (the benchmark ran on a 1400px render, not the original).
