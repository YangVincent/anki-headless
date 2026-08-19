# Tests

Run them:

```
tests/run.sh            # all 46, about 20 seconds
tests/run.sh -v         # with names and the reason each test exists
.venv/bin/python -m unittest tests.test_gate.GateInvariants
```

They also run daily, from `freq_data/anki_daily.sh` (12:10 UTC). A failure makes that
script exit non-zero.

## Why these tests exist

Every defect ever found in this project was found by **executing the code against a copy
and constructing the state it forbids**. Nobody had done that in the life of the project.
That is why a renamed deck could sit dead in a background job for months, why a tool's
report could drift from its behaviour, and why three separate claims of "this is
thorough" were each wrong.

So the tests are not a coverage exercise. Each one names a defect that reached the live
system, and asserts the behaviour that would have caught it. **If a test passes on code
that has its defect, the test is wrong.** That is checkable: revert a fix and run it.

## Safety

The real collection is never opened for writing.

* The fixture copies it (`mode=ro`, WAL included) and points `bot.COLLECTION_PATH` at the
  copy before any test body runs.
* Each test method gets a **fresh** copy, so a test that writes cannot affect the next.
* The real file's size and mtime are recorded at import and checked at exit. If a test
  touches it, the suite exits 9 rather than passing.
* `bot.log_change` writes beside whichever collection is open, so the changelog follows
  the copy. That was not always true — twelve false entries reached the real changelog
  before it was fixed.

One constraint worth knowing: **Anki allows one open handle per collection.** The tool
layer opens its own, so `CollectionTest` opens lazily and `self.tool()` closes the
fixture's handle first. A fixture that held one open made every tool call raise
"Anki already open" — which the tests found on their first run.

## What is covered

| File | What it pins |
|---|---|
| `test_decks.py` | Role resolution. A missing deck raises instead of shortening a list; the archive raises instead of returning empty; case-insensitivity matches Anki; `HSK` does not subtree-match `HSK7-9`; the gate-owned decks are not writable. |
| `test_gate.py` | The four invariants, each by constructing the state it forbids. Plus idempotency from a disturbed state, and that the gate returns a report dict rather than `None`. |
| `test_tools.py` | Every declared tool executes. The write allowlist. Promotion keeps a review card's deck and schedule. `due` refuses a position on a review card or a card on loan to a filtered deck. |
| `test_placement.py` | The template deck overrides. A cloze card generated months later lands in `Cloze`, not the note's home deck — the bug that put 65 of them in `Default`. The collection's shape. |

## Adding one

Put it beside the defect it describes, and say in the docstring what went wrong. A test
whose name and docstring do not identify a real failure is hard to trust later.
