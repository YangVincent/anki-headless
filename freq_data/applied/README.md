# Applied — one-shot scripts that have already run

These scripts did their job and were retired here on 2026-08-19. **Every one of them names
a deck that no longer exists.** They are kept as a record of what was done to the
collection, not as tools.

## Why they are here rather than deleted

A script naming a dead deck does not crash. `col.decks.id_for_name()` returns `None`, the
query matches nothing, and the run reports success while doing nothing at all. That failure
mode cost months: the cloze gate, two background sync jobs and `add_chinese_vocab` all ran
that way. Leaving 45 such scripts beside the working ones invites someone to re-run one and
believe the output.

## What broke them

Deck names they were written against, and what replaced each:

| Named | Status |
|---|---|
| `Vocab` | Retired. Its contents became `HSK`, `HSK7-9` and `non-HSK`. A single-deck query cannot be rewritten to three decks mechanically — the semantics differ per script. |
| `Vocab Cloze` | Renamed `Cloze` (2026-08-19). |
| `Hidden`, `Hidden::Archive`, `Hidden::` | Folded into the single `Archive` deck (2026-08-19). |
| `Characters`, `Characters::Hanly Gap` | Emptied and removed (2026-08-19). |
| `Calibration`, `Knowledge` | Never existed in this collection, or removed long before. |

## Before re-using any of these

1. Read it. Work out what the deck it names meant at the time.
2. Rewrite it against `decks.py` — ask for a ROLE (`RECOGNITION_DECKS`, `NEW_WORDS_DECK`,
   `CLOZE_DECK`, `ARCHIVE_DECK`), never a name.
3. Move it back to `freq_data/`, and confirm `freq_data/lint_deck_names.py` stays at 0.

## Superseded by something that still works

| Retired | Use instead |
|---|---|
| `resort_vocab.py` | `freq_data/resort_hsk_queue.py` — the canonical queue re-sort |
| `cloze_build.py`, `cloze_backfill.py`, `cloze_sweep.py`, `cloze_prevent.py` | `freq_data/template_gate.py` — the maturity gate owns the `Cloze` deck now |
| `char_apply.py` | Its target deck `Characters` no longer exists |
| `novel_deck_apply.py` | Its `Mined::十日终焉` deck folded into `Mined` |
