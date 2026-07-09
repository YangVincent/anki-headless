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
