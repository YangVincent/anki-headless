# Deck Editing Rules

For requests to explain, compare, or repair Mandarin words or cards, follow
[`skills/mandarin-card-clarification/SKILL.md`](skills/mandarin-card-clarification/SKILL.md).
The dictionary check and source attribution in that workflow are required before
claiming a distinction or changing a card.

## Read the live collection first

- Treat user-entered Hanzi and pinyin as approximate when the user is trying to recall a
  word. Do not announce a match from sound or appearance alone.
- Search the live collection before answering. If the user mentions review timing, inspect
  cards due today first; otherwise use recently modified and recently reviewed notes as
  context. Scheduler and collection evidence outrank a plausible homophone.
- Acknowledge uncertainty when more than one live candidate remains. Do not edit a card
  until its exact note has been identified.

## Write cards for retrieval

- `Meaning` is the production cue. It must identify the intended word without relying on
  `Notes`, especially for Reverse cards where Notes are hidden.
- Prefer one concise, practical core meaning over a numbered dictionary dump. Put register,
  edge cases, contrasts, and exclusions in `Notes`.
- For near-synonyms, include the shortest decisive boundary in `Meaning`: semantic role,
  grammar frame, collocation, or register. If the words genuinely overlap, say so instead
  of inventing a false distinction.
- Use a natural example that demonstrates the intended sense and, when practical, rules
  out the nearest competitor. The English sentence must not expose the target Hanzi.
- Preserve user-authored wording unless the user asks to replace it. Treat recent manual
  edits as evidence of the desired style, not stale content to normalize away.

## Collection safety

- Before writing a script for a card task, check the existing editors and use a JSON
  spec when one fits: `freq_data/applied/note_patch.py` (fields/tags),
  `freq_data/disambiguation_upsert.py` (contrasts),
  `freq_data/applied/vocab_upsert.py` (new vocabulary),
  `freq_data/merge_reverse_synonyms.py` (shared Reverse cues), and
  `freq_data/add_pattern_cards.py` (Reverse pattern prompts). Extend an existing tool
  for a recurring gap; reserve new Python scripts for distinct migrations or behavior.
- Run every collection mutation through `freq_data/anki_op.sh` and sync with media disabled.
- Inspect the current note before patching it. Preserve manual suspensions unless promotion
  is explicitly requested.
- To move one new Main card forward, use `freq_data/prioritize_new_card.py` through
  `freq_data/anki_op.sh`. Run its dry run first. Never use
  `reposition_new_cards(..., shift_existing=True)` for a single card; it renumbers
  unrelated cards and creates a large sync.
