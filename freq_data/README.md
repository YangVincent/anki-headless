# Vocab system — frequency-ordered Chinese learning

Tooling that turned a scattered Anki collection into a single **frequency-ordered "Vocab" deck**,
with pipelines for generating example sentences and character mnemonics.

Built for a **heritage speaker** whose goal is reading (novels, business/finance media like 小Lin,
papers). Bottleneck is *word knowledge*, not character decoding — so the deck is **word-first,
frequency-ordered**, not gated on character mastery. See "Design decisions" below.

---

## Data sources

| Source | What | Where | Role |
|---|---|---|---|
| **CC-CEDICT** | dictionary, ~120k headwords (pinyin + definitions) | `/home/vincent/dong-chinese/Resources/cedict_ts.u8` | meaning / pinyin / traditional |
| **wordfreq** (+`jieba`) | word frequencies (Zipf), 334k words | pip, in `.venv` | ordering, gap-finding |
| **pypinyin** | hanzi → tone-marked pinyin | pip, in `.venv` | card pinyin |
| **Hanly export** | character-learning progress | `june_hanly.json` | informational only (NOT a gate) |

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
bash freq_data/anki_op.sh chars freq_data/char_apply.py --apply
```
`char_gen.py` calls Claude (key from `.bot_config.json`) to decompose each character + write a
Hanly-style mnemonic. `char_apply.py` **enriches** an existing `ChineseCharacters` card's `Notes`
field, or **creates** a new one in the `Characters` deck. Use on-demand for characters that trip you.

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
- [ ] Apply the 875 gap-card sentences + create those cards in Vocab, then reposition by frequency.
- [ ] Wild-add: Chrome-extension adds → tag `mined` + front-of-queue; frequency re-sort excludes `mined`.
- [ ] Audio for generated sentences (deck uses HyperTTS/Forvo) — separate TTS pass.
- [ ] Optional: reverse/production deck when ready; ground char decomposition in Make-Me-a-Hanzi data.
