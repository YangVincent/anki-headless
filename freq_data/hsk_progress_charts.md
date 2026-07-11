# HSK progress bar charts

How to reproduce the ASCII HSK progress charts (the "am I on HSK 4 yet" bars).
There are two variants:

| Variant | Groups words by | Answers |
|---|---|---|
| **3.0** | each card's `HSK::HSKn` tag in the **HSK deck** | how far through the deck's own 9-band queue you are |
| **2.0** | intersecting your **whole collection** against the old 6-level HSK 2.0 word list | where you'd place on the pre-2021 HSK scale |

Both are produced by `freq_data/hsk_progress_chart.py`:

```bash
.venv/bin/python freq_data/hsk_progress_chart.py --standard 3.0
.venv/bin/python freq_data/hsk_progress_chart.py --standard 2.0
```

The script copies `collection.anki2` to a temp file and reads that, so it is safe
to run while `anki-bot` holds the live collection. Nothing is written back.

## Data sources

- **Card status** — `collection.anki2`, `cards` joined to `notes`. The word is the
  note sort field `n.sfld` (HTML stripped).
- **3.0 level** — the `HSK::HSKn` tag on the note (`n.tags`). The deck is built on the
  2021 nine-band standard; see `freq_data/hsk3_vocab.json` for the source word→band list.
- **2.0 level** — `freq_data/hsk20_vocab.json` (4,995 words, levels 1–6). This is the
  official 2012 HSK 2.0 vocabulary list, fetched from the canonical
  `glxxyz/hskhsk.com` GitHub mirror (`data/lists/HSK Official With Definitions 2012 L1..L6.txt`,
  tab-separated: simplified, traditional, numeric-pinyin, pinyin, gloss). Per-level
  counts match the official standard exactly: 150 / 150 / 300 / 600 / 1300 / 2500.

## Status buckets

Each card is bucketed by `status_of(queue, type, reps)`:

| Bucket | Rule | Meaning |
|---|---|---|
| **learned** | `reps > 0` or `type != 0` | seen at least once (learning / review / relearning) |
| **to-do** | `reps == 0 and type == 0 and queue != -1` | new, never studied |
| **suspended** | `queue == -1` | parked / removed from scheduling |

In **2.0** mode a word can have several cards across decks, so it takes its **best**
status (learned > to-do > suspended).

## The progress %

```
progress = learned / (learned + to-do)      # suspended EXCLUDED from the denominator
```

Suspended is excluded so the bar reflects "of the cards actually in rotation, how many
have I started". This matches the original chart's methodology.

## Caveats (read before quoting a number)

- **Heritage-speaker suspended basics.** At the low levels a large suspended band is
  mostly words known cold and parked on purpose (~164 HSK1/2 single-char cards; see the
  `hsk-basic-chars-suspended-intentionally` memory). So the printed HSK1–3 progress
  (92–97% on the 2.0 chart) understates real command, which is ~100% there. If you want
  "known" to include parked-because-known, add `suspended` back into the numerator.
- **2.0 vs 3.0 don't line up.** HSK 3.0 front-loaded vocabulary: new Band 1 (500 words)
  is larger than old Levels 1+2 combined (300). So the same knowledge reads as a *higher*
  level number on the old scale. Finishing new Band 3 ≈ mid old-HSK-4 by word count.
- **Matching is by simplified surface form** (`n.sfld` vs the 2.0 `word` field). A word
  stored only in traditional in the deck would miss; in practice the deck is simplified,
  and the 2.0 check reports 0 absent (full coverage), so this isn't currently an issue.
- **`type != 0` counts in-progress learning cards as "learned."** A card lapsed back to
  new (`type==0`, `reps>0`) still counts as learned via the `reps>0` clause — intended:
  it has been seen.

## Rendering elsewhere

The script prints ASCII (20-char bars, `█`/`·`). For a rendered image/artifact, feed the
same per-level `[learned, to-do, suspended]` rows to any plotting stack — see the
`dataviz` skill for palette/mark guidance. The numbers are identical; only the medium
changes.
