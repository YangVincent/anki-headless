# quarantine/

## hsk3_vocab.json — corrupt levels, do not use

Parsed out of the HSK 1-6 Vocabulary PDF text in `chunks/`, whose layout is a fixed six
lines per record (Num, Level, Word, Pinyin, Word Class, Meaning). Entries whose Meaning
wrapped to a second line desynchronised the reader, so from about entry 500 on, the
**Level and Word Class belong to a different word than the one they are attached to**.
Accuracy: 62% over the first 500 entries, 20-25% after, **31% across HSK 1-6**.

Word, pinyin and gloss stayed aligned (pinyin matches the official list on 9261/9294).

Moved here 2026-08-28. Replaced by two files:

- `../hsk30_official.json` — the authority for levels. Built by `build_hsk30_official.py`
  from `hsk30_source.csv`, which carries the official band IDs and reproduces the published
  band sizes 500/772/973/1000/1071/1140/5636.
- `../supplementary_vocab.json` — the same 10,440 words with **level and pos removed**, so
  no script can read a corrupt level from them. Used only as a membership set: "this is a
  real word, do not park the card", which is what `hsk_match.py` needs it for. 1,128 of its
  words are not in HSK 3.0 (你好, 玩, 老虎, 数学, 红绿灯 …).

### Why it matters beyond this repo

This parse leaked onto the public web. On 2026-08-28 both hanzistroke.com and Claude's web
UI reported 构造 as "HSK 3.0 Level 6, verb" — the exact (level, pos, gloss) triple in this
file's entry 3894. The standard files it at **L4-0281, level 4, noun**. Two web sources
agreeing on an HSK level is not independent confirmation. Check the part of speech: a verb
tag on a noun means the row shifted.

Scripts in `../applied/` still import `hsk3_vocab.json` by name and will fail on import.
They are history, not tools to re-run — see the note in `../README.md`.
