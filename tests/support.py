"""Test fixture: a private copy of the collection, and a guard that it stays private.

Every defect found in this project was found by EXECUTING the code against a copy and
constructing the state it forbids. Nobody had done that in the life of the project, which
is why a deck rename could sit dead for months and a tool's report could drift from its
behaviour. This makes that technique cheap and repeatable.

Two rules the fixture enforces, because the alternative is editing the real collection:

  * `bot.COLLECTION_PATH` is redirected before any test body runs, and restored after.
  * The real collection's size and mtime are recorded at import and checked at exit. If a
    test touches it, the suite says so rather than passing quietly.

`bot.log_change` writes beside whichever collection is open, so the changelog follows the
copy too. That was not always true: twelve false entries were written to the real
changelog before it was fixed.

Run:  .venv/bin/python -m unittest discover -s tests -v
"""
from __future__ import annotations

import atexit
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, "/home/vincent/anki-headless")
import anki_cache  # noqa: E402
import bot         # noqa: E402
import decks       # noqa: E402

REAL = Path("/home/vincent/anki-headless/collection.anki2")
REAL_CACHE = Path(anki_cache.CACHE_PATH)


def _fingerprint():
    """What the real collection holds, not what its inode says.

    (size, mtime) is NOT enough and used to be all this guard checked. The collection is
    in WAL mode, so a committed write lands in collection.anki2-wal and moves NEITHER the
    size nor the mtime of the main file. Measured: suspending 50 cards left both
    byte-identical while a concurrent reader saw the change, so the guard passed on a test
    that wrote to the real collection. `col.mod` is the value Anki bumps on every write.
    """
    con = sqlite3.connect(f"file:{REAL}?mode=ro", uri=True)
    try:
        mod = con.execute("select mod from col").fetchone()[0]
        cards = con.execute("select count(*) from cards").fetchone()[0]
        notes = con.execute("select count(*) from notes").fetchone()[0]
    finally:
        con.close()
    return (REAL.stat().st_size, mod, cards, notes)


_REAL_STAT = _fingerprint()


def _assert_real_untouched():
    now = _fingerprint()
    if now != _REAL_STAT:
        print(f"\n*** THE REAL COLLECTION CHANGED DURING THE TESTS ***\n"
              f"    was {_REAL_STAT}\n    now {now}", file=sys.stderr)
        os._exit(9)


# ── the real cache.db is guarded at the WRITE, not by its mtime ───────
# A test that forgets a path argument would write the live cache while the bot serves
# from it, and that really happened: every anki_cache entry point defaults to CACHE_PATH.
#
# Watching the file's mtime does NOT detect it, and worse, it reports a failure on every
# run. The bot writes `checked_at` every 30 seconds, so the live cache's mtime moves on
# its own: measured twice, 30.0 s apart, with no test running. The first version of this
# guard aborted the suite for exactly that reason.
#
# So guard the one thing a test controls: this process must never open the real cache
# read-write. That has no false positive, whatever the bot is doing.
_real_connect_rw = anki_cache._connect_rw


def _guarded_connect_rw(cache_path, *args, **kwargs):
    if REAL_CACHE.exists() and Path(cache_path).resolve() == REAL_CACHE.resolve():
        raise AssertionError(
            f"a test tried to OPEN THE REAL CACHE FOR WRITING ({cache_path}). "
            "Pass an explicit cache_path, or use CollectionTest, which redirects it.")
    return _real_connect_rw(cache_path, *args, **kwargs)


anki_cache._connect_rw = _guarded_connect_rw


atexit.register(_assert_real_untouched)


def copy_collection(dest):
    """A consistent copy of the live collection, WAL included.

    mode=ro so this can never take a write lock from the running bot. NOT immutable=1:
    that flag makes SQLite skip the WAL, so a committed row living only there is read as
    absent, with no error.
    """
    src = sqlite3.connect(f"file:{REAL}?mode=ro", uri=True)
    dst = sqlite3.connect(str(dest))
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    return dest


class CollectionTest(unittest.TestCase):
    """Base class. Each test method gets its own collection, so a test that writes
    cannot affect the next one."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="ankitest-")
        self.path = copy_collection(Path(self._tmp.name) / "collection.anki2")
        self._saved = bot.COLLECTION_PATH
        bot.COLLECTION_PATH = str(self.path)
        assert Path(bot.COLLECTION_PATH) != REAL, "refusing to run against the real collection"
        # The cache path is redirected for the same reason as the collection path: every
        # anki_cache reader and writer defaults to the module constant, so one forgotten
        # argument would reach the live cache while the bot serves from it.
        self.cache_path = Path(self._tmp.name) / "cache.db"
        self._saved_cache = anki_cache.CACHE_PATH
        self._saved_default = anki_cache.DEFAULT_COLLECTION
        anki_cache.CACHE_PATH = str(self.cache_path)
        anki_cache.DEFAULT_COLLECTION = str(self.path)
        assert Path(anki_cache.CACHE_PATH) != REAL_CACHE, "refusing to write the real cache"
        self._col = None

    def tearDown(self):
        try:
            self.close()
        finally:
            bot.COLLECTION_PATH = self._saved
            anki_cache.CACHE_PATH = self._saved_cache
            anki_cache.DEFAULT_COLLECTION = self._saved_default
            self._tmp.cleanup()
            _assert_real_untouched()

    def build_cache(self, **kw):
        """Build this test's private cache and return its meta."""
        return anki_cache.build(str(self.path), str(self.cache_path), **kw)

    def cache(self):
        """A read-only handle on this test's private cache."""
        return anki_cache.connect_ro(str(self.cache_path))

    # ── the collection is opened LAZILY ───────────────────────────────
    # Anki allows one open handle per collection. `execute_tool` opens its own, so a
    # fixture that holds one makes every tool call raise "Anki already open". Opening on
    # demand, and closing before a tool call, is the only arrangement that lets a test
    # both inspect the collection and drive the tool layer.
    @property
    def col(self):
        if self._col is None:
            self._col = bot.open_collection()
        return self._col

    def close(self):
        if self._col is not None:
            self._col.close()
            self._col = None

    def tool(self, name, args):
        """Call a bot tool. Closes our handle first, because the tool opens its own."""
        self.close()
        return bot.execute_tool(name, args)

    def tool_json(self, name, args):
        import json
        return json.loads(self.tool(name, args))

    def reopen(self):
        """Close and reopen, for assertions that must see committed state."""
        self.close()
        return self.col

    def deck(self, name):
        return decks.deck_id_by_name(self.col, name)

    def cards_of(self, nid):
        return {c.ord: c for c in self.col.get_note(nid).cards()}

    def a_note_with_ord0_in(self, deck_name, **where):
        """A note whose ord-0 card is in `deck_name`, optionally filtered by column."""
        clauses = " ".join(f"AND c.{k}={v}" for k, v in where.items())
        row = self.col.db.first(
            f"SELECT c.nid FROM cards c WHERE c.did=? AND c.ord=0 {clauses} LIMIT 1",
            self.deck(deck_name))
        self.assertIsNotNone(row, f"no ord-0 card in {deck_name} matching {where}")
        return row[0]

    def gate_result(self, dry_run=True):
        return (bot.apply_reverse_gate(self.col, dry_run=dry_run),
                bot.apply_cloze_gate(self.col, dry_run=dry_run))

    def assertGateSettled(self, msg=""):
        for r in self.gate_result(dry_run=True):
            self.assertFalse(r.get("error"), f"{r.get('error')} {msg}")
            for k in ("moved", "unsuspended", "suspended"):
                self.assertEqual(r[k], 0, f"{r['deck']} wants to {k} {r[k]} card(s). {msg}")
