"""One shape for every script that touches the collection.

WHY THIS EXISTS. Five live scripts each hand-rolled the same four things: a retry loop
for the collection lock, an `--apply` flag, a VERIFY block, and an exit code. Each copy
drifted. The failures that followed were all the same kind — a script reported success
while doing nothing:

  * `cloze_gate.py` named a deck that had been renamed away and released 0 cards a day
    for months, printing a cheerful summary each time.
  * `suspend_deck.py` suspended 212 cards and wrote no changelog entry.
  * `anki_daily.sh` returned exit 0 when its backup failed outright.
  * `set_template_decks.py` and `fix_default_deck.py` named decks that stopped existing
    hours after they ran; a re-run would have failed on their own targets.

So this harness makes the safe path the short path:

  * DRY RUN IS THE DEFAULT. Writing requires `--apply`, always.
  * `check()` is not optional decoration. Any failed check sets a non-zero exit code, so
    a wrapper or a cron can see it. A script with zero checks is itself an error.
  * A run that writes and records no changelog entry is an error.
  * The collection is always closed, and the lock retry is uniform.

Usage:

    from tools.collection_op import CollectionOp

    with CollectionOp("suspend-deck", "Suspend every card in one deck.") as op:
        cids = op.col.find_cards('"deck:Mined"')
        op.plan("suspend", len(cids))
        if op.will_write:
            op.col.sched.suspend_cards(cids)
            op.record("suspend_deck", note_ids, {"deck": decks.NEW_WORDS_DECK})
        op.check("cards left live", live_count, 0)
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, "/home/vincent/anki-headless")
import bot  # noqa: E402


class OpError(RuntimeError):
    pass


class CollectionOp:
    def __init__(self, label, description="", argv=None, open_timeout=60):
        argv = sys.argv[1:] if argv is None else argv
        self.label = label
        self.description = description
        self.apply = "--apply" in argv
        self.verify_only = "--verify" in argv
        self.args = [a for a in argv if not a.startswith("--")]
        self.open_timeout = open_timeout
        self.col = None
        self._plans: list[tuple[str, int]] = []
        self._checks: list[tuple[str, object, object, bool]] = []
        self._wrote = False

    @property
    def will_write(self):
        """True only in --apply mode. Guard every mutation with this."""
        return self.apply and not self.verify_only

    # ── lifecycle ─────────────────────────────────────────────────────
    def __enter__(self):
        print(f"[{self.label}] {'APPLY' if self.will_write else 'DRY RUN'}"
              + (" (verify only)" if self.verify_only else ""))
        if self.description:
            print(f"  {self.description.strip().splitlines()[0]}")
        deadline = time.time() + self.open_timeout
        last = None
        while time.time() < deadline:
            try:
                self.col = bot.open_collection()
                break
            except Exception as e:  # noqa: BLE001 — the lock clears on its own
                last = e
                time.sleep(2)
        if self.col is None:
            raise OpError(f"collection stayed locked for {self.open_timeout}s: {last}")
        return self

    def __exit__(self, exc_type, exc, tb):
        try:
            if exc_type is None:
                self._report()
        finally:
            if self.col is not None:
                self.col.close()
        if exc_type is not None:
            print(f"\n[{self.label}] FAILED: {exc_type.__name__}: {exc}", file=sys.stderr)
            sys.exit(2)
        sys.exit(self._exit_code())

    # ── recording ─────────────────────────────────────────────────────
    def plan(self, what, n):
        """Describe an intended change. Printed in both modes."""
        self._plans.append((what, n))
        return n

    def record(self, action, note_ids=None, details=None):
        """Write a changelog entry. A writing run that never calls this is an error —
        suspend_deck.py suspended 212 cards and left no trace."""
        if not self.will_write:
            return
        bot.log_change(action, note_ids, details)
        self._wrote = True

    def check(self, label, got, want):
        """A post-condition. A failure sets the exit code; it does not just print."""
        ok = got == want
        self._checks.append((label, got, want, ok))
        return ok

    # ── output ────────────────────────────────────────────────────────
    def _report(self):
        if self._plans:
            print(f"\n  {'applied' if self.will_write else 'plan'}:")
            width = max(len(w) for w, _ in self._plans)
            for what, n in self._plans:
                print(f"    {what:<{width}}  {n}")
        if self._checks:
            print("\n  VERIFY")
            width = max(len(l) for l, _, _, _ in self._checks)
            for label, got, want, ok in self._checks:
                print(f"    {'OK ' if ok else 'BAD'} {label:<{width}}  {got}"
                      + ("" if ok else f"  (want {want})"))
        if not self.will_write:
            print("\n  DRY RUN — nothing written. Add --apply to commit.")

    def _exit_code(self):
        if not self._checks:
            print(f"\n[{self.label}] ERROR: the op declared no checks. A script that "
                  "cannot say what 'correct' looks like cannot report failure.",
                  file=sys.stderr)
            return 3
        failed = [l for l, _, _, ok in self._checks if not ok]
        if failed:
            print(f"\n[{self.label}] FAILED {len(failed)} check(s): "
                  + ", ".join(failed), file=sys.stderr)
            return 1
        if self.will_write and any(n for _, n in self._plans) and not self._wrote:
            print(f"\n[{self.label}] ERROR: wrote to the collection but recorded no "
                  "changelog entry. Call op.record().", file=sys.stderr)
            return 4
        return 0
