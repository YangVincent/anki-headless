"""The tool layer the model drives, and the rules that stop it writing to the wrong place.

`execute_tool` is 698 lines holding 24 tools. Nothing exercised it before. Two of its
defects reached production: `add_general_card` filed into `Default` for months while
reporting "Knowledge", and `move_card_type` would CREATE whatever deck name it was given.
"""
import json

import decks
from tests.support import CollectionTest

# A note id is stable. A note's SCHEDULING STATE is not -- the user studies this
# collection every day, so a card moves between new, learning and review under the suite.
# These constants therefore name only what cannot change: which note it is.
#
# `HSK_NOTE = 1393817667119  # 说服 — ord 0 new, in HSK` broke exactly this rule. 说服
# entered review, so the promotion test compared a DAY NUMBER (due=255) against new-card
# queue positions, counted 16 suspended cards as "ahead", and went red with nothing wrong
# in the code. Any test that needs a state must SELECT for that state at run time --
# a_note_with_ord0_in(), or a query in the test -- and never assume an id still holds it.
HSK_NOTE = 1393817667119       # 说服 — a live ChineseVocabulary note, ord-0 card in HSK
IMPORT_POOL = 1707757129855    # a parked xiehanzi import note


class EveryToolRuns(CollectionTest):
    """A compile does not prove a tool runs. Two deleted constants once survived
    py_compile and would have raised NameError at startup."""

    SAFE_ARGS = {
        "search_notes": {"query": "Simplified:说服"},
        "get_notes_detail": {"note_ids": [HSK_NOTE]},
        "get_field_values": {"query": "deck:HSK", "fields": ["Simplified"]},
        "get_collection_stats": {},
        "get_cards_info": {"note_ids": [HSK_NOTE]},
        "lookup_frequency": {"words": ["说服"]},
        "list_decks": {},
        "list_note_types": {},
        "get_note_type_templates": {"note_type": "ChineseVocabulary"},
        "get_vocab_for_story": {"num_known": 20, "num_target": 3},
        "get_grammar_for_story": {},
        "edit_note": {"note_id": HSK_NOTE, "fields": {"Notes": "test"}},
        "tag_notes": {"query": f"nid:{HSK_NOTE}", "tags": ["testtag"]},
        "remove_tags": {"query": f"nid:{HSK_NOTE}", "tags": ["testtag"]},
        "suspend_cards": {"query": f"nid:{HSK_NOTE}"},
        "unsuspend_cards": {"query": f"nid:{HSK_NOTE}"},
        "suspend_card_type": {"query": f"nid:{HSK_NOTE}", "template_name": "Cloze-Recall"},
        "unsuspend_card_type": {"query": f"nid:{HSK_NOTE}", "template_name": "Cloze-Recall"},
        "move_cards": {"query": f"nid:{HSK_NOTE}", "deck": decks.NEW_WORDS_DECK},
        "move_card_type": {"query": f"nid:{HSK_NOTE}", "template_name": "Hanzi-English",
                           "deck": decks.NEW_WORDS_DECK},
        "delete_notes": {"query": "Simplified:说服"},
        "add_general_card": {"front": "q", "back": "a", "deck": decks.NEW_WORDS_DECK},
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
                out = self.tool("move_cards", {"query": f"nid:{HSK_NOTE}", "deck": name})
                self.assertIn("may write to", out, f"{name} must be refused")

    def test_allows_the_recognition_decks(self):
        for name in decks.RECOGNITION_DECKS:
            with self.subTest(deck=name):
                self.assertIn("Moved", self.tool(
                    "move_cards", {"query": f"nid:{HSK_NOTE}", "deck": name}))

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
        nid = self.a_note_with_ord0_in(decks.RECOGNITION_DECKS[0], queue=2)
        before = self.cards_of(nid)[0]
        state = (before.did, before.due, before.ivl, before.type)
        self.tool("tag_notes", {"query": f"nid:{nid}", "tags": ["mined"]})
        after = self.cards_of(nid)[0]
        self.assertEqual((after.did, after.due, after.ivl, after.type), state)

    def test_a_new_card_stays_in_its_study_deck_and_goes_to_the_front(self):
        # Selected now, not pinned to an id: promotion only repositions a NEW card, so a
        # fixture that drifts into review makes this assert a day number against queue
        # positions. `type=0 AND ord=0` mirrors the MIN(due) the promotion itself takes,
        # so "front" means the same thing here and there.
        nid = self.a_note_with_ord0_in(decks.RECOGNITION_DECKS[0], queue=0)
        self.tool("tag_notes", {"query": f"nid:{nid}", "tags": ["mined"]})
        c0 = self.cards_of(nid)[0]
        self.assertEqual(self.col.decks.name(c0.did), decks.RECOGNITION_DECKS[0])
        ahead = self.col.db.scalar(
            "SELECT count(*) FROM cards WHERE did=? AND type=0 AND ord=0 AND due<?",
            self.deck(decks.RECOGNITION_DECKS[0]), c0.due)
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
        c = self.cards_of(self.a_note_with_ord0_in(decks.RECOGNITION_DECKS[0], queue=2))[0]
        with self.assertRaises(ValueError):
            import_bot().set_new_card_position(self.col, c, -5)

    def test_refuses_a_card_on_loan_to_a_filtered_deck(self):
        """Its real position lives in `odue`, so the write is discarded when the session
        ends — while the caller reports "moved to the front"."""
        did = self.col.decks.new_filtered("DueProbe")
        d = self.col.decks.get(did)
        d["terms"] = [[f'"deck:{decks.RECOGNITION_DECKS[0]}" is:new', 5, 0]]
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
        self.assertIn(HSK_NOTE, live)
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
        # Absolute settledness stopped being true on 2026-09-01: merging the recognition
        # decks made mined words a PRODUCTION source, so ~21 mature ones became
        # releasable and bot.GATE_DISABLED is what holds them. That backlog is not
        # promotion's doing, so the invariant is that promotion does not ADD to it.
        def pending():
            return [{k: r[k] for k in ("moved", "unsuspended", "suspended")}
                    for r in self.gate_result(dry_run=True)]
        before = pending()
        self.tool("tag_notes", {"query": "nid:1537328242227", "tags": ["mined"]})
        self.assertEqual(pending(), before,
                         "promotion must leave nothing NEW for the gate to undo")

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

    def a_reviewed_note_with_a_seven_digit_sibling(self):
        """The exact shape that caused the bug: ord 0 in rotation, a sibling still new
        and carrying a seven-digit `due`. Selected at run time -- pinning it to an id
        would encode a scheduling state the user changes by studying."""
        # `s.queue=0` found this shape until 2026-09-01, when every production and cloze
        # card was suspended -- so no sibling is queue=0 any more and the fixture found
        # nothing. The SHAPE still matters: remove a template from bot.GATE_DISABLED and
        # these siblings come back. So it is built here, on the copy, rather than found.
        row = self.col.db.first(
            "SELECT c0.nid, s.id FROM cards c0 JOIN cards s ON s.nid=c0.nid AND s.ord!=0 "
            "WHERE c0.ord=0 AND c0.queue=2 AND s.type=0 AND s.due>1000000 LIMIT 1")
        self.assertIsNotNone(row, "fixture: no reviewed note with a seven-digit sibling")
        self.col.sched.unsuspend_cards([row[1]])
        return row[0]

    def a_note_with_a_suspended_new_sibling(self):
        row = self.col.db.first(
            "SELECT nid FROM cards WHERE ord!=0 AND type=0 AND queue=-1 LIMIT 1")
        self.assertIsNotNone(row, "fixture: no suspended new sibling anywhere")
        return row[0]

    def test_study_state_is_the_ord_0_card_not_a_sibling(self):
        nid = self.a_reviewed_note_with_a_seven_digit_sibling()
        r = self.tool_json("get_notes_detail", {"note_ids": [nid]})[0]
        ss = r["study_state"]
        self.assertEqual(ss["ord"], 0)
        self.assertEqual(ss["state"], "review")
        self.assertIn("due_in_days", ss)
        # The whole point: the governing card carries no position at all.
        self.assertNotIn("queue_position", ss)
        self.assertNotIn("new_queue_rank", ss)

    def test_the_sibling_that_used_to_be_quoted_is_still_in_card_states(self):
        """If this stops holding, the selector is wrong and the test above proves nothing."""
        nid = self.a_reviewed_note_with_a_seven_digit_sibling()
        r = self.tool_json("get_notes_detail", {"note_ids": [nid]})[0]
        siblings = [c for c in r["card_states"] if c["ord"] != 0]
        self.assertTrue(any(c.get("queue_position", 0) > 1_000_000 for c in siblings),
                        "fixture: expected a sibling with a seven-digit queue_position")

    def test_a_seven_digit_position_ranks_inside_a_queue_of_a_few_thousand(self):
        """1,992,896 is not a depth. That card is ~1,900th of ~2,000 in Reverse."""
        nid = self.a_reviewed_note_with_a_seven_digit_sibling()
        r = self.tool_json("get_notes_detail", {"note_ids": [nid]})[0]
        big = next(c for c in r["card_states"] if c.get("queue_position", 0) > 1_000_000)
        self.assertLessEqual(big["new_queue_rank"], big["new_queue_size"])
        self.assertGreaterEqual(big["new_queue_rank"], 1)
        self.assertLess(big["new_queue_size"], 100_000,
                        "the rank must count the real queue, not the suspended archive")

    def test_rank_bounds_are_exact_at_both_ends_of_a_deck_queue(self):
        did = self.deck(decks.RECOGNITION_DECKS[0])
        first = self.col.db.scalar(
            "SELECT nid FROM cards WHERE did=? AND queue=0 ORDER BY due ASC LIMIT 1", did)
        last = self.col.db.scalar(
            "SELECT nid FROM cards WHERE did=? AND queue=0 ORDER BY due DESC LIMIT 1", did)
        rows = self.tool_json("get_notes_detail", {"note_ids": [first, last]})
        by_nid = {r["note_id"]: r for r in rows}

        def hsk_new(nid):
            return next(c for c in by_nid[nid]["card_states"]
                        if c["deck"] == decks.RECOGNITION_DECKS[0] and c["state"] == "new")

        self.assertEqual(hsk_new(first)["new_queue_rank"], 1)
        self.assertEqual(hsk_new(last)["new_queue_rank"], hsk_new(last)["new_queue_size"])

    def test_a_suspended_new_card_gets_no_rank(self):
        """It comes up at no position at all, so a rank would assert a place it lacks."""
        nid = self.a_note_with_a_suspended_new_sibling()
        r = self.tool_json("get_notes_detail", {"note_ids": [nid]})[0]
        parked = [c for c in r["card_states"]
                  if c["state"] == "suspended" and "queue_position" in c]
        self.assertTrue(parked, "fixture: expected a suspended NEW sibling on this note")
        for c in parked:
            self.assertIn("queue_position", c)
            self.assertNotIn("new_queue_rank", c)
