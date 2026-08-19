"""The maturity gate: its four invariants, stated as tests.

The gate decides where production (ord 1) and cloze (ord 2) cards live and whether they
are suspended. Its predecessors failed silently for months. Each test here constructs the
state the invariant forbids and checks the gate's answer, rather than checking that a
healthy collection stays healthy — which is what the author kept doing, and why the
defects survived.
"""
import decks
from tests.support import CollectionTest

MATURE = 40      # comfortably above decks/bot MATURE_IVL
IMMATURE = 3


class GateInvariants(CollectionTest):

    # ── helpers ───────────────────────────────────────────────────────
    def _vocab_note_with_production_card(self):
        """A ChineseVocabulary note that has both an ord-0 and an ord-1 card."""
        cv = self.col.models.by_name("ChineseVocabulary")["id"]
        nid = self.col.db.scalar(
            "SELECT c.nid FROM cards c JOIN notes n ON n.id=c.nid "
            "WHERE n.mid=? AND c.ord=1 AND c.nid IN "
            "(SELECT nid FROM cards WHERE ord=0) LIMIT 1", cv)
        self.assertIsNotNone(nid)
        return nid

    def _set(self, card, **fields):
        for k, v in fields.items():
            setattr(card, k, v)
        self.col.update_card(card)

    def _make_mature(self, nid, deck_name="HSK"):
        c0 = self.cards_of(nid)[0]
        self.col.set_deck([c0.id], self.deck(deck_name))
        c0 = self.cards_of(nid)[0]
        self._set(c0, type=2, queue=2, ivl=MATURE, due=self.col.sched.today + 1)
        return c0

    def _make_immature(self, nid, deck_name="HSK"):
        c0 = self.cards_of(nid)[0]
        self.col.set_deck([c0.id], self.deck(deck_name))
        c0 = self.cards_of(nid)[0]
        self._set(c0, type=2, queue=2, ivl=IMMATURE, due=self.col.sched.today + 1)
        return c0

    # ── invariant 1: never in a study deck ────────────────────────────
    def test_a_production_card_in_a_study_deck_is_moved_out(self):
        nid = self._vocab_note_with_production_card()
        self._make_mature(nid)
        c1 = self.cards_of(nid)[1]
        self.col.set_deck([c1.id], self.deck("HSK"))
        bot_gate = bot_reverse(self.col)
        self.assertGreaterEqual(bot_gate["moved"], 1)
        self.assertEqual(self.col.decks.name(self.cards_of(nid)[1].did),
                         decks.name_of(decks.PRODUCTION))

    # ── invariant 2: parked stays parked until the word matures ───────
    def test_a_parked_card_for_an_immature_word_is_left_alone(self):
        nid = self._vocab_note_with_production_card()
        self._make_immature(nid)
        c1 = self.cards_of(nid)[1]
        self.col.set_deck([c1.id], self.deck("Archive"))
        self.col.sched.suspend_cards([c1.id])
        before = (self.cards_of(nid)[1].did, self.cards_of(nid)[1].queue)
        bot_reverse(self.col)
        after = (self.cards_of(nid)[1].did, self.cards_of(nid)[1].queue)
        self.assertEqual(before, after)

    def test_a_parked_card_is_released_when_its_word_matures(self):
        nid = self._vocab_note_with_production_card()
        self._make_mature(nid)
        c1 = self.cards_of(nid)[1]
        self.col.set_deck([c1.id], self.deck("Archive"))
        self.col.sched.suspend_cards([c1.id])
        r = bot_reverse(self.col)
        self.assertGreaterEqual(r["unsuspended"], 1)
        c1 = self.cards_of(nid)[1]
        self.assertEqual(self.col.decks.name(c1.did), decks.name_of(decks.PRODUCTION))
        self.assertNotEqual(c1.queue, -1)

    # ── invariant 3: a filtered deck is untouched ─────────────────────
    def test_a_card_on_loan_to_a_filtered_deck_is_untouched(self):
        """One run emptied a 20-card custom study session before this guard existed."""
        did = self.col.decks.new_filtered("GateProbe")
        d = self.col.decks.get(did)
        d["terms"] = [[f'"deck:{decks.name_of(decks.PRODUCTION)}" is:due', 20, 0]]
        self.col.decks.save(d)
        self.col.sched.rebuild_filtered_deck(did)
        n_before = self.col.db.scalar("SELECT count(*) FROM cards WHERE did=?", did)
        self.assertGreater(n_before, 0, "fixture needs cards in the filtered deck")
        bot_reverse(self.col)
        self.assertEqual(self.col.db.scalar("SELECT count(*) FROM cards WHERE did=?", did),
                         n_before)

    # ── invariant 4: a studied card is never suspended ────────────────
    def test_a_studied_card_is_never_suspended(self):
        """Invariant 4 beats invariant 1. The gate adds practice; it must not remove a
        card that is already mid-schedule."""
        nid = self._vocab_note_with_production_card()
        self._make_immature(nid)                    # word NOT mature -> would suspend
        c1 = self.cards_of(nid)[1]
        self.col.set_deck([c1.id], self.deck(decks.name_of(decks.PRODUCTION)))
        self._set(c1, queue=2, type=2, reps=5, ivl=10, due=self.col.sched.today + 1)
        bot_reverse(self.col)
        self.assertNotEqual(self.cards_of(nid)[1].queue, -1,
                            "a card with reps>0 must not be suspended")

    def test_an_unstudied_card_for_an_immature_word_is_suspended(self):
        nid = self._vocab_note_with_production_card()
        self._make_immature(nid)
        c1 = self.cards_of(nid)[1]
        self.col.set_deck([c1.id], self.deck(decks.name_of(decks.PRODUCTION)))
        self._set(c1, queue=0, type=0, reps=0)
        r = bot_reverse(self.col)
        self.assertGreaterEqual(r["suspended"], 1)
        self.assertEqual(self.cards_of(nid)[1].queue, -1)


class GateConvergence(CollectionTest):

    def test_the_live_collection_is_at_a_fixed_point(self):
        self.assertGateSettled("the collection should already satisfy the gate")

    def test_idempotent_from_a_disturbed_state(self):
        """Run once from a mutated state, then again: the second run must be a no-op."""
        cv = self.col.models.by_name("ChineseVocabulary")["id"]
        nid = self.col.db.scalar(
            "SELECT c.nid FROM cards c JOIN notes n ON n.id=c.nid "
            "WHERE n.mid=? AND c.ord=1 LIMIT 1", cv)
        c1 = self.cards_of(nid)[1]
        self.col.set_deck([c1.id], self.deck("HSK"))          # invariant 1 broken
        first = bot_reverse(self.col)
        self.assertGreaterEqual(first["moved"], 1)
        second = bot_reverse(self.col)
        for k in ("moved", "unsuspended", "suspended"):
            self.assertEqual(second[k], 0, f"second run still wants to {k}")

    def test_the_gate_reports_a_dict_even_when_it_cannot_run(self):
        """It returned None for a missing note type, and the caller's r.get() raised —
        so the SECOND gate never ran that cycle."""
        import bot as B
        r = B._apply_template_gate(self.col, "NoSuchTemplate", decks.PRODUCTION, dry_run=True)
        self.assertIsInstance(r, dict)
        self.assertTrue(r.get("error"))


def bot_reverse(col, dry_run=False):
    import bot
    return bot.apply_reverse_gate(col, dry_run=dry_run)
