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


class DuplicateGuards(CollectionTest):
    """The autonomous /api/card path creates notes with no human confirmation, so the
    guard cannot be a prompt instruction."""

    def test_a_word_whose_field_carries_html_is_still_found(self):
        """Anki's field search matches the RAW field. 14 vocabulary notes carry markup in
        `Simplified`, so the search returned 0 hits for a word that exists — and the
        autonomous path reads 0 hits as "create it"."""
        cv = self.col.models.by_name("ChineseVocabulary")["id"]
        row = self.col.db.first(
            "SELECT id, sfld FROM notes WHERE mid=? AND "
            "substr(flds,1,instr(flds,char(31))-1) LIKE '%<%' LIMIT 1", cv)
        self.assertIsNotNone(row, "fixture: expected a note with HTML in Simplified")
        nid, word = row
        r = self.tool_json("search_notes", {"query": f"Simplified:{word}"})
        self.assertGreater(r["count"], 0, f"{word!r} exists as note {nid} but was not found")

    def test_creating_a_word_that_already_exists_is_refused(self):
        out = self.tool_json("add_chinese_vocab", {
            "simplified": "说服", "traditional": "說服", "pinyin": "shuō fú",
            "meaning": "persuade", "part_of_speech": "verb",
            "sentence_simplified": "这是。", "sentence_pinyin": "zhè shì.",
            "sentence_meaning": "This is."})
        self.assertIn("error", out)
        self.assertIn("already has a note", out["error"])
        self.assertIn(1393817667119, out["existing_note_ids"])


class PromotionOwnsNothing(CollectionTest):
    """Suspension has exactly one owner: the maturity gate."""

    def test_promotion_leaves_the_collection_at_the_gate_fixed_point(self):
        """It used to suspend production and cloze cards itself, and the gate re-released
        them within 5 minutes."""
        self.tool("tag_notes", {"query": "nid:1537328242227", "tags": ["mined"]})
        self.assertGateSettled("promotion must leave nothing for the gate to undo")

    def test_a_second_tag_is_not_written_onto_import_pool_notes(self):
        before = set(self.col.get_note(IMPORT_POOL).tags)
        self.tool("tag_notes", {"query": f"nid:{IMPORT_POOL}", "tags": ["mined", "probe"]})
        self.assertEqual(set(self.reopen().get_note(IMPORT_POOL).tags), before)


class CardStandingIsTheOrd0Card(CollectionTest):
    """get_notes_detail returns EVERY card of a note, siblings included.

    A ChineseVocabulary note has three: the recognition card the user studies (ord 0)
    plus a Reverse and a Cloze sibling. The siblings stay new long after ord 0 is in
    rotation -- 401 of the 429 notes reviewed in the 3 days to 2026-08-28 -- so the
    payload sat a seven-digit sibling `queue_position` next to a review card. The bot
    read that number back as the user's standing on a card they were reviewing that day.

    Two things fix it and both are pinned here: `study_state` names the governing card,
    and a new card reports a RANK, because raw `due` is an internal ordering index. This
    collection's counter sits near 1,998,000 (a 212,889-card import was appended at the
    top), so 84% of new cards carry a seven-digit value that is not a queue depth.
    """

    def test_study_state_is_the_ord_0_card_not_a_sibling(self):
        r = self.tool_json("get_notes_detail", {"note_ids": [HSK_REVIEW]})[0]
        ss = r["study_state"]
        self.assertEqual(ss["ord"], 0)
        self.assertEqual(ss["state"], "review")
        self.assertIn("due_in_days", ss)
        # The whole point: the governing card carries no position at all.
        self.assertNotIn("queue_position", ss)
        self.assertNotIn("new_queue_rank", ss)

    def test_the_sibling_that_used_to_be_quoted_is_still_in_card_states(self):
        """If this stops holding, the fixture drifted and the test above proves nothing."""
        r = self.tool_json("get_notes_detail", {"note_ids": [HSK_REVIEW]})[0]
        siblings = [c for c in r["card_states"] if c["ord"] != 0]
        self.assertTrue(any(c.get("queue_position", 0) > 1_000_000 for c in siblings),
                        "fixture: expected a sibling with a seven-digit queue_position")

    def test_a_seven_digit_position_ranks_inside_a_queue_of_a_few_thousand(self):
        """1,992,896 is not a depth. That card is ~1,900th of ~2,000 in Reverse."""
        r = self.tool_json("get_notes_detail", {"note_ids": [HSK_REVIEW]})[0]
        big = next(c for c in r["card_states"] if c.get("queue_position", 0) > 1_000_000)
        self.assertLessEqual(big["new_queue_rank"], big["new_queue_size"])
        self.assertGreaterEqual(big["new_queue_rank"], 1)
        self.assertLess(big["new_queue_size"], 100_000,
                        "the rank must count the real queue, not the suspended archive")

    def test_rank_bounds_are_exact_at_both_ends_of_a_deck_queue(self):
        did = self.deck("HSK")
        first = self.col.db.scalar(
            "SELECT nid FROM cards WHERE did=? AND queue=0 ORDER BY due ASC LIMIT 1", did)
        last = self.col.db.scalar(
            "SELECT nid FROM cards WHERE did=? AND queue=0 ORDER BY due DESC LIMIT 1", did)
        rows = self.tool_json("get_notes_detail", {"note_ids": [first, last]})
        by_nid = {r["note_id"]: r for r in rows}

        def hsk_new(nid):
            return next(c for c in by_nid[nid]["card_states"]
                        if c["deck"] == "HSK" and c["state"] == "new")

        self.assertEqual(hsk_new(first)["new_queue_rank"], 1)
        self.assertEqual(hsk_new(last)["new_queue_rank"], hsk_new(last)["new_queue_size"])

    def test_a_suspended_new_card_gets_no_rank(self):
        """It comes up at no position at all, so a rank would assert a place it lacks."""
        r = self.tool_json("get_notes_detail", {"note_ids": [HSK_NEW]})[0]
        parked = [c for c in r["card_states"] if c["state"] == "suspended"]
        self.assertTrue(parked, "fixture: expected a suspended sibling on this note")
        for c in parked:
            self.assertIn("queue_position", c)
            self.assertNotIn("new_queue_rank", c)
