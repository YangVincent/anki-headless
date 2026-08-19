"""The tool layer the model drives, and the rules that stop it writing to the wrong place.

`execute_tool` is 698 lines holding 24 tools. Nothing exercised it before. Two of its
defects reached production: `add_general_card` filed into `Default` for months while
reporting "Knowledge", and `move_card_type` would CREATE whatever deck name it was given.
"""
import json

import decks
from tests.support import CollectionTest

HSK_NEW = 1393817667119        # 说服 — ord 0 new, in HSK
HSK_REVIEW = 1537328242227     # 可乐 — ord 0 in review, in HSK
IMPORT_POOL = 1707757129855    # a parked xiehanzi import note


class EveryToolRuns(CollectionTest):
    """A compile does not prove a tool runs. Two deleted constants once survived
    py_compile and would have raised NameError at startup."""

    SAFE_ARGS = {
        "search_notes": {"query": "Simplified:说服"},
        "get_notes_detail": {"note_ids": [HSK_NEW]},
        "get_field_values": {"query": "deck:HSK", "fields": ["Simplified"]},
        "get_collection_stats": {},
        "get_cards_info": {"note_ids": [HSK_NEW]},
        "lookup_frequency": {"words": ["说服"]},
        "list_decks": {},
        "list_note_types": {},
        "get_note_type_templates": {"note_type": "ChineseVocabulary"},
        "get_vocab_for_story": {"num_known": 20, "num_target": 3},
        "get_grammar_for_story": {},
        "edit_note": {"note_id": HSK_NEW, "fields": {"Notes": "test"}},
        "tag_notes": {"query": f"nid:{HSK_NEW}", "tags": ["testtag"]},
        "remove_tags": {"query": f"nid:{HSK_NEW}", "tags": ["testtag"]},
        "suspend_cards": {"query": f"nid:{HSK_NEW}"},
        "unsuspend_cards": {"query": f"nid:{HSK_NEW}"},
        "suspend_card_type": {"query": f"nid:{HSK_NEW}", "template_name": "Cloze-Recall"},
        "unsuspend_card_type": {"query": f"nid:{HSK_NEW}", "template_name": "Cloze-Recall"},
        "move_cards": {"query": f"nid:{HSK_NEW}", "deck": "Mined"},
        "move_card_type": {"query": f"nid:{HSK_NEW}", "template_name": "Hanzi-English",
                           "deck": "Mined"},
        "delete_notes": {"query": "Simplified:说服"},
        "add_general_card": {"front": "q", "back": "a", "deck": "Mined"},
        "add_chinese_vocab": {"simplified": "测甲", "traditional": "測甲", "pinyin": "cè jiǎ",
                              "meaning": "test", "part_of_speech": "noun",
                              "sentence_simplified": "这是测甲。",
                              "sentence_pinyin": "zhè shì cè jiǎ.",
                              "sentence_meaning": "This is a test."},
    }

    def test_every_declared_tool_executes(self):
        declared = {t["name"] for t in import_bot().TOOLS} - {"sync_collection"}   # no network
        missing = declared - set(self.SAFE_ARGS)
        self.assertFalse(missing, f"no safe arguments defined for: {sorted(missing)}")
        for name in sorted(declared):
            with self.subTest(tool=name):
                out = self.tool(name, self.SAFE_ARGS[name])
                self.assertIsInstance(out, str)
                self.assertNotIn("Traceback", out)


class WriteAllowlist(CollectionTest):

    def test_refuses_the_gate_owned_and_reserved_decks(self):
        for name in (decks.name_of(decks.PRODUCTION), decks.name_of(decks.CLOZE),
                     decks.ARCHIVE_DECK, "Default"):
            with self.subTest(deck=name):
                out = self.tool("move_cards", {"query": f"nid:{HSK_NEW}", "deck": name})
                self.assertIn("may write to", out, f"{name} must be refused")

    def test_allows_the_recognition_decks(self):
        for name in decks.RECOGNITION_DECKS:
            with self.subTest(deck=name):
                self.assertIn("Moved", self.tool(
                    "move_cards", {"query": f"nid:{HSK_NEW}", "deck": name}))

    def test_refuses_a_deck_that_does_not_exist(self):
        out = self.tool_json(
            "add_general_card", {"front": "q", "back": "a", "deck": "Knowledge"})
        self.assertIn("error", out)
        self.assertIsNone(self.col.decks.id_for_name("Knowledge"),
                          "a refused write must not have created the deck")


class Promotion(CollectionTest):

    def test_a_review_card_keeps_its_deck_and_its_schedule(self):
        """It used to write a queue position onto `due`, turning a card due in 9 days
        into one 250 days overdue, and pull it out of HSK."""
        before = self.cards_of(HSK_REVIEW)[0]
        state = (before.did, before.due, before.ivl, before.type)
        self.tool("tag_notes", {"query": f"nid:{HSK_REVIEW}", "tags": ["mined"]})
        after = self.cards_of(HSK_REVIEW)[0]
        self.assertEqual((after.did, after.due, after.ivl, after.type), state)

    def test_a_new_card_stays_in_its_study_deck_and_goes_to_the_front(self):
        self.tool("tag_notes", {"query": f"nid:{HSK_NEW}", "tags": ["mined"]})
        c0 = self.cards_of(HSK_NEW)[0]
        self.assertEqual(self.col.decks.name(c0.did), "HSK")
        ahead = self.col.db.scalar(
            "SELECT count(*) FROM cards WHERE did=? AND type=0 AND ord=0 AND due<?",
            self.deck("HSK"), c0.due)
        self.assertEqual(ahead, 0, "it should be first among HSK's new cards")

    def test_the_import_pool_is_skipped(self):
        """These are parked import artefacts, not the user's cards."""
        before = self.col.decks.name(self.cards_of(IMPORT_POOL)[0].did)
        out = self.tool("tag_notes", {"query": f"nid:{IMPORT_POOL}", "tags": ["mined"]})
        self.assertEqual(self.col.decks.name(self.cards_of(IMPORT_POOL)[0].did), before)
        self.assertIn("import-pool", out)


class DueSemantics(CollectionTest):
    """`due` is a queue POSITION on a new card, a DAY NUMBER on a review card, and a
    UNIX TIMESTAMP on an intraday learning card. Mixing them cost a real schedule."""

    def test_refuses_to_write_a_position_onto_a_review_card(self):
        c = self.cards_of(HSK_REVIEW)[0]
        with self.assertRaises(ValueError):
            import_bot().set_new_card_position(self.col, c, -5)

    def test_refuses_a_card_on_loan_to_a_filtered_deck(self):
        """Its real position lives in `odue`, so the write is discarded when the session
        ends — while the caller reports "moved to the front"."""
        did = self.col.decks.new_filtered("DueProbe")
        d = self.col.decks.get(did)
        d["terms"] = [['"deck:HSK" is:new', 5, 0]]
        self.col.decks.save(d)
        self.col.sched.rebuild_filtered_deck(did)
        cid = self.col.db.scalar("SELECT id FROM cards WHERE did=? LIMIT 1", did)
        self.assertIsNotNone(cid, "fixture needs a card on loan")
        with self.assertRaises(ValueError):
            import_bot().set_new_card_position(self.col, self.col.get_card(cid), 1)


class ArchiveGuards(CollectionTest):

    def test_delete_notes_refuses_archived_notes(self):
        out = self.tool_json("delete_notes", {"query": "Simplified:说服"})
        self.assertEqual(out.get("error"), "refused")
        self.assertTrue(self.col.get_note(IMPORT_POOL), "nothing may be deleted")

    def test_search_splits_hits_into_three_disjoint_sets(self):
        """An archived note is the user's own backlog and must be PROMOTED. An
        import-pool note is an artefact and must be IGNORED. Conflating them made the
        autonomous path create duplicates."""
        r = self.tool_json("search_notes", {"query": "Simplified:说服"})
        live, arch, pool = (set(r["live_note_ids"]), set(r["archived_note_ids"]),
                            set(r["import_pool_note_ids"]))
        self.assertEqual(len(live | arch | pool), r["count"])
        self.assertFalse(live & arch or live & pool or arch & pool)
        self.assertIn(HSK_NEW, live)
        self.assertIn(IMPORT_POOL, pool)

    def test_story_targets_never_include_a_known_word(self):
        """The target set once CONTAINED all 790 known words."""
        r = self.tool_json(
            "get_vocab_for_story", {"num_known": 60, "num_target": 6})
        known = {w["simplified"] for w in r["known_words"]}
        target = {w["simplified"] for w in r["target_words"]}
        self.assertFalse(known & target)
        self.assertTrue(target)


def import_bot():
    import bot
    return bot
