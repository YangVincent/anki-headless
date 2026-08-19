#!/usr/bin/env python3
"""Put the archive on the collection's own preset, and rebuild the memory state it cost.

`Archive` was created with col.decks.id(), which binds a NEW deck to Anki's stock preset
(id 1). Its FSRS parameters differ from the preset every other deck uses. Anki DISCARDS a
card's memory state when the card moves to a deck whose parameters differ — so folding the
old Hidden:: subtree into Archive stripped `s`, `d`, `dr` and `decay` from 421 studied
cards. That was not reported at the time.

Two things here:

  1. Move `Archive` onto the same preset as the study decks, so a future move into it
     cannot strip anything again.
  2. Recompute memory state for the cards that lost it. Every one has revlog rows, which
     is what compute_memory_state rebuilds from — the same thing the desktop client's
     "Update memory state" does.

Idempotent. Dry-run unless --apply.
Run via: bash freq_data/anki_op.sh archive-preset freq_data/fix_archive_preset.py --apply
"""
import sys

sys.path.insert(0, "/home/vincent/anki-headless")
import decks                                    # noqa: E402
from tools.collection_op import CollectionOp     # noqa: E402


def target_preset(col):
    """The preset the recognition decks use. Not a literal, and not preset 1."""
    ids = {col.decks.config_dict_for_deck_id(d)["id"]
           for d in decks.deck_ids_for(col, decks.RECOGNITION)}
    if len(ids) > 1:
        # HSK has its own 25/day preset; take the one the majority use.
        counts = {}
        for d in decks.deck_ids_for(col, decks.RECOGNITION):
            k = col.decks.config_dict_for_deck_id(d)["id"]
            counts[k] = counts.get(k, 0) + 1
        return max(counts, key=counts.get)
    return ids.pop()


def missing_memory_state(col):
    """Cards with review history whose FSRS memory state is gone."""
    return col.db.list(
        "SELECT c.id FROM cards c WHERE c.reps > 0 AND c.data NOT LIKE '%\"s\":%' "
        "AND EXISTS (SELECT 1 FROM revlog r WHERE r.cid = c.id)")


with CollectionOp("archive-preset", __doc__) as op:
    col = op.col
    arch = decks.deck_id_by_name(col, decks.ARCHIVE_DECK)
    want = target_preset(col)
    have = col.decks.config_dict_for_deck_id(arch)["id"]
    op.plan(f"move {decks.ARCHIVE_DECK} from preset {have} to {want}", int(have != want))

    stale = missing_memory_state(col)
    op.plan("cards needing their memory state rebuilt", len(stale))

    if op.will_write:
        # ORDER MATTERS. The rebuilt state uses the deck's desired retention, and Archive
        # sits on preset 1 (0.93) rather than the collection's 0.90. Recomputing first
        # would bake in the wrong number.
        if have != want:
            d = col.decks.get(arch)
            d["conf"] = want
            col.decks.save(d)
        from anki.cards_pb2 import FsrsMemoryState
        rebuilt = 0
        for cid in stale:
            ms = col.compute_memory_state(cid)
            if ms.stability <= 0:
                continue
            c = col.get_card(cid)
            c.memory_state = FsrsMemoryState(stability=ms.stability, difficulty=ms.difficulty)
            c.desired_retention = ms.desired_retention
            col.update_card(c)
            rebuilt += 1
        op.plan("memory state rebuilt from revlog", rebuilt)
        op.record("fix_archive_preset", None,
                  {"preset": want, "memory_state_rebuilt": rebuilt})

    op.check("Archive preset matches the study decks",
             col.decks.config_dict_for_deck_id(arch)["id"], want)
    op.check("cards still missing memory state", len(missing_memory_state(col)), 0)
    op.check("Archive still fully suspended",
             col.db.scalar("SELECT count(*) FROM cards WHERE did=? AND queue!=-1", arch), 0)
    op.check("no corrupted schedules",
             col.db.scalar("SELECT count(*) FROM cards WHERE type IN (1,2,3) AND due<0"), 0)
