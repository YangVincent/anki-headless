"""The read cache. Each test names a defect that reached, or nearly reached, the system.

Two shapes, for one reason: a full build costs about 6 seconds.

  * `Derivation` tests the pure functions directly. Every "three meanings of `due`"
    defect lives in those functions, so that is where the constructed states belong.
  * `BuiltCache` constructs every forbidden state in ONE collection copy, builds ONCE,
    and asserts against the result. Thirty separate builds would add three minutes.
  * `Trigger` and `Freshness` build their own, because they are about rebuilding.

If a test passes on code that has its defect, the test is wrong. That is checkable:
revert the fix and run it.
"""
from __future__ import annotations

import html as htmllib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, "/home/vincent/anki-headless")

import anki_cache
import decks
from tests import support


# ── the pure derivations ──────────────────────────────────────────────

class Derivation(unittest.TestCase):
    """No collection, no build. These are the functions every consumer used to re-derive."""

    def test_overdue_days_normalises_the_three_units(self):
        """`cards.due` holds three different units, and mixing them turned a card due in
        9 days into one 250 days overdue.

        queue 1 is a UNIX TIMESTAMP, queues 2 and 3 are a DAY NUMBER, queue 0 is a
        new-card POSITION and not a date at all.
        """
        now, today = 1_787_000_000, 246
        # intraday learning: a timestamp two hours in the past
        self.assertAlmostEqual(
            anki_cache.overdue_days(1, now - 7200, 0, 0, now, today), 2 / 24, places=6)
        # review: a day number, 9 days ago
        self.assertEqual(anki_cache.overdue_days(2, today - 9, 0, 0, now, today), 9.0)
        # day-learn: the same unit as review, NOT a timestamp
        self.assertEqual(anki_cache.overdue_days(3, today - 1, 0, 0, now, today), 1.0)
        # a review card due in the future is negative, not overdue
        self.assertEqual(anki_cache.overdue_days(2, today + 9, 0, 0, now, today), -9.0)
        # a new card has a POSITION. Reading it as a day number is the 250-days bug.
        self.assertIsNone(anki_cache.overdue_days(0, 1_997_872, 0, 0, now, today))

    def test_a_card_on_loan_to_a_filtered_deck_uses_odue(self):
        """A card in a filtered deck keeps its real due date in `odue`; `due` holds the
        filtered deck's own ordering. Reading `due` reports a wildly wrong date."""
        now, today = 1_787_000_000, 246
        self.assertEqual(
            anki_cache.overdue_days(2, 1, today - 5, 1_700_000_000, now, today), 5.0)

    def test_queue_maps_exhaustively_and_raises_on_the_unknown(self):
        """A buried card is not live. It would otherwise read as unsuspended with no due
        date, so jiangchinese would silently drop it for a day. Burying is in use here:
        config.lastUnburied is set."""
        self.assertEqual(anki_cache.card_blocked(-1), "suspended")
        self.assertEqual(anki_cache.card_blocked(-2), "buried")   # sibling buried
        self.assertEqual(anki_cache.card_blocked(-3), "buried")   # manually buried
        for queue in (0, 1, 2, 3, 4):
            self.assertIsNone(anki_cache.card_blocked(queue))
        with self.assertRaises(anki_cache.BuildError):
            anki_cache.card_blocked(-9)

    def test_status_has_four_values_and_raises_on_the_unknown(self):
        """/api/hsk-levels already separates `young` from `learning`, so three values
        cannot serve it."""
        self.assertEqual(anki_cache.card_status(0, 0), "new")
        self.assertEqual(anki_cache.card_status(1, 0), "learning")
        self.assertEqual(anki_cache.card_status(3, 2), "learning")     # relearning
        self.assertEqual(anki_cache.card_status(2, 20), "young")
        self.assertEqual(anki_cache.card_status(2, 21), "mature")      # the boundary
        with self.assertRaises(anki_cache.BuildError):
            anki_cache.card_status(7, 0)

    def test_canonical_strips_what_anki_stores(self):
        """Raw field 0 carries markup on 985 notes of this collection, and nine of them
        are HSK words that /api/hsk-levels matches by string."""
        self.assertEqual(anki_cache.canonical('<span style="x">建筑</span>'), "建筑")
        self.assertEqual(anki_cache.canonical("&nbsp;臭宝"), "臭宝")
        self.assertEqual(anki_cache.canonical("<div><div>没差</div></div>"), "没差")
        self.assertEqual(anki_cache.canonical("学习[sound:x.mp3]"), "学习")
        self.assertEqual(anki_cache.canonical("<!--zai yu-->好"), "好")
        self.assertEqual(anki_cache.canonical(None), "")

    def test_template_kind_comes_from_the_template_name(self):
        """DECK_REFERENCE records ords 1 AND 2 as production-direction, so an ord-based
        map invents a vocabulary. The names are the data."""
        self.assertEqual(anki_cache.template_kind("Hanzi-English", 0), "recognition")
        self.assertEqual(anki_cache.template_kind("English-Speaking", 1), "speaking")
        self.assertEqual(anki_cache.template_kind("Cloze-Recall", 2), "cloze")
        # another note type: ord 0 is still the recognition direction
        self.assertEqual(anki_cache.template_kind("SimpRecognition", 0), "recognition")
        self.assertEqual(anki_cache.template_kind("TradRecognition", 1), "other")
        # the same template name keeps its meaning wherever the ord lands
        self.assertEqual(anki_cache.template_kind("Cloze-Recall", 5), "cloze")

    def test_the_day_number_is_ankis_not_the_naive_one(self):
        """(now - crt) // 86400 disagrees with col.sched.today for nine hours a day.

        crt is 19:00 UTC, which is 04:00 in the creation offset (UTC+9), and the rollover
        hour is 4. Checked against the real values below; the integration test compares
        the builder against col.sched.today itself.
        """
        crt, rollover, created_west, now_west = 1_765_825_200, 4, -540, 0
        # 02:10 UTC on 2026-08-20, before that day's 04:00 rollover
        before = 1_787_192_400
        today, next_day = anki_cache.sched_timing(crt, rollover, created_west, now_west, before)
        self.assertEqual(today, 246)
        self.assertEqual(next_day, 1_787_198_400)          # 04:00 UTC that day
        self.assertEqual((before - crt) // 86400, 247)     # the naive answer, wrong
        # one minute after the rollover the day advances, and not before
        just_before = anki_cache.sched_timing(crt, rollover, created_west, now_west,
                                              1_787_198_399)[0]
        just_after = anki_cache.sched_timing(crt, rollover, created_west, now_west,
                                             1_787_198_460)[0]
        self.assertEqual(just_before, 246)
        self.assertEqual(just_after, 247)

    def test_deck_names_resolve_without_sql(self):
        """`decks.name` carries Anki's `unicase` collation, so a raw connection cannot
        use WHERE or ORDER BY on it. Matching happens in Python, case-insensitively,
        because col.decks.id_for_name is case-insensitive."""
        rec = decks.RECOGNITION_DECKS[0]
        rows = [(1, rec), (2, rec.lower()), (3, f"{decks.NEW_WORDS_DECK}\x1f三体"),
                (4, decks.ARCHIVE_DECK), (5, "Default"), (6, "Nope")]
        got = {name: role for name, role in decks.resolve_rows(rows).values()}
        self.assertEqual(got[rec], decks.RECOGNITION)
        self.assertEqual(got[rec.lower()], decks.RECOGNITION)   # case-insensitive
        self.assertEqual(got[f"{decks.NEW_WORDS_DECK}::三体"],
                         decks.RECOGNITION)                     # \x1f became ::
        self.assertEqual(got[decks.ARCHIVE_DECK], decks.ARCHIVE)
        self.assertEqual(got["Default"], decks.RESERVED)
        self.assertIsNone(got["Nope"], "an undeclared deck must not be given a role")

    def test_the_current_archive_name_wins_over_a_legacy_one(self):
        """decks.archive_ids consults a legacy name only when no deck carries the current
        one, so a new deck someone calls `Hidden` is not mistaken for the archive. Two
        resolvers must not give two answers."""
        both = {n: r for n, r in decks.resolve_rows([(1, "Archive"), (2, "Hidden")]).values()}
        self.assertEqual(both["Archive"], decks.ARCHIVE)
        self.assertIsNone(both["Hidden"])
        legacy_only = {n: r for n, r in decks.resolve_rows([(1, "Hidden")]).values()}
        self.assertEqual(legacy_only["Hidden"], decks.ARCHIVE)

    def test_importing_the_cache_does_not_import_anki(self):
        """Acceptance: a consumer reading cache.db never imports anki. `decks` is
        stdlib-only and this module must stay that way, or every consumer inherits the
        single-open-handle constraint again."""
        out = subprocess.run(
            [sys.executable, "-c",
             "import sys; sys.path.insert(0, '/home/vincent/anki-headless');"
             " import anki_cache;"
             " print([m for m in sys.modules if m == 'anki' or m.startswith('anki.')])"],
            capture_output=True, text=True, check=True)
        self.assertEqual(out.stdout.strip(), "[]", out.stdout)


# ── one build, every constructed state ────────────────────────────────

class BuiltCache(unittest.TestCase):
    """Construct the forbidden states in one copy, build once, assert against it."""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory(prefix="ankicache-")
        cls.path = support.copy_collection(Path(cls._tmp.name) / "collection.anki2")
        cls.cache_path = Path(cls._tmp.name) / "cache.db"
        cls.planted = cls._plant_states()
        cls.meta = anki_cache.build(str(cls.path), str(cls.cache_path))
        cls.con = anki_cache.connect_ro(str(cls.cache_path))

    @classmethod
    def tearDownClass(cls):
        cls.con.close()
        cls._tmp.cleanup()
        support._assert_real_untouched()

    @classmethod
    def _plant_states(cls):
        """States the live collection does not contain, so no test can rely on luck.

        Measured on 2026-08-19: 0 cards with `odid != 0`, 0 cards in queue 3, and 0
        buried cards. Every one of those paths would otherwise go untested.
        """
        con = sqlite3.connect(str(cls.path))
        planted = {}
        # From the registry: this said "HSK", which stopped existing on 2026-09-01 and
        # took the whole fixture with it.
        study = decks.RECOGNITION_DECKS[0]
        hsk = next(i for i, n in con.execute("select id, name from decks") if n == study)
        rows = con.execute(
            "select c.id, n.id, n.flds from cards c join notes n on n.id = c.nid "
            "where c.did = ? and c.ord = 0 and c.queue != -1 limit 8", (hsk,)).fetchall()
        (buried, day_learn, on_loan, marked, htmlish, leech_tagged,
         relearned_long, plain) = rows

        con.execute("update cards set queue = -2 where id = ?", (buried[0],))
        planted["buried"] = anki_cache.canonical(buried[2].split("\x1f")[0])

        con.execute("update cards set queue = 3, type = 3, due = ? where id = ?",
                    (240, day_learn[0]))
        planted["day_learn"] = anki_cache.canonical(day_learn[2].split("\x1f")[0])

        # On loan to a filtered deck: `did` points at a deck that does not exist in the
        # decks table, `odid` holds the real one, and `odue` holds the real due date.
        # ivl is set too: a type=2 card with ivl=0 is not a state Anki produces, and
        # planting one would compare the cache against a card that cannot exist.
        con.execute("update cards set did = ?, odid = ?, odue = ?, due = ?, queue = 2, "
                    "type = 2, ivl = 30 where id = ?", (999_999, hsk, 200, 1, on_loan[0]))
        planted["on_loan"] = anki_cache.canonical(on_loan[2].split("\x1f")[0])

        # A note tagged `rewritten::leech` with NO lapses: the 118 notes jiangchinese's
        # substring match used to serve.
        con.execute("update notes set tags = ' rewritten::leech ' where id = ?",
                    (leech_tagged[1],))
        con.execute("update cards set lapses = 0, ivl = 3, type = 2, queue = 2 where id = ?",
                    (leech_tagged[0],))
        planted["tagged_not_leech"] = anki_cache.canonical(leech_tagged[2].split("\x1f")[0])

        # A real leech: lapsed repeatedly and still on a short interval.
        con.execute("update cards set lapses = 5, ivl = 2, type = 2, queue = 2 where id = ?",
                    (marked[0],))
        planted["real_leech"] = anki_cache.canonical(marked[2].split("\x1f")[0])

        # Lapsed repeatedly but RELEARNED: 60 days is not a leech.
        con.execute("update cards set lapses = 9, ivl = 60, type = 2, queue = 2 where id = ?",
                    (relearned_long[0],))
        planted["relearned"] = anki_cache.canonical(relearned_long[2].split("\x1f")[0])

        # HTML in field 0, as 985 real notes carry.
        fields = htmlish[2].split("\x1f")
        word = anki_cache.canonical(fields[0])
        fields[0] = f'<span id="docs-internal-guid-x">{word}</span>'
        con.execute("update notes set flds = ? where id = ?",
                    ("\x1f".join(fields), htmlish[1]))
        planted["htmlish"] = word

        planted["plain"] = anki_cache.canonical(plain[2].split("\x1f")[0])
        con.commit()
        con.close()
        return planted

    # ── the schema ────────────────────────────────────────────────────

    def test_no_table_carries_an_anki_column(self):
        """Every consumer breakage came from Anki's schema leaking outward. `ord`,
        `queue`, raw `due` and deck ids must not exist here at all.

        flagged.template_ord is the ONE declared exception: /api/flagged publishes an
        `ord` integer as part of a contract older than this cache.
        """
        banned = {"ord", "queue", "due", "did", "odid", "odue", "mid", "nid", "cid",
                  "flags", "usn", "type", "ivl", "sfld", "flds", "csum", "left", "factor"}
        allowed = {("flagged", "template_ord")}
        for (table,) in self.con.execute(
                "select name from sqlite_master where type='table' and name not like 'sqlite_%'"):
            for row in self.con.execute(f"pragma table_info({table})"):
                name = row["name"]
                self.assertNotIn(
                    (name, table), {(c, t) for t, c in allowed} and set(),
                    "unreachable")
                if (table, name) in allowed:
                    continue
                self.assertNotIn(name, banned, f"{table}.{name} is Anki's schema")

    def test_today_matches_ankis_own_day_number(self):
        """col.sched.today is the only trustworthy oracle. The builder has no anki
        library, so this is where the two are compared."""
        from anki.collection import Collection
        col = Collection(str(self.path))
        try:
            self.assertEqual(self.meta["today"], col.sched.today)
        finally:
            col.close()

    def test_card_count_sums_to_the_cards_read(self):
        """The primary key collapses cards, so a row can stand for several. Without
        card_count a deck total taken from `words` would silently undercount."""
        total = self.con.execute("select sum(card_count) from words").fetchone()[0]
        skipped = self.meta["skipped_cards"]
        self.assertEqual(total + skipped, self.meta["card_count"])

    def test_deck_stats_totals_match_a_direct_count(self):
        """deck_stats is keyed by notetype because /api/stats filters on `model`. Summing
        every notetype together inflated the HSK total from 4,343 to 4,859."""
        raw = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True)
        try:
            study = decks.RECOGNITION_DECKS[0]
            hsk = next(i for i, n in raw.execute("select id, name from decks") if n == study)
            cv = next(i for i, n in raw.execute("select id, name from notetypes")
                      if n == anki_cache.VOCAB_NOTETYPE)
            # The HOME deck, the same rule the cache uses: a card on loan to a filtered
            # deck keeps its real deck in `odid`. Counting `did` alone would disagree by
            # exactly the cards currently on loan.
            direct = raw.execute(
                "select count(*) from cards c join notes n on n.id=c.nid "
                "where (case when c.odid != 0 then c.odid else c.did end)=? "
                "and c.ord=0 and n.mid=?", (hsk, cv)).fetchone()[0]
        finally:
            raw.close()
        rec = decks.RECOGNITION_DECKS[0]
        cached = anki_cache.deck_stats(self.con, [rec])[rec]["total"]
        self.assertEqual(cached, direct)

    # ── the constructed states ────────────────────────────────────────

    def _row(self, word, deck=None):
        # The default came from a literal "HSK"; the registry names the deck now.
        deck = deck or decks.RECOGNITION_DECKS[0]
        row = self.con.execute(
            "select * from words where simplified=? and deck=?", (word, deck)).fetchone()
        self.assertIsNotNone(row, f"{word!r} is missing from {deck}")
        return row

    def test_a_buried_card_is_blocked_not_live(self):
        self.assertEqual(self._row(self.planted["buried"])["blocked"], "buried")

    def test_a_day_learn_card_uses_the_day_unit(self):
        """queue 3 holds a DAY NUMBER. Reading it as a timestamp is the 250-days bug."""
        row = self._row(self.planted["day_learn"])
        self.assertEqual(row["overdue_days"], float(self.meta["today"] - 240))

    def test_a_card_on_loan_reports_its_real_due_date(self):
        """`due` was set to 1 -- the filtered deck's ordering -- and `odue` to the real
        day number. Reading `due` would report the card ~245 days overdue."""
        row = self._row(self.planted["on_loan"])
        self.assertEqual(row["overdue_days"], float(self.meta["today"] - 200))
        self.assertNotEqual(row["overdue_days"], float(self.meta["today"] - 1))

    def test_html_in_field_zero_does_not_reach_the_key(self):
        """Field 0 carries markup on 985 notes here. The key column must be canonical.

        `sort_field` mirrors Anki's own `sfld`, which Anki keeps stripped and maintains
        itself -- planting HTML in `flds` deliberately does NOT change it. That column
        exists so /api/stats' words and /api/deck/{name}/words keep publishing the exact
        bytes they publish today.
        """
        row = self._row(self.planted["htmlish"])
        self.assertEqual(row["simplified"], self.planted["htmlish"])
        self.assertNotIn("<", row["simplified"])
        raw = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True)
        try:
            stored = raw.execute(
                "select sfld from notes where flds like ?",
                (f"%docs-internal-guid-x%",)).fetchone()
        finally:
            raw.close()
        self.assertIsNotNone(stored, "the planted note is gone")
        self.assertEqual(row["sort_field"], str(stored[0]))

    # ── the tutor's two rules ─────────────────────────────────────────

    def test_leech_means_lapses_not_a_tag(self):
        """jiangchinese matched `tags like '%leech%'`. On this collection that is 118
        notes, every one of them tagged `rewritten::leech`, while exactly 1 note carries
        Anki's real `leech` tag. The rule is lapses, bounded by interval."""
        leeches = {r["simplified"] for r in anki_cache.leech_words(self.con, 500)}
        self.assertIn(self.planted["real_leech"], leeches)
        self.assertNotIn(self.planted["tagged_not_leech"], leeches,
                         "a rewritten::leech tag with 0 lapses is not a leech")
        self.assertNotIn(self.planted["relearned"], leeches,
                         "9 lapses but a 60-day interval means relearned, not a leech")

    def test_the_tutor_reads_the_recognition_role_only(self):
        """Decision B: HSK, HSK7-9, non-HSK and Mined, written as the role so a rename
        cannot reach this code."""
        for reader in (anki_cache.due_words, anki_cache.leech_words):
            roles = {r["role"] for r in reader(self.con, 500)}
            self.assertLessEqual(roles, {decks.RECOGNITION}, f"{reader.__name__} left its scope")
        decks_seen = {r["deck"] for r in anki_cache.due_words(self.con, 500)}
        self.assertNotIn("Reverse", decks_seen)
        self.assertNotIn("Cloze", decks_seen)
        self.assertNotIn(decks.ARCHIVE_DECK, decks_seen)

    def test_due_words_are_ordered_by_how_overdue_they_are(self):
        """Ordering by raw `due` sorted every review card ahead of every learning card,
        so no learning card could reach a 12-item limit."""
        got = [r["overdue_days"] for r in anki_cache.due_words(self.con, 50)]
        self.assertEqual(got, sorted(got, reverse=True))
        self.assertTrue(all(v is not None for v in got))

    # ── known_words, the dong contract ────────────────────────────────

    def test_known_words_matches_the_old_backfill(self):
        """The migration proof for step 2.

        dong's logic is COPIED here rather than imported: the suite runs from
        freq_data/anki_daily.sh at 12:10 UTC and must not depend on a sibling repo's venv.
        """
        han = re.compile(r"[一-鿿]")
        rank = {"new": 0, "learning": 1, "mature": 2}

        def word(flds):
            f0 = flds.split("\x1f", 1)[0]
            f0 = re.sub(r"\[sound:[^\]]*\]", "", f0)
            f0 = re.sub(r"<[^>]+>", "", f0)
            f0 = htmllib.unescape(f0).strip()
            return f0 if 1 <= len(f0) <= 6 and all(han.match(c) for c in f0) else ""

        src = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True)
        try:
            hidden = {did for did, name in src.execute("select id, name from decks")
                      if decks.is_archive(name)}
            rows = src.execute(
                "select n.flds, c.ivl, c.type, c.queue, c.did, c.odid "
                "from cards c join notes n on n.id=c.nid where c.queue != -1").fetchall()
        finally:
            src.close()
        best = {}
        for flds, ivl, ctype, queue, did, odid in rows:
            if (odid or did) in hidden:
                continue
            w = word(flds)
            if not w:
                continue
            if ivl and ivl >= 21:
                status = "mature"
            elif (ivl and ivl >= 1) or ctype in (1, 3) or queue in (1, 3):
                status = "learning"
            else:
                status = "new"
            if rank[status] > rank.get(best.get(w, "new"), 0):
                best[w] = status
        old = {w: s for w, s in best.items() if s != "new"}

        new = anki_cache.known_words(self.con)
        self.assertEqual(set(new) - set(old), set(), "the cache invented words")
        self.assertEqual(set(old) - set(new), set(), "the cache lost words")

    def test_the_archive_is_never_known(self):
        """The reader marked 313 extra words as known -- 2,960 against 2,647 -- because
        the archive was not excluded."""
        known = anki_cache.known_words(self.con)
        archived_only = self.con.execute(
            "select simplified from words group by simplified "
            "having sum(case when role != ? then 1 else 0 end) = 0 limit 50",
            (decks.ARCHIVE,)).fetchall()
        self.assertTrue(archived_only, "no archive-only words to check against")
        for row in archived_only:
            self.assertNotIn(row["simplified"], known)

    def test_a_blocked_word_is_never_known(self):
        known = anki_cache.known_words(self.con)
        self.assertNotIn(self.planted["buried"], known)

    # ── which row represents a word ───────────────────────────────────

    def test_exactly_one_row_per_word_is_preferred(self):
        rows = self.con.execute(
            "select count(*) c, count(distinct simplified) d from words "
            "where preferred = 1").fetchone()
        distinct = self.con.execute("select count(distinct simplified) from words").fetchone()[0]
        self.assertEqual(rows["c"], rows["d"])
        self.assertEqual(rows["c"], distinct)

    def test_the_preferred_row_prefers_a_live_recognition_card(self):
        """Ranking on interval alone named the archive for ~31,000 words; ranking on
        live-and-not-archived alone named a production deck for 23."""
        rows = self.con.execute(
            "select simplified from words where role = ? and blocked is null "
            "and template_kind = ? limit 200", (decks.RECOGNITION, anki_cache.RECOGNITION))
        for row in rows:
            best = self.con.execute(
                "select role, template_kind, blocked from words "
                "where simplified = ? and preferred = 1", (row["simplified"],)).fetchone()
            self.assertEqual(best["template_kind"], anki_cache.RECOGNITION)
            self.assertIsNone(best["blocked"])
            self.assertNotEqual(best["role"], decks.ARCHIVE)

    # ── the reader's contract ─────────────────────────────────────────

    def test_an_unknown_deck_raises_rather_than_returning_empty(self):
        """Anki reports "missing" and "nothing" identically, and two background jobs plus
        a daily cron ran for months achieving nothing because of it."""
        with self.assertRaises(anki_cache.NotInCache):
            anki_cache.deck_words(self.con, "NoSuchDeck")
        with self.assertRaises(anki_cache.NotInCache):
            anki_cache.deck_stats(self.con, ["NoSuchDeck"])
        self.assertIsInstance(
            anki_cache.deck_words(self.con, decks.RECOGNITION_DECKS[0]), list)

    def test_a_missing_new_per_day_is_null_not_zero(self):
        """The dashboard computes PACE = limit || 0 and divides by max(1, rate), so a 0
        becomes a completion date thousands of days out instead of a visible gap."""
        rec = decks.RECOGNITION_DECKS[0]
        self.assertIsNone(anki_cache.deck_stats(self.con, [rec])[rec]["new_per_day"])

    def test_the_cache_file_is_not_world_readable(self):
        """collection.anki2 is 0600 and this holds the same vocabulary. The umask is 0002
        and the directory is 0775, so a new file would be 0664."""
        self.assertEqual(os.stat(self.cache_path).st_mode & 0o777, 0o600)


# ── rebuilding ────────────────────────────────────────────────────────

class Trigger(support.CollectionTest):
    """The half of the design that removes "someone forgot to invalidate"."""

    def test_a_rebuild_follows_a_write(self):
        """Acceptance: the cache rebuilds when col.mod changes, proven by mutating the
        collection and asserting the cache followed."""
        self.assertIsNotNone(anki_cache.poll(str(self.path), str(self.cache_path)))
        cid = self.col.find_cards(f"deck:{decks.RECOGNITION_DECKS[0]} -is:suspended")[0]
        word = anki_cache.canonical(self.col.get_card(cid).note().fields[0])
        self.col.sched.suspend_cards([cid])
        self.close()

        self.assertIsNotNone(anki_cache.poll(str(self.path), str(self.cache_path)),
                             "poll did not notice a write")
        con = self.cache()
        try:
            row = con.execute("select blocked from words where simplified=? and deck=?",
                              (word, decks.RECOGNITION_DECKS[0])).fetchone()
            self.assertEqual(row["blocked"], "suspended")
            self.assertEqual(anki_cache.read_meta(con)["source_mod"],
                             anki_cache.source_mod(str(self.path)))
        finally:
            con.close()

    def test_no_rebuild_when_nothing_changed(self):
        """generated_at holds; checked_at moves. Freshness is `checked_at`, because a
        cache built six hours ago from an untouched collection is correct."""
        first = self.build_cache()
        time.sleep(1.1)
        self.assertIsNone(anki_cache.poll(str(self.path), str(self.cache_path)))
        con = self.cache()
        try:
            meta = anki_cache.read_meta(con)
        finally:
            con.close()
        self.assertEqual(meta["generated_at"], first["generated_at"])
        self.assertGreater(meta["checked_at"], first["checked_at"])

    def test_mod_is_read_inside_the_same_snapshot_as_the_rows(self):
        """A `mod` read AFTER the rows records a state the cache does not hold, and the
        cache then never catches up: the next poll compares equal and skips.

        The seam commits a write while the build is in flight. With the correct order the
        build's snapshot predates that write, so the recorded mod is the OLD one and the
        next poll rebuilds. With the wrong order it records the NEW mod against old rows.
        """
        before = anki_cache.source_mod(str(self.path))

        def write_midway():
            con = sqlite3.connect(str(self.path))
            try:
                con.execute("update col set mod = mod + 1000")
                con.commit()
            finally:
                con.close()

        meta = self.build_cache(_after_mod_read=write_midway)
        self.assertEqual(meta["source_mod"], before,
                         "the build recorded a mod newer than the rows it read")
        self.assertNotEqual(anki_cache.source_mod(str(self.path)), before)
        self.assertIsNotNone(anki_cache.poll(str(self.path), str(self.cache_path)),
                             "the cache must still know it is behind")

    def test_a_missing_deck_stops_the_cache(self):
        """A rename is a schema change with no migration and no error. Four consumers
        hardcoded a deck name and three broke silently. The build must refuse rather than
        write a short table."""
        did = decks.deck_id_by_name(self.col, decks.RECOGNITION_DECKS[0])
        self.col.decks.rename(self.col.decks.get(did), "Renamed-away")
        self.close()
        with self.assertRaises(decks.DeckMissing):
            self.build_cache()

    def test_a_rebuild_preserves_deck_limits(self):
        """Only the maturity-gate job can read Anki's deck-config protobuf, so a rebuild
        that emptied this table would publish new_per_day as absent for five minutes."""
        self.build_cache()
        rec = decks.RECOGNITION_DECKS[0]
        anki_cache.write_deck_limits({rec: 10}, str(self.cache_path))
        self.build_cache()
        con = self.cache()
        try:
            self.assertEqual(anki_cache.deck_stats(con, [rec])[rec]["new_per_day"], 10)
        finally:
            con.close()

    def test_the_build_cannot_write_to_the_collection(self):
        """Asserting that size and mtime did not move does NOT test this: the collection
        is in WAL mode, so a real write moves neither. Assert the mechanism instead.
        """
        opened = {}
        real_connect = sqlite3.connect

        def spy(target, *a, **kw):
            opened.setdefault("uris", []).append(str(target))
            return real_connect(target, *a, **kw)

        sqlite3.connect = spy
        try:
            self.build_cache()
        finally:
            sqlite3.connect = real_connect

        col_uris = [u for u in opened["uris"] if "collection.anki2" in u]
        self.assertTrue(col_uris)
        for uri in col_uris:
            self.assertIn("mode=ro", uri, "the collection was opened writable")
            self.assertNotIn("immutable", uri, "immutable=1 makes SQLite skip the WAL")

        before = anki_cache.source_mod(str(self.path))
        self.build_cache()
        self.assertEqual(anki_cache.source_mod(str(self.path)), before,
                         "col.mod moved, so something wrote to the collection")

    def test_an_undeclared_deck_is_recorded_rather_than_fatal(self):
        """Raising would let a stray deck synced from a phone take every consumer down.
        Skipping silently would hide it. It is counted and named in meta."""
        self.col.decks.id("Scratch")     # id() CREATES, unlike id_for_name()
        self.close()
        meta = self.build_cache()
        self.assertIn("Scratch", meta["unexpected_decks"])


class Freshness(unittest.TestCase):
    """What a consumer does when the bot is not running.

    Builds ONCE for the class and copies the result per test. These tests are about
    reading a cache in a given state, not about producing one, so a build each would add
    24 seconds for nothing.
    """

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory(prefix="ankifresh-")
        cls.source = support.copy_collection(Path(cls._tmp.name) / "collection.anki2")
        cls.template = Path(cls._tmp.name) / "template.db"
        anki_cache.build(str(cls.source), str(cls.template))

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()
        support._assert_real_untouched()

    def setUp(self):
        self._dir = tempfile.TemporaryDirectory(prefix="ankifresh-t-")
        self.path = self.source
        self.cache_path = Path(self._dir.name) / "cache.db"

    def tearDown(self):
        self._dir.cleanup()

    def build_cache(self, **kw):
        """Copy the prebuilt cache instead of building it again."""
        shutil.copy(self.template, self.cache_path)
        con = anki_cache.connect_ro(str(self.cache_path))
        try:
            return anki_cache.read_meta(con)
        finally:
            con.close()

    def cache(self):
        return anki_cache.connect_ro(str(self.cache_path))

    def test_missing_empty_and_stale_are_three_different_errors(self):
        """SQLite CREATES an empty file on connect, so "absent" and "empty" used to look
        identical -- the exact ambiguity brief constraint 1 forbids."""
        with self.assertRaises(anki_cache.CacheMissing):
            anki_cache.connect_ro(str(self.cache_path))
        sqlite3.connect(str(self.cache_path)).close()          # an empty file
        with self.assertRaises(anki_cache.CacheIncomplete):
            anki_cache.connect_ro(str(self.cache_path))
        os.remove(str(self.cache_path))

        self.build_cache()
        con = self.cache()
        try:
            anki_cache.assert_fresh(con)                       # fresh: no raise
        finally:
            con.close()
        rw = sqlite3.connect(str(self.cache_path))
        rw.execute("update meta set checked_at = checked_at - 5000")
        rw.commit()
        rw.close()
        con = self.cache()
        try:
            with self.assertRaises(anki_cache.CacheStale):
                anki_cache.assert_fresh(con)
        finally:
            con.close()

    def test_a_declared_pause_is_not_staleness(self):
        """freq_data/anki_op.sh stops the bot for the length of a write. Without this,
        any operation over 15 minutes makes every consumer refuse at once."""
        self.build_cache()
        rw = sqlite3.connect(str(self.cache_path))
        rw.execute("update meta set checked_at = checked_at - 5000")
        rw.commit()
        rw.close()
        anki_cache.set_pause(str(self.cache_path), 1800)
        con = self.cache()
        try:
            self.assertTrue(anki_cache.assert_fresh(con)["paused"])
        finally:
            con.close()
        anki_cache.set_pause(str(self.cache_path), None)
        con = self.cache()
        try:
            with self.assertRaises(anki_cache.CacheStale):
                anki_cache.assert_fresh(con)
        finally:
            con.close()

    def test_an_expired_pause_is_staleness_again(self):
        """A script that dies mid-operation must not silence the check forever."""
        self.build_cache()
        rw = sqlite3.connect(str(self.cache_path))
        rw.execute("update meta set checked_at = checked_at - 5000, "
                   "paused_until = ?", (int(time.time()) - 10,))
        rw.commit()
        rw.close()
        con = self.cache()
        try:
            with self.assertRaises(anki_cache.CacheStale):
                anki_cache.assert_fresh(con)
        finally:
            con.close()

    def test_a_schema_change_raises_rather_than_being_read_wrong(self):
        """Old consumer code against a new shape would otherwise read whatever the
        columns now mean."""
        self.build_cache()
        rw = sqlite3.connect(str(self.cache_path))
        rw.execute("update meta set schema_version = schema_version + 1")
        rw.commit()
        rw.close()
        with self.assertRaises(anki_cache.SchemaMismatch):
            anki_cache.connect_ro(str(self.cache_path))


class Wiring(unittest.TestCase):
    """The cache is useless if nothing calls it.

    This project has two recorded cases of a background job that ran for months doing
    nothing: a deck-rename left a query matching zero rows, and nobody noticed because
    the job only logged a non-empty result. Testing the FUNCTION a job calls does not
    prove anything calls it.
    """

    def test_the_refresh_job_is_registered_every_30_seconds(self):
        import bot

        class Recorder:
            def __init__(self):
                self.jobs = []

            def run_repeating(self, callback, interval, first=None, **kw):
                self.jobs.append((callback.__name__, interval, first))

        rec = Recorder()
        bot.register_jobs(rec)
        by_name = {name: (interval, first) for name, interval, first in rec.jobs}
        self.assertIn("refresh_cache", by_name, "nothing refreshes the cache")
        self.assertEqual(by_name["refresh_cache"][0], 30)
        self.assertIn("periodic_sync", by_name, "register_jobs dropped the existing job")
        self.assertEqual(by_name["periodic_sync"][0], 300)

    def test_the_refresh_endpoint_is_routed(self):
        """Acceptance: POST /api/refresh returns the new generated_at."""
        import bot

        routes = {(r.method, r.resource.canonical) for r in bot.create_web_app().router.routes()}
        self.assertIn(("POST", "/api/refresh"), routes)
        # the routes that existed before must survive
        self.assertIn(("GET", "/api/status"), routes)
        self.assertIn(("POST", "/api/sync"), routes)

    def test_the_refresh_handler_returns_the_new_generated_at(self):
        import asyncio

        import bot

        with tempfile.TemporaryDirectory(prefix="ankiwire-") as tmp:
            path = support.copy_collection(Path(tmp) / "collection.anki2")
            cache_path = Path(tmp) / "cache.db"
            saved = (anki_cache.CACHE_PATH, anki_cache.DEFAULT_COLLECTION)
            anki_cache.CACHE_PATH = str(cache_path)
            anki_cache.DEFAULT_COLLECTION = str(path)
            try:
                class Request:
                    pass

                response = asyncio.run(bot.handle_api_refresh(Request()))
                body = json.loads(response.text)
            finally:
                anki_cache.CACHE_PATH, anki_cache.DEFAULT_COLLECTION = saved
        self.assertEqual(response.status, 200)
        self.assertIn("generated_at", body)
        self.assertGreater(body["generated_at"], 0)
        self.assertGreater(body["card_count"], 0)
        support._assert_real_untouched()


if __name__ == "__main__":
    unittest.main()
