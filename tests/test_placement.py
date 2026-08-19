"""Where a card lands when Anki creates it, and the shape of the collection.

Card placement used to be a repair job: every card a note generated went to the note's
home deck, and something had to move it afterwards. That is where the strays came from —
65 cloze cards appeared in `Default` when a field was backfilled MONTHS after the note
was made, 146 production cards sat inside `HSK`, 132 inside `HSK7-9`.

Anki has a per-template deck override for exactly this. These tests pin it.
"""
import decks
from tests.support import CollectionTest

OVERRIDES = [
    ("ChineseVocabulary", "English-Speaking", decks.PRODUCTION),
    ("ChineseVocabulary", "Cloze-Recall", decks.CLOZE),
    ("ChineseCharacters", "TradRecognition", decks.ARCHIVE),
    ("ChineseSentences", "Listen-English", decks.ARCHIVE),
]


class TemplateOverrides(CollectionTest):

    def test_each_gated_template_declares_its_deck(self):
        for model_name, tmpl_name, role in OVERRIDES:
            with self.subTest(template=f"{model_name}/{tmpl_name}"):
                m = self.col.models.by_name(model_name)
                t = next(t for t in m["tmpls"] if t["name"] == tmpl_name)
                self.assertIsNotNone(t.get("did"), "no deck override")
                self.assertEqual(self.col.decks.name(t["did"]), decks.name_of(role))

    def test_recognition_templates_have_no_override(self):
        """ord 0 must follow its note: a word lives in whichever study deck it belongs
        to, and that varies per note."""
        for model_name in ("ChineseVocabulary", "ChineseCharacters", "ChineseSentences",
                           "ChineseCharactersWriting"):
            m = self.col.models.by_name(model_name)
            if not m:
                continue
            with self.subTest(model=model_name):
                self.assertIsNone(m["tmpls"][0].get("did"))


class NewCardPlacement(CollectionTest):

    def _add(self, word="放置测试", cloze=False):
        args = {"simplified": word, "traditional": word, "pinyin": "fàng zhì cè shì",
                "meaning": "placement test", "part_of_speech": "noun",
                "sentence_simplified": f"这是{word}。", "sentence_pinyin": "zhè shì.",
                "sentence_meaning": "Placement test."}
        return self.tool_json("add_chinese_vocab", args)["note_id"]

    def test_a_new_note_lands_by_role_with_no_sweep(self):
        nid = self._add()
        placed = {o: self.col.decks.name(c.did) for o, c in self.cards_of(nid).items()}
        self.assertEqual(placed[0], decks.NEW_WORDS_DECK)
        self.assertEqual(placed[1], decks.name_of(decks.PRODUCTION))
        self.assertGateSettled("a freshly created note must not need repairing")

    def test_a_cloze_card_generated_later_lands_in_the_cloze_deck(self):
        """THE 65-CARD BUG. The cloze template is conditional on a field. Backfilling
        that field months later makes Anki generate the card THEN — and without an
        override it goes to the note's home deck, which is how 65 of them reached
        `Default` and bypassed the maturity gate entirely."""
        nid = self._add()
        self.assertNotIn(2, self.cards_of(nid), "fixture: no cloze card yet")
        note = self.col.get_note(nid)
        note["SentenceSimplifiedCloze"] = "这是[ ]。"
        self.col.update_note(note)
        cards = self.cards_of(nid)
        self.assertIn(2, cards, "the cloze card should now exist")
        self.assertEqual(self.col.decks.name(cards[2].did), decks.name_of(decks.CLOZE))

    def test_nothing_new_reaches_the_reserved_deck(self):
        before = self.col.db.scalar("SELECT count(*) FROM cards WHERE did=1")
        self._add("放置测试乙")
        self.assertEqual(self.col.db.scalar("SELECT count(*) FROM cards WHERE did=1"), before)


class CollectionShape(CollectionTest):
    """Assertions about the collection itself, which is the thing that cannot be
    rebuilt."""

    def test_the_collection_holds_exactly_the_declared_decks(self):
        names = {d.name for d in self.col.decks.all_names_and_ids()}
        self.assertEqual(names, set(decks.ALL_NAMES))

    def test_the_archive_is_fully_suspended(self):
        live = self.col.db.scalar(
            "SELECT count(*) FROM cards WHERE did=? AND queue!=-1", self.deck("Archive"))
        self.assertEqual(live, 0, "the archive's whole contract is that nothing in it runs")

    def test_no_card_carries_a_corrupted_schedule(self):
        """A queue position written onto a review card turned one due in 9 days into one
        250 days overdue."""
        self.assertEqual(
            self.col.db.scalar("SELECT count(*) FROM cards WHERE type IN (1,2,3) AND due<0"), 0)

    def test_no_orphan_cards(self):
        self.assertEqual(self.col.db.scalar(
            "SELECT count(*) FROM cards WHERE did NOT IN (SELECT id FROM decks)"), 0)

    def test_no_gated_card_sits_in_a_study_deck(self):
        cv = self.col.models.by_name("ChineseVocabulary")["id"]
        study = decks.deck_ids_for(self.col, decks.RECOGNITION)
        ph = ",".join("?" * len(study))
        for ord_ in (1, 2):
            with self.subTest(ord=ord_):
                self.assertEqual(self.col.db.scalar(
                    f"SELECT count(*) FROM cards c JOIN notes n ON n.id=c.nid "
                    f"WHERE c.ord=? AND n.mid=? AND c.did IN ({ph})", ord_, cv, *study), 0)


class ArchiveContract(CollectionTest):
    """The archive's only contract is that nothing in it runs. Nothing enforced it, and
    two paths could break it: a conditional template whose override points at the archive
    (Anki creates that card UNSUSPENDED), and any hand move."""

    def test_a_live_unstudied_card_in_the_archive_is_suspended(self):
        import bot
        cid = self.col.db.scalar(
            "SELECT id FROM cards WHERE did=? AND queue=-1 AND reps=0 LIMIT 1",
            self.deck("Archive"))
        self.col.sched.unsuspend_cards([cid])
        self.assertNotEqual(self.col.get_card(cid).queue, -1)
        r = bot.enforce_archive_suspended(self.col)
        self.assertGreaterEqual(r["suspended"], 1)
        self.assertEqual(self.col.get_card(cid).queue, -1)

    def test_a_studied_card_in_the_archive_is_left_alone_and_reported(self):
        """Taking away something the user has studied is the bigger error."""
        import bot
        cid = self.col.db.scalar(
            "SELECT id FROM cards WHERE did=? AND reps>0 LIMIT 1", self.deck("Archive"))
        self.col.sched.unsuspend_cards([cid])
        r = bot.enforce_archive_suspended(self.col)
        self.assertNotEqual(self.col.get_card(cid).queue, -1)
        self.assertGreaterEqual(r["studied_left_alone"], 1)
