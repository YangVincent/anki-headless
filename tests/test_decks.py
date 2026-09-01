"""decks.py — the deck list, and resolving a ROLE to deck IDs.

Every test here corresponds to a defect that reached the live system. The names say
which. If a test passes on code that has the defect, the test is wrong.
"""
import unittest

import decks
from tests.support import CollectionTest


class RoleResolution(CollectionTest):

    def test_recognition_role_returns_every_declared_deck(self):
        ids = decks.deck_ids_for(self.col, decks.RECOGNITION)
        names = {self.col.decks.name(i) for i in ids}
        self.assertEqual(names, set(decks.RECOGNITION_DECKS))

    def test_subtrees_are_included(self):
        """`Mined` alone excluded Mined::三体 from the maturity query, so its cloze cards
        could never be released."""
        probe = f"{decks.NEW_WORDS_DECK}::probe"
        self.col.decks.id(probe)
        ids = decks.deck_ids_for(self.col, decks.RECOGNITION)
        self.assertIn(self.col.decks.id_for_name(probe), ids)

    def test_a_sibling_sharing_a_prefix_is_not_a_subtree(self):
        """`HSK` and `HSK7-9` were siblings, and a prefix test without the `::`
        separator merged two curricula. Both decks are gone -- they became `Main` on
        2026-09-01 -- so the invariant is tested on probe decks instead. Testing it on
        whatever decks happen to exist is what let it go untested the moment they were
        renamed.
        """
        self.col.decks.id("ZProbe")
        self.col.decks.id("ZProbe-sibling")
        self.col.decks.id("ZProbe::child")
        ids = decks._subtree_ids(self.col, "ZProbe")
        self.assertIn(self.col.decks.id_for_name("ZProbe::child"), ids)
        self.assertNotIn(self.col.decks.id_for_name("ZProbe-sibling"), ids)

    def test_case_insensitive_like_anki(self):
        """id_for_name is case-insensitive; a plain `==` disagreed with it, so the health
        check called the collection healthy while the gate refused to run."""
        name = decks.RECOGNITION_DECKS[0]
        self.assertEqual(decks._subtree_ids(self.col, name.lower()),
                         decks._subtree_ids(self.col, name))
        self.assertTrue(decks._subtree_ids(self.col, name.lower()))

    def test_a_missing_source_deck_raises_rather_than_shortening_the_list(self):
        """A silently short list let the gate act on half the data and suspend 83
        already-released cards."""
        d = self.col.decks.get(self.deck(decks.RECOGNITION_DECKS[0]))
        self.col.decks.rename(d, "Renamed Away")
        with self.assertRaises(decks.DeckMissing):
            decks.deck_ids_for(self.col, decks.RECOGNITION)
        with self.assertRaises(decks.DeckMissing):
            decks.gate_source_ids(self.col, decks.PRODUCTION)

    def test_deck_id_by_name_raises_for_a_dead_name(self):
        """col.decks.id_for_name returns None and col.decks.id() CREATES. Both silent."""
        with self.assertRaises(decks.DeckMissing):
            decks.deck_id_by_name(self.col, "Vocab")
        self.assertIsNone(self.col.decks.id_for_name("Vocab"),
                          "the lookup must not have created it")


class ArchiveResolution(CollectionTest):

    def test_archive_ids_raises_when_the_archive_is_missing(self):
        """It returned an empty set. The gate read that as "nothing is parked" and one
        run moved the whole 42,524-card archive into the study decks."""
        d = self.col.decks.get(self.deck("Archive"))
        self.col.decks.rename(d, "Parked")
        with self.assertRaises(decks.DeckMissing):
            decks.archive_ids(self.col)

    def test_a_missing_archive_stops_the_gate_instead_of_emptying_it(self):
        before = self.col.db.scalar(
            "SELECT count(*) FROM cards WHERE did=?", self.deck("Archive"))
        self.assertGreater(before, 100000)
        d = self.col.decks.get(self.deck("Archive"))
        self.col.decks.rename(d, "Parked")
        rev, clz = self.gate_result(dry_run=True)
        for r in (rev, clz):
            self.assertTrue(r.get("error"), "the gate must refuse, not proceed")
            self.assertEqual(r["moved"], 0)

    def test_the_archive_is_a_required_deck(self):
        """It was exempt, so startup reported "all required decks resolve" while the one
        deck whose absence causes a destructive write was gone."""
        self.assertIn("Archive", decks.REQUIRED_DECKS)
        d = self.col.decks.get(self.deck("Archive"))
        self.col.decks.rename(d, "Parked")
        self.assertIn("Archive", bot_missing(self.col))

    def test_the_current_name_beats_the_legacy_one(self):
        """`Hidden` is kept for reading old backups. A NEW deck someone calls `Hidden`
        must not be mistaken for the archive."""
        stray = self.col.decks.id("Hidden")
        self.assertNotIn(stray, decks.archive_ids(self.col))

    def test_the_legacy_name_still_works_when_the_current_one_is_absent(self):
        """That is the whole point of legacy_names: a pre-migration backup."""
        d = self.col.decks.get(self.deck("Archive"))
        self.col.decks.rename(d, "Hidden")
        self.assertEqual(decks.archive_ids(self.col), {self.col.decks.id_for_name("Hidden")})


class Declaration(unittest.TestCase):
    """Static checks. No collection needed."""

    def test_exactly_one_deck_per_single_deck_role(self):
        for role in (decks.PRODUCTION, decks.CLOZE, decks.ARCHIVE):
            self.assertEqual(len(decks._named(role)), 1, f"role {role!r}")

    def test_exactly_one_new_words_deck(self):
        """Two would silently pick the first; none raised a bare StopIteration."""
        self.assertEqual(len([d for d in decks.DECKS if d.new_words]), 1)

    def test_the_gate_owned_decks_are_not_writable(self):
        """A card moved into Reverse or Cloze by hand is ungated; one moved into Archive
        stays unsuspended, breaking that deck's only contract."""
        for name in (decks.PRODUCTION_DECK, decks.CLOZE_DECK, decks.ARCHIVE_DECK, "Default"):
            self.assertNotIn(name, decks.WRITABLE_DECKS)
        self.assertEqual(set(decks.WRITABLE_DECKS), set(decks.RECOGNITION_DECKS))

    def test_every_gate_has_at_least_one_source(self):
        """Zero sources makes `mature` empty, and the gate suspends every released card
        reporting success."""
        for gate in (decks.PRODUCTION, decks.CLOZE):
            self.assertTrue(decks.gate_sources(gate), f"no source declares {gate!r}")


def bot_missing(col):
    import bot
    return bot.missing_decks(col)


class DeckDriftIsNoticed(CollectionTest):
    """The deck check ran only at startup, so a rename in the desktop client was invisible
    until someone restarted the bot."""

    def test_a_rename_is_reported_on_the_next_cycle(self):
        import bot
        bot._last_deck_state = None
        self.assertIsNone(bot._check_decks(self.col), "a healthy collection says nothing")
        gone = decks.RECOGNITION_DECKS[0]
        self.col.decks.rename(self.col.decks.get(self.deck(gone)), "Renamed Away")
        msg = bot._check_decks(self.col)
        self.assertIn("MISSING", msg)
        self.assertIn(gone, msg)

    def test_the_same_problem_is_not_repeated_every_cycle(self):
        import bot
        bot._last_deck_state = None
        bot._check_decks(self.col)
        self.col.decks.id("Stray")
        self.assertIn("UNEXPECTED", bot._check_decks(self.col))
        self.assertIsNone(bot._check_decks(self.col), "an unchanged state must stay quiet")
