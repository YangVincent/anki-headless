#!/usr/bin/env python3
"""Telegram bot that uses Claude to create Anki cards via a conversational loop."""

import asyncio
import base64
import collections
import json
import sqlite3
import logging
import os
import random
import re
import signal
import subprocess
import time
import unicodedata
import uuid
from datetime import datetime
from pathlib import Path

from aiohttp import web

import anthropic
import httpx
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

# ── Config ────────────────────────────────────────────────────────────

CONFIG_FILE = "/home/vincent/anki-headless/.bot_config.json"
COLLECTION_PATH = "/home/vincent/anki-headless/collection.anki2"
AUTH_FILE = os.path.expanduser("~/.anki_auth")

DEFAULT_DECK = "Knowledge::Languages::Chinese::Vocabulary"
CHINESE_VOCAB_NOTETYPE = "ChineseVocabulary"
SNAPSHOTS_DIR = Path("/home/vincent/anki-headless/json_snapshots")
# Derived from COLLECTION_PATH at call time, not pinned. A test that redirects
# COLLECTION_PATH to a copy must not append false records to the real changelog --
# twelve such lines were written and removed on 2026-08-19.
CHANGELOG_FILE = Path("/home/vincent/anki-headless/changelog.jsonl")


def _changelog_path():
    """Sit beside whichever collection is open."""
    return Path(COLLECTION_PATH).with_name(CHANGELOG_FILE.name)
ANALYZE_SCRIPT = "/home/vincent/anki-headless/analyze_json.py"
CHINESE_VOCAB_FIELDS = ["Simplified", "Pinyin", "Meaning", "Traditional", "Notes",
                        "Audio", "Strokes", "ColorPinyin", "Frequency", "CustomFreq",
                        "PartOfSpeech", "Homophone", "SentenceSimplified",
                        "SentenceTraditional", "SentenceSimplifiedCloze",
                        "SentenceTraditionalCloze", "SentencePinyin",
                        "SentenceMeaning", "SentenceAudio"]

logging.basicConfig(format="%(asctime)s [%(levelname)s] %(message)s", level=logging.INFO)
log = logging.getLogger(__name__)


def log_change(action, note_ids=None, details=None):
    """Append an entry to the changelog."""
    entry = {
        "ts": datetime.now().isoformat(),
        "action": action,
    }
    if note_ids:
        entry["note_ids"] = note_ids if len(note_ids) <= 20 else note_ids[:20] + [f"...+{len(note_ids)-20}"]
        entry["count"] = len(note_ids)
    if details:
        entry.update(details)
    with open(_changelog_path(), "a") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def load_config():
    if not os.path.exists(CONFIG_FILE):
        raise SystemExit(
            f"Config not found: {CONFIG_FILE}\n"
            "Create it with:\n"
            '  {"telegram_bot_token": "...", "anthropic_api_key": "...", '
            f'"default_deck": "{DEFAULT_DECK}"}}'
        )
    with open(CONFIG_FILE) as f:
        return json.load(f)


CONFIG = load_config()
TELEGRAM_TOKEN = CONFIG["telegram_bot_token"]
ANTHROPIC_KEY = CONFIG["anthropic_api_key"]
DEFAULT_DECK = CONFIG.get("default_deck", DEFAULT_DECK)
API_KEY = (CONFIG.get("api_key") or "").strip()
API_PORT = CONFIG.get("api_port", 8103)

claude = anthropic.Anthropic(api_key=ANTHROPIC_KEY)


# ── Anki helpers ──────────────────────────────────────────────────────

def open_collection():
    from anki.collection import Collection
    return Collection(COLLECTION_PATH)


def load_anki_auth():
    if not os.path.exists(AUTH_FILE):
        return None
    with open(AUTH_FILE) as f:
        data = json.load(f)
    from anki.sync import SyncAuth
    auth = SyncAuth()
    auth.hkey = data["hkey"]
    if data.get("endpoint"):
        auth.endpoint = data["endpoint"]
    return auth


def save_anki_auth(hkey, endpoint):
    data = {"hkey": hkey, "endpoint": endpoint or ""}
    with open(AUTH_FILE, "w") as f:
        json.dump(data, f)
    os.chmod(AUTH_FILE, 0o600)


def _sync_collection():
    """Sync to AnkiWeb. Returns status message."""
    auth = load_anki_auth()
    if auth is None:
        return "Sync skipped (not logged in to AnkiWeb)"

    # open_collection() INSIDE the try. Anki takes an exclusive lock, so any concurrent
    # reader raises DBError("Anki already open"). With the open outside, that escaped
    # _sync_collection, aborted periodic_sync before either gate ran, and the scheduler
    # still logged "executed successfully". Observed twice on 2026-08-19 at 03:55 and 04:00.
    col = None
    try:
        col = open_collection()
        result = col.sync_collection(auth, sync_media=False)
        if result.new_endpoint:
            auth.endpoint = result.new_endpoint
            save_anki_auth(auth.hkey, auth.endpoint)

        NO_CHANGES = 0
        NORMAL_SYNC = 1
        FULL_SYNC = 2

        if result.required == NO_CHANGES:
            return "Synced (no changes needed)"
        elif result.required == NORMAL_SYNC:
            return "Synced"
        elif result.required == FULL_SYNC:
            return "Full sync required — resolve manually with anki-cli sync"
        else:
            return f"Synced (status: {result.required})"
    except Exception as e:
        return f"Sync failed: {e}"
    finally:
        if col is not None:
            col.close()


def strip_html(text):
    return re.sub(r"<[^>]+>", "", text)


async def send_long_message(message, text, parse_mode=None):
    """Split text into <=4096-char chunks at line boundaries and send each."""
    MAX = 4096
    if parse_mode and "```" in text:
        MAX = 4080
    while text:
        if len(text) <= MAX:
            await message.reply_text(text, parse_mode=parse_mode)
            break
        cut = text.rfind("\n", 0, MAX)
        if cut <= 0:
            cut = MAX
        chunk = text[:cut]
        text = text[cut:].lstrip("\n")
        await message.reply_text(chunk, parse_mode=parse_mode)


def has_cjk(text):
    """Check if text contains CJK characters."""
    return any(unicodedata.category(ch).startswith("Lo") and
               "\u4e00" <= ch <= "\u9fff" or "\u3400" <= ch <= "\u4dbf"
               for ch in text)


# Two sibling templates are gated on the same rule: you should not drill a word in a
# harder direction before you can recognise it. ord 1 `English-Speaking` asks you to say
# the word in Mandarin; ord 2 `Cloze-Recall` asks you to fill it into a sentence. Both
# stay suspended in their own deck until the word's ord 0 card matures.
# ── Deck and scheduling API ───────────────────────────────────────────
# Every silent-no-op bug in this file came from one of two Anki calls:
#   col.decks.id_for_name(name)  -> returns None for a missing deck
#   col.decks.id(name)           -> CREATES the missing deck, on preset 1
# One letter apart, opposite failure modes, neither raising. Callers carried the None
# onward: col.add_note(note, None) files into Default, col.set_deck(ids, None) reports
# "your database appears to be in an inconsistent state", and the search string
# `deck:hanly-reverse` matched nothing for months while looking healthy.
#
# Nothing below returns None. A missing deck raises, and startup refuses to run a
# half-configured bot. Rename a deck and you get a loud failure, not a quiet no-op.

class DeckMissing(RuntimeError):
    """A deck this code depends on does not exist."""


# Decks the bot cannot work without. Checked once at startup.
REQUIRED_DECKS = ("HSK", "HSK7-9", "non-HSK", "Mined", "Reverse", "Vocab Cloze")


def deck_id(col, name):
    """Deck id for `name`, or raise DeckMissing. Never returns None, never creates."""
    did = col.decks.id_for_name(name)
    if did is None:
        raise DeckMissing(f"no deck named {name!r}")
    return did


def deck_subtree_ids(col, name):
    """Deck ids for `name` AND its subdecks, or raise DeckMissing.

    id_for_name resolves the parent alone, so a `did IN (...)` query against `Mined`
    silently excluded Mined::三体 and Mined::十日终焉.
    """
    ids = [d.id for d in col.decks.all_names_and_ids()
           if d.name == name or d.name.startswith(name + "::")]
    if not ids:
        raise DeckMissing(f"no deck named {name!r}")
    return ids


def missing_decks(col, names=REQUIRED_DECKS):
    """Names that do not resolve. Empty list means every required deck exists."""
    return [n for n in names if col.decks.id_for_name(n) is None]


# `cards.due` holds three different units, and nothing in Anki's API stops you mixing
# them. This is the second cause of real damage in this file.
DUE_POSITION = "queue_position"   # type 0 (new): an ordering index
DUE_DAY = "day_number"            # queue 2 / 3: days since collection creation
DUE_TIMESTAMP = "unix_timestamp"  # queue 1: intraday learning, seconds


def due_unit(card):
    """Which unit this card's `due` is in. A card inside a filtered deck keeps its real
    value in `odue`, so read that instead of `due` when odid is set."""
    if card.type == 0:
        return DUE_POSITION
    if card.queue in (2, 3):
        return DUE_DAY
    if card.queue == 1:
        return DUE_TIMESTAMP
    return None


def set_new_card_position(col, card, position):
    """Write a queue position. Refuses any card that is not new.

    This is the ONLY place `due` is written. Writing a negative position onto a review
    card turned a card due in 9 days into one 250 days overdue, because on a review card
    `due` is a day number.
    """
    if card.type != 0:
        raise ValueError(
            f"card {card.id} is type {card.type}: its `due` is a {due_unit(card)}, "
            "not a queue position")
    card.due = position
    col.update_card(card)


REVERSE_DECK = "Reverse"
REVERSE_TEMPLATE = "English-Speaking"
REVERSE_SOURCE_DECKS = ("HSK", "HSK7-9", "non-HSK")

CLOZE_DECK = "Vocab Cloze"
CLOZE_TEMPLATE = "Cloze-Recall"
# Mined is included here and not in REVERSE_SOURCE_DECKS on purpose: the old cloze gate
# counted mined reading-words, and the reverse gate's source list was chosen separately.
CLOZE_SOURCE_DECKS = ("HSK", "HSK7-9", "non-HSK", "Mined")

MATURE_IVL = 21


def _apply_template_gate(col, template, home_deck, source_decks, dry_run=False):
    """Keep one ChineseVocabulary template's cards out of the study decks, and suspended
    until their word is known.

    Four invariants:
      1. A gated card never sits in a study deck other than `home_deck`.
      2. A card parked under Hidden:: stays there until its word matures. Only a release
         moves it out, so the backlog leaves one card at a time, not in one bulk write.
         Cards already in `home_deck` stay in `home_deck`, suspended -- most of the deck
         is exactly that (5,364 in Reverse, 15,533 in Vocab Cloze), which is why this
         says "stays parked", not "stays under Hidden::".
      3. A card in a filtered deck is left completely alone until the session ends.
      4. A card with reps > 0 is never suspended. The gate adds practice; it must not
         take away a card that is already mid-schedule. Invariant 4 beats invariant 1.

    "Mature" means the note's ord 0 card is in a source deck, unsuspended, type=2, with
    interval >= MATURE_IVL.

    Both callers of this had the same defect. The reverse job searched
    `deck:hanly-reverse` after that deck was renamed `Hidden::hanly-reverse`, and
    the old freq_data/cloze_gate.py read a deck named `Vocab` that no longer existed.
    Each matched almost nothing and ran for months doing nothing, while cards leaked into
    the study decks behind them. Both scripts are gone; freq_data/template_gate.py calls
    this. Naming the decks in one place is what stops that repeating.
    """
    cv = col.models.by_name(CHINESE_VOCAB_NOTETYPE)
    if not cv:
        return None
    ord_ = next((t["ord"] for t in cv["tmpls"] if t["name"] == template), None)
    home_did = col.decks.id_for_name(home_deck)

    # Each source deck INCLUDING its subdecks. id_for_name resolves the parent only, and
    # the maturity query matches deck ids exactly, so Mined::三体 and Mined::十日终焉 could
    # never contribute maturity and their cloze cards would have stuck forever.
    src, missing = [], []
    for name in source_decks:
        try:
            src.extend(deck_subtree_ids(col, name))
        except DeckMissing:
            missing.append(name)
    if ord_ is None:
        missing.append(f"template {template!r}")
    if home_did is None:
        missing.append(f"deck {home_deck!r}")
    if missing:
        # ALL source decks, or the gate does not run. Dropping a renamed deck silently
        # left a partial maturity set, and the next run suspended 83 already-released
        # cards with no error -- worse than the do-nothing failure this replaced.
        return {"template": template, "deck": home_deck,
                "error": "missing " + ", ".join(missing),
                "mature_words": 0, "moved": 0, "unsuspended": 0, "suspended": 0}

    ph = ",".join("?" * len(src))
    hidden = _hidden_deck_ids(col)
    mature = set(col.db.list(
        f"SELECT nid FROM cards WHERE (CASE WHEN odid!=0 THEN odid ELSE did END) "
        f"IN ({ph}) AND ord=0 AND type=2 AND ivl>=? AND queue!=-1", *src, MATURE_IVL))

    to_move, to_unsuspend, to_suspend = [], [], []
    for cid, did, odid, queue, reps, nid in col.db.all(
            "SELECT c.id, c.did, c.odid, c.queue, c.reps, c.nid FROM cards c "
            "JOIN notes n ON n.id=c.nid WHERE c.ord=? AND n.mid=?", ord_, cv["id"]):
        if odid:
            # Borrowed by a filtered deck. `did` is the filtered deck, and set_deck would
            # tear the card out of the session -- one run emptied a 20-card custom study
            # deck. Leave it; the session returns it to odid on its own.
            continue
        releasing = nid in mature and queue == -1
        # A parked card moves ONLY on release. The old `or queue != -1` disjunct dragged
        # an unsuspended card out of Hidden:: into the study deck even when its word was
        # nowhere near mature -- and with reps > 0 it landed live and due.
        if did != home_did and (releasing or did not in hidden):
            to_move.append(cid)
        if releasing:
            to_unsuspend.append(cid)
        elif nid not in mature and queue != -1 and reps == 0:
            to_suspend.append(cid)

    if not dry_run:
        if to_move:
            col.set_deck(to_move, home_did)
        if to_unsuspend:
            col.sched.unsuspend_cards(to_unsuspend)
        if to_suspend:
            col.sched.suspend_cards(to_suspend)
    return {"template": template, "deck": home_deck, "mature_words": len(mature),
            "moved": len(to_move), "unsuspended": len(to_unsuspend),
            "suspended": len(to_suspend)}


def apply_reverse_gate(col, dry_run=False):
    """Production cards (`English-Speaking`) -> the `Reverse` deck. See _apply_template_gate."""
    return _apply_template_gate(col, REVERSE_TEMPLATE, REVERSE_DECK,
                                REVERSE_SOURCE_DECKS, dry_run)


def apply_cloze_gate(col, dry_run=False):
    """Cloze cards (`Cloze-Recall`) -> the `Vocab Cloze` deck. See _apply_template_gate."""
    return _apply_template_gate(col, CLOZE_TEMPLATE, CLOZE_DECK,
                                CLOZE_SOURCE_DECKS, dry_run)


def promote_to_hanly(col, note_ids):
    """Tag notes with 'hanly', unsuspend forward cards, suspend reverse cards,
    and move to hanly/hanly-reverse decks. Returns (tagged_count, unsuspended_count)."""
    hanly_did = col.decks.id_for_name("hanly")
    hanly_rev_did = col.decks.id_for_name("hanly-reverse")
    tagged = 0
    forward_to_unsuspend = []
    reverse_to_suspend = []
    forward_cards = []
    reverse_cards = []

    for nid in note_ids:
        try:
            note = col.get_note(nid)
        except Exception:
            continue
        if "hanly" not in [t.lower() for t in note.tags]:
            note.tags.append("hanly")
            col.update_note(note)
            tagged += 1
        for card in note.cards():
            if card.ord == 0:
                forward_cards.append(card.id)
                if card.queue == -1:
                    forward_to_unsuspend.append(card.id)
            elif card.ord == 1:
                reverse_cards.append(card.id)
                # reps == 0 only, same invariant as promote_to_vocab and the gate: never
                # take away a card that is already mid-schedule.
                if card.queue != -1 and card.reps == 0:
                    reverse_to_suspend.append(card.id)

    if forward_to_unsuspend:
        col.sched.unsuspend_cards(forward_to_unsuspend)
    if reverse_to_suspend:
        col.sched.suspend_cards(reverse_to_suspend)
    if forward_cards and hanly_did:
        col.set_deck(forward_cards, hanly_did)
    if reverse_cards and hanly_rev_did:
        col.set_deck(reverse_cards, hanly_rev_did)

    # The 'hanly' and 'hanly-reverse' decks no longer exist in this collection, so
    # both set_deck calls above are skipped. Report that instead of claiming a move.
    return {
        "tagged": tagged,
        "forward_unsuspended": len(forward_to_unsuspend),
        "reverse_suspended": len(reverse_to_suspend),
        "moved_to_hanly": len(forward_cards) if hanly_did else 0,
        "moved_to_hanly_reverse": len(reverse_cards) if hanly_rev_did else 0,
        "decks_missing": [n for n, d in (("hanly", hanly_did),
                                         ("hanly-reverse", hanly_rev_did)) if d is None],
    }


def promote_to_vocab(col, note_ids):
    """Wild-add promotion: tag notes 'mined', move forward (ord0) cards into the separate
    'Mined' deck (front of THAT deck, so newly added words come up next when studying Mined)
    and unsuspend them, route the reverse (ord1) card into 'Reverse' and the cloze (ord2)
    card into 'Vocab Cloze', both suspended (the maturity gate releases them later). This keeps the
    frequency-ordered Vocab backbone clean — mined reading-words no longer spike it.

    Only NEW forward cards are repositioned, and only a card in Default or under
    Hidden:: moves deck — a card already in HSK, HSK7-9, non-HSK or Mined stays there
    and goes to the front of THAT deck. A card already in learning or review keeps its
    schedule and its position, and is counted under 'already_in_review'."""
    # id_for_name, never id(): col.decks.id() CREATES a missing deck and binds it to
    # preset 1 ("Default"), whose FSRS params, retention and new-card order all differ
    # from the preset the real deck uses. A silent re-create with different scheduling is
    # the same failure as a silently reset deck config. Missing decks are reported instead.
    mined_did = col.decks.id_for_name("Mined")
    cloze_did = col.decks.id_for_name(CLOZE_DECK)
    reverse_did = col.decks.id_for_name(REVERSE_DECK)
    decks_missing = [n for n, d in (("Mined", mined_did), (CLOZE_DECK, cloze_did),
                                    (REVERSE_DECK, reverse_did)) if d is None]
    # The parked xiehanzi import notes are NOT the user's cards. Promoting one would
    # un-archive an import artefact into the study queue, and `Simplified:<word>` returns
    # four of them for most words. Skip them; see _import_pool_note_ids.
    import_pool = _import_pool_note_ids(col, note_ids)
    cv = next((m for m in col.models.all() if m["name"] == CHINESE_VOCAB_NOTETYPE), None)
    cloze_ord = next((t["ord"] for t in cv["tmpls"] if t["name"] == CLOZE_TEMPLATE), None) if cv else None
    reverse_ord = next((t["ord"] for t in cv["tmpls"] if t["name"] == REVERSE_TEMPLATE), 1) if cv else 1
    tagged = 0
    forward_cards = []
    forward_to_unsuspend = []
    reverse_cards = []
    reverse_to_suspend = []
    cloze_cards = []

    for nid in note_ids:
        if nid in import_pool:
            continue
        try:
            note = col.get_note(nid)
        except Exception:
            continue
        if "mined" not in [t.lower() for t in note.tags]:
            note.tags.append("mined")
            col.update_note(note)
            tagged += 1
        # ord 1 and ord 2 mean different things in different note types -- ChineseSentences
        # ord 1 is `Listen-English`, not a production card. Routing those into Reverse and
        # Vocab Cloze stranded them: the gate filters on ChineseVocabulary, so it would
        # never move or release them again. Only ord 0 is promoted for other note types.
        is_cv = cv is not None and note.mid == cv["id"]
        for card in note.cards():
            if card.ord == 0:
                forward_cards.append(card.id)
                if card.queue == -1:
                    forward_to_unsuspend.append(card.id)
            elif not is_cv:
                continue
            elif card.ord == reverse_ord and reverse_did:
                # Route the production card the same way as the cloze card. Suspending it
                # in place left it in a study deck, which breaks the gate's first
                # invariant: add_chinese_vocab put every new note's production card in
                # Mined, and the gate had to move it out on its next run.
                reverse_cards.append(card.id)
                if card.queue != -1 and card.reps == 0:
                    reverse_to_suspend.append(card.id)
            elif cloze_ord is not None and card.ord == cloze_ord and cloze_did:
                # `and cloze_did`: without a target deck the card used to be suspended in
                # place inside a study deck while the result still claimed it was routed.
                cloze_cards.append(card.id)

    if forward_to_unsuspend:
        col.sched.unsuspend_cards(forward_to_unsuspend)
    if reverse_cards:
        col.set_deck(reverse_cards, reverse_did)
    if reverse_to_suspend:
        # reps == 0 only: never take away a card that is already mid-schedule. The gate
        # releases it again once the word matures.
        col.sched.suspend_cards(reverse_to_suspend)
    if cloze_cards:
        col.set_deck(cloze_cards, cloze_did)
        col.sched.suspend_cards([c for c in cloze_cards if col.get_card(c).reps == 0])
    # A card already in a live study deck KEEPS that deck. Only a card in Default or
    # under Hidden:: moves to Mined. Pulling a studied HSK card out of HSK breaks that
    # deck's level ordering and its coverage, and "promote" means the word comes up
    # sooner -- not that it leaves the deck it belongs to.
    hidden = _hidden_deck_ids(col)
    moved, kept = [], []
    for cid in forward_cards:
        card = col.get_card(cid)
        did = card.odid or card.did
        (kept if (did != 1 and did not in hidden) else moved).append(cid)
    if moved and mined_did:
        col.set_deck(moved, mined_did)
    elif moved:
        kept.extend(moved)          # no Mined deck: leave them where they are
        moved = []

    # Front of each target deck: due below that deck's own new cards, newest first.
    # `odid or did` for the same reason as above -- a card sitting in a filtered deck has
    # its home deck in odid, and grouping by the filtered deck computed MIN(due) over the
    # wrong deck and wrote a position that the filtered deck discards on empty.
    by_deck = {}
    for cid in kept:
        c = col.get_card(cid)
        by_deck.setdefault(c.odid or c.did, []).append(cid)
    for cid in moved:
        by_deck.setdefault(mined_did, []).append(cid)

    repositioned = 0
    already_in_review = 0
    for did, cids in by_deck.items():
        min_due = col.db.scalar(
            "SELECT MIN(due) FROM cards WHERE did=? AND type=0 AND ord=0", did)
        next_due = min(min_due if min_due is not None else 1, 1) - 1
        for cid in cids:
            card = col.get_card(cid)
            # `due` is a queue POSITION on a new card but a DAY NUMBER on a learning
            # or review card. Writing a negative position onto a review card made it
            # hundreds of days overdue and discarded its schedule -- a card due in 9
            # days became 250 days late. Only new cards move. A card already in
            # review needs no promotion; it is in rotation already.
            if card.type != 0:
                already_in_review += 1
                continue
            set_new_card_position(col, card, next_due)
            next_due -= 1
            repositioned += 1

    return {
        "tagged": tagged,
        "forward_unsuspended": len(forward_to_unsuspend),
        "skipped_import_pool": len(import_pool),
        "decks_missing": decks_missing,
        "moved_to_mined": len(moved),
        "kept_in_deck": len(kept),
        "repositioned_to_front": repositioned,
        "already_in_review": already_in_review,
        "reverse_routed": len(reverse_cards),
        "reverse_suspended": len(reverse_to_suspend),
        "cloze_routed": len(cloze_cards),
    }


def freq_tier(word):
    """Corpus frequency of a Chinese word via wordfreq. Returns zipf + a tier:
    very common (>=5), common (4-5), mid (3.5-4), uncommon (3-3.5), rare (<3)."""
    from wordfreq import zipf_frequency  # lazy import (loads jieba on first use)
    z = zipf_frequency(word, "zh")
    if z >= 5:    tier = "very common"
    elif z >= 4:  tier = "common"
    elif z >= 3.5: tier = "mid"
    elif z >= 3:  tier = "uncommon"
    elif z > 0:   tier = "rare"
    else:         tier = "not in corpus"
    return {"word": word, "zipf": round(z, 2), "tier": tier}


def _collect_card_ids(col, note_ids):
    """Collect card IDs from note IDs, skipping missing notes."""
    card_ids = []
    skipped = 0
    for nid in note_ids:
        try:
            note = col.get_note(nid)
            card_ids.extend(c.id for c in note.cards())
        except Exception:
            skipped += 1
    return card_ids, skipped


def _looks_like_json_fragment(text):
    """Heuristic: does this text look like a chunk of JSON data?"""
    indicators = 0
    if '": ' in text or '":' in text:
        indicators += 1
    if text.count('"') > 6:
        indicators += 1
    if text.count('{') + text.count('}') > 2:
        indicators += 1
    if text.count('[') + text.count(']') > 1:
        indicators += 1
    if re.search(r'"\w+":\s*[{\["\d]', text):
        indicators += 1
    return indicators >= 3


# ── Conversation state ────────────────────────────────────────────────

chat_histories = {}  # {chat_id: [{"role": "user"/"assistant", "content": ...}]}


def _truncate_content(content, max_chars=20000):
    """Truncate a tool result string to prevent history bloat."""
    if isinstance(content, str) and len(content) > max_chars:
        return content[:max_chars] + f"\n\n[... truncated from {len(content):,} chars]"
    return content


def _estimate_history_chars(chat_id):
    """Rough estimate of total characters in conversation history."""
    total = 0
    for msg in chat_histories.get(chat_id, []):
        content = msg.get("content", "")
        if isinstance(content, str):
            total += len(content)
        elif isinstance(content, list):
            for item in content:
                if isinstance(item, dict):
                    if item.get("type") == "image":
                        total += 1000  # rough proxy for image token cost
                    else:
                        total += len(json.dumps(item, ensure_ascii=False))
        else:
            total += len(str(content))
    return total


def _trim_history(chat_id, max_messages=50, max_chars=300000):
    """Trim conversation history by count and total size."""
    hist = chat_histories.get(chat_id, [])
    if len(hist) > max_messages:
        chat_histories[chat_id] = hist[-max_messages:]
    # Also trim by total estimated size
    while len(chat_histories.get(chat_id, [])) > 2:
        if _estimate_history_chars(chat_id) <= max_chars:
            break
        chat_histories[chat_id] = chat_histories[chat_id][2:]  # drop oldest pair


# ── Unified system prompt ─────────────────────────────────────────────

SYSTEM_PROMPT = """You are an Anki card creation and collection management assistant running as a Telegram bot. You help the user create flashcards and manage their Anki collection through natural conversation.

## FIRST PRINCIPLE: The user's intent is ALWAYS to understand or improve a card
The user is a heritage Chinese learner curating this collection. Essentially every message is about one or more specific cards — usually the card(s) most recently discussed — and the underlying goal is ALWAYS the same: understand the card and make it better. "help me look at X", "what about Y", "is there such a usage", "doesn't it just mean Z" are never abstract language questions — they mean *pull up that card and critically evaluate it with me.* Act on that intent directly; do not wait to be asked to fetch, and do not wait to be asked whether the card is good.

Your standing loop for any card-related message:
1. **Fetch first, automatically.** Call `search_notes` + `get_notes_detail` (or `get_field_values`) and read the card's ACTUAL current fields BEFORE you say anything about it. Never describe, judge, or answer from memory, from earlier in this conversation, or from general knowledge of the word — the user having to say "you didn't look up the card yet?" or "look at the example" is a failure. If the user refers to "this card", "the first card", "it", or a word already discussed, re-fetch it; don't trust your earlier view of the fields.
2. **Critically assess it, unasked.** Once you've read the fields, proactively judge quality: Is the Meaning complete and accurate? Does it cover the character's/word's main senses? Is the example sentence real, natural, and actually illustrative of the target usage? Is the pinyin right? State plainly what's weak and what you'd change — don't wait for "do you think this is high quality?" That question means you should already have volunteered the assessment.
3. **Ground every claim in the real fields.** Quote or reference what the card actually says. If you propose an example or usage, verify it's genuine — don't invent examples and don't defend a shaky one under pushback; re-check and correct.
4. **Propose the improvement and offer to make it.** Since the goal is to improve the card, move toward a concrete edit (preview it, then edit_note on confirmation).
5. **After the edit, offer to move the card to the front — then stop and wait.** Never promote silently. Read `card_states` from `get_notes_detail` (the ord-0 card) and choose by its `state`:
   - **`new`** — offer it. Say how far back it sits (`queue_position`) and ask: "Move it to the front so it comes up next?" On a yes, call `tag_notes` with the `mined` tag. Say "first among the new cards", not "next" — cards already due still come first.
   - **`review`, `learning` or `day-learn`** — do NOT offer. The card is in rotation. Report `due_in_days` (or `due_in_minutes` for `learning`). Promotion would leave this card's own deck, schedule and position untouched, but it still tags the note and re-routes its production and cloze siblings, so it is not a no-op.
   - **`suspended`** — ask whether the card was parked on purpose before you do anything. About 164 basic HSK single-character cards are suspended deliberately. `tag_notes` + `mined` UNSUSPENDS the ord-0 card, so it can silently undo that decision.
   - **`buried-manual`, `buried-sibling`, `preview`** — do not offer; the state is temporary. Say what it is.
   Make the offer once per card. If the user declines, drop it and do not ask again for that card.

When the user pushes back ("doesn't it just mean middle?", "are you over-indexing on the tone?", "isn't the card just the character itself?"), treat it as a correction: re-read the card, reconsider, and update your view — do not dig in defending a previous reply.

The only messages that DON'T need a fetch first: pure chit-chat, story-writing requests (use the story tools), or a one-word confirmation (yes/ok) to an action you already previewed.

## Chinese card philosophy (how the user thinks about cards)
- **One comprehensive card per character/word — NEVER split by pronunciation or tone.** A character like 中 (zhōng / zhòng) gets a SINGLE card whose Meaning and Notes cover all its major senses and both pronunciations together. Do not propose, create, or maintain separate cards per reading. If you find duplicates split by pronunciation, the fix is to merge them into one comprehensive card, not to keep them apart.
- **The card represents the character/word itself**, not one narrow usage. When evaluating, ask "does this card comprehensively capture what 中 IS?" — not "does this example match one specific tone?" Don't get fixated on a single reading or example at the expense of the whole.
- A high-quality card: accurate and reasonably complete Meaning (main senses), correct tone-marked pinyin covering the readings in use, and a natural, genuine example sentence that a learner would actually encounter.

## Collection layout — two different things live under `Hidden::`
`Hidden::` holds 213,447 cards. Only **499** are unsuspended, and **346 of those are in
review**, so "under Hidden" does NOT mean "never appears in a review". The live ones sit in
`Hidden::hanly-grammar` (226), `Hidden::hanly-proper-nouns` (172), `Hidden::Personal` (30)
and `Hidden::Personal-reverse` (3). `Hidden::Archive::*` is 212,750 cards with only 25
unsuspended. (Counts measured 2026-08-19; treat them as approximate.)

**Two populations sit there, and they need OPPOSITE actions. `search_notes` and
`get_notes_detail` tell them apart for you — read the flags, never guess.**

1. **`import_pool` — ignore these.** The four note types `Basic - new hsk 3.0 xiehanzi v3 -
   audio` / `- pinyin-zhuyin` / `- write` / `- meaning` are one complete HSK 3.0 deck
   imported years ago, 11,042 notes each, entirely parked. **Every one uses a field named
   `Simplified`**, exactly like the live ChineseVocabulary notes, so `Simplified:说服`
   returns the real card plus four of these. That is the expected shape, not a defect.
2. **`archived` — these are the USER'S OWN cards.** A ChineseVocabulary, ChineseCharacters
   or ChineseSentences note parked in `Hidden::Archive::*` is the user's staged backlog:
   **30,556 of 49,930 vocabulary notes are there.** Words like 立即, 长江, 打篮球 exist ONLY
   as an archived note. They are not import junk and they are not duplicates.

Rules that follow:
- **An archived note means the word IS in the collection.** If the user wants to study it,
  promote it with `tag_notes` + the `mined` tag — that unarchives it into `Mined`. **Never
  create a second note for a word that already has an archived one.** 153 words already
  carry both an archived and a live note from exactly that mistake.
- **Ignore `import_pool` hits entirely.** Do not count them, edit them, or offer to delete
  them. `tag_notes` skips them and `delete_notes` refuses them.
- **Never propose deleting an archived note.** It costs nothing and it is the user's own
  staged material. `delete_notes` refuses it unless the user asks explicitly.
- **A real duplicate is two notes of the same note type that BOTH have live cards.** 13
  words currently qualify. An archived note plus a live note is a promotion question, not
  a duplicate — say so and offer to merge or promote, do not silently ignore it.

## Capabilities
1. **Chinese vocabulary cards** — create ChineseVocabulary note type cards
2. **General cards** — create Basic note type cards for any topic
3. **Edit cards** — modify field values on existing notes (use get_notes_detail first to see current values)
4. **Collection management** — search, suspend, unsuspend, delete, tag, move cards
5. **Image analysis** — OCR Chinese text from photos, offer to create cards
6. **Collection stats** — report on deck sizes, due counts, etc.

## Chinese Vocabulary Cards
When the user sends Chinese characters (word or short phrase), look it up and offer to create a card.
ChineseVocabulary fields: Simplified, Traditional, Pinyin, Meaning, PartOfSpeech, SentenceSimplified, SentencePinyin, SentenceMeaning, Notes.
- Use tone-marked pinyin (ā á ǎ à), NOT numbered
- Always provide traditional even if same as simplified
- Include a natural example sentence
- Default deck: """ + DEFAULT_DECK + """
- Default tags: ["claude", "chinese"]

## General Cards
For non-Chinese knowledge, create Basic cards with Front/Back fields.
- Make the front a clear question
- Make the back a concise but complete answer
- Default deck: "Knowledge"
- Default tags: ["claude"]

## Anki Search Syntax (for tools)
- `deck:DeckName` or `"deck:Deck Name"` — filter by deck (includes subdecks)
- `tag:tagname` — filter by tag
- `note:NoteTypeName` — filter by note type
- `is:suspended`, `is:new`, `is:due`, `is:review`, `is:learn`, `is:buried`
- `-is:suspended` — negate any filter
- `front:text`, `back:text`, `Simplified:text`, `FieldName:text` — search specific fields
- Combine terms with spaces for AND; use `OR` for OR
- `"exact phrase"` for literal matching
- `*` wildcard, `_` single char wildcard
- `added:N` — added in last N days
- `rated:N` — reviewed in last N days
- `prop:ivl>30` — cards with interval > 30 days

## Chinese Reading Stories
When the user asks for a story or reading practice:
1. Call `get_vocab_for_story` AND `get_grammar_for_story` to get known vocabulary, target words, and grammar patterns
2. If the user wants a news-based or current-events story, use `web_search` to find recent Chinese news headlines for inspiration
3. Write the story following this format exactly:

**Header**: 📖 Chinese story #N (HSK level, topic tag):
**Title**: 【Chinese title】 followed by English translation on same line
**Body**: ~350-400 Chinese characters. Use 90-95% known vocab from the list. Write in first person, conversational tone. Use short paragraphs. Mix in dialogue for engagement. Build to an interesting or thought-provoking conclusion.
**Target words**: Weave in ~5-7 target words naturally. Annotate each on first use as: word（pinyin - meaning）
**Grammar**: Naturally incorporate the grammar patterns from `get_grammar_for_story`. On first use of each pattern, annotate it as: [grammar structure]（pattern formula）
**Footer**: After a --- separator:
  📝 Key vocab: bullet list of all target words with pinyin and meaning
  📗 Grammar patterns: bullet list of each grammar pattern used, with the formula and one example from the story
  📰 Based on: one-line summary of the real news story (if news-based)

4. The user can ask for a specific topic, difficulty adjustment, or more/fewer new words
5. If the user wants to create cards for the target words, offer to do so

## User Preferences
- Chinese vocabulary decks: **HSK**, **HSK7-9** and **non-HSK** (frequency-ordered).
  There is NO deck named `Vocab` — that name is dead, and `deck:Vocab` matches nothing.
  **Mined** is where wild-adds go. Words the user
  adds in the wild are tagged **mined** and placed at the FRONT of the new-card queue (next-up)
  so they're studied first. add_chinese_vocab does this automatically; to promote existing
  notes, use tag_notes with the "mined" tag. (The old "hanly" deck/tag is defunct/merged.)
- You can report a word's frequency tier with lookup_frequency (very common → rare).

## Important Rules
- **Read the card before you talk about it, and critique it unasked.** For any card-related message — including follow-ups and pushback — re-fetch the current fields with get_notes_detail before answering, then proactively assess quality and propose improvements. Never answer from conversation memory or general knowledge. One comprehensive card per character/word; never split by pronunciation. (See FIRST PRINCIPLE above.)
- **Always confirm before destructive actions** (delete, suspend, unsuspend, tag, move). Show what will be affected and ask the user to confirm before calling the modification tool.
- **Always sync after modifications** — call sync_collection after any add/edit/delete/suspend/tag/move operation.
- For card creation, show a preview of what you'll create and ask for confirmation before calling add_chinese_vocab or add_general_card.
- When analyzing images, list the words you found and ask which ones to create cards for.
- Keep responses concise — this is a Telegram chat, not an essay.
- For large result sets needing semantic filtering, use get_field_values to inspect content efficiently.
- When user confirms (yes/y/ok/sure/do it), proceed with the action without asking again.
"""

API_SYSTEM_PROMPT = """You are an Anki card creation assistant for Chinese vocabulary, invoked via API.
You receive a Chinese word or phrase. Execute the following steps autonomously — no confirmation needed.

## Steps
1. **Search** for an existing card: use search_notes with query `Simplified:<word>`
2. **Read the three id lists search_notes returns. They mean different things.**
   - `import_pool_note_ids` — parked xiehanzi import artefacts. **Ignore them completely.**
     They are not cards and they are not evidence the word exists.
   - `archived_note_ids` — the USER'S OWN note, parked under `Hidden::`. **The word EXISTS.
     Never treat it as "not found" and never create a second note for it.** 30,556 of
     49,930 vocabulary notes are archived, including very common words, so this is the
     normal case, not an edge case. Promote it instead: go to step 5.
   - `live_note_ids` — already in an active study deck.
   Decide with: live hit → step 3. No live hit but an archived hit → step 5. Only
   import-pool hits, or no hits at all → step 4.
3. **If found**: use get_notes_detail to inspect it. If any fields are weak/empty (missing pinyin, meaning, sentence, traditional), improve them with edit_note.
4. **If not found**: create a new card with add_chinese_vocab. Use tone-marked pinyin (ā á ǎ à), include traditional characters, a natural example sentence, and part of speech. This automatically files the card in the **Mined** deck, tags it **mined**, and puts it first among that deck's new cards — no extra step needed. There is no deck named `Vocab`.
5. **If found but archived or in another deck**: use tag_notes with the "mined" tag. That
   unarchives the note, moves its ord-0 card into Mined, and puts it first among that
   deck's new cards. This is the correct path for every archived hit — it is what stops a
   duplicate note being created for a word the user already has.
6. **Sync**: call sync_collection.

## Response format
After completing all steps, respond with ONLY a JSON object (no markdown, no explanation):
{"status": "created" or "improved", "word": "<simplified>", "pinyin": "<pinyin>", "meaning": "<meaning>", "action_details": "<brief description of what was done>"}

If the word already exists and all fields are complete, return:
{"status": "already_exists", "word": "<simplified>", "pinyin": "<pinyin>", "meaning": "<meaning>", "action_details": "Card already complete"}

## Rules
- Act immediately. Do NOT ask for confirmation.
- Use tone-marked pinyin, never numbered.
- Always provide traditional characters even if same as simplified.
- Default tags: ["claude", "chinese"]
- Keep the example sentence natural and at an intermediate level.
"""

# ── Tools ─────────────────────────────────────────────────────────────

TOOLS = [
    # Read-only tools
    {
        "name": "search_notes",
        "description": "Search for notes using Anki's search syntax. Returns note IDs and total count.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Anki search query (e.g., 'deck:Chinese tag:hsk4', '\"deck:My Deck\" is:suspended')"
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "get_notes_detail",
        "description": "Get field values, tags, deck, and note type for a batch of notes. Max 100 per call. Use get_field_values instead for large sets.",
        "input_schema": {
            "type": "object",
            "properties": {
                "note_ids": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "Note IDs to look up (max 100)"
                }
            },
            "required": ["note_ids"]
        }
    },
    {
        "name": "get_field_values",
        "description": "Get specific field value(s) for notes matching a search query. Much more efficient than get_notes_detail for large sets.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Anki search query to find notes"
                },
                "fields": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Field names to return (e.g., ['Simplified', 'Meaning'])"
                }
            },
            "required": ["query", "fields"]
        }
    },
    {
        "name": "list_decks",
        "description": "List all decks with their card counts.",
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "list_note_types",
        "description": "List all note types and their field names.",
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "get_collection_stats",
        "description": "Get collection statistics: new, due, learning, and total card counts.",
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    },
    # Card creation tools
    {
        "name": "add_chinese_vocab",
        "description": "Create a ChineseVocabulary card. Only call after user confirms the preview.",
        "input_schema": {
            "type": "object",
            "properties": {
                "simplified": {"type": "string"},
                "traditional": {"type": "string"},
                "pinyin": {"type": "string", "description": "Tone-marked pinyin"},
                "meaning": {"type": "string"},
                "part_of_speech": {"type": "string"},
                "sentence_simplified": {"type": "string"},
                "sentence_pinyin": {"type": "string"},
                "sentence_meaning": {"type": "string"},
                "notes": {"type": "string", "description": "Optional extra notes"},
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Extra tags beyond the default ['claude', 'chinese']"
                }
            },
            "required": ["simplified", "traditional", "pinyin", "meaning"]
        }
    },
    {
        "name": "add_general_card",
        "description": "Create a Basic card. Only call after user confirms the preview.",
        "input_schema": {
            "type": "object",
            "properties": {
                "front": {"type": "string", "description": "Question / front side"},
                "back": {"type": "string", "description": "Answer / back side"},
                "deck": {"type": "string", "description": "Deck name (default: Knowledge)"},
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Tags for the card"
                }
            },
            "required": ["front", "back"]
        }
    },
    # Modification tools
    {
        "name": "suspend_cards",
        "description": "Suspend all cards for notes matching a query. Confirm with user first.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Anki search query to select notes"}
            },
            "required": ["query"]
        }
    },
    {
        "name": "unsuspend_cards",
        "description": "Unsuspend all cards for notes matching a query. Confirm with user first.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Anki search query to select notes"}
            },
            "required": ["query"]
        }
    },
    {
        "name": "tag_notes",
        "description": "Add tags to notes matching a query. Confirm with user first.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Anki search query to select notes"},
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Tags to add"
                }
            },
            "required": ["query", "tags"]
        }
    },
    {
        "name": "remove_tags",
        "description": "Remove tags from notes matching a query. Confirm with user first.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Anki search query to select notes"},
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Tags to remove"
                }
            },
            "required": ["query", "tags"]
        }
    },
    {
        "name": "delete_notes",
        "description": "Delete notes matching a query. DESTRUCTIVE — always confirm with user first. "
                       "Refuses notes archived under Hidden:: unless include_archived is true.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Anki search query to select notes"},
                "include_archived": {"type": "boolean", "description": "Allow deletion of notes whose every card sits in a Hidden:: deck. Default false. Only set this after the user explicitly asks to delete archived notes."}
            },
            "required": ["query"]
        }
    },
    {
        "name": "move_cards",
        "description": "Move cards matching a query to a different deck. Confirm with user first.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Anki search query to select notes"},
                "deck": {"type": "string", "description": "Target deck name"}
            },
            "required": ["query", "deck"]
        }
    },
    {
        "name": "edit_note",
        "description": "Edit field values on an existing note. Use get_notes_detail first to see current values. Confirm with user first.",
        "input_schema": {
            "type": "object",
            "properties": {
                "note_id": {
                    "type": "integer",
                    "description": "The note ID to edit"
                },
                "fields": {
                    "type": "object",
                    "description": "Map of field names to new values (e.g., {\"Meaning\": \"new meaning\", \"Pinyin\": \"xīn pīnyīn\"}). Only include fields you want to change."
                }
            },
            "required": ["note_id", "fields"]
        }
    },
    {
        "name": "sync_collection",
        "description": "Sync the collection to AnkiWeb.",
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    },
    # Card-type-specific tools
    {
        "name": "get_note_type_templates",
        "description": "Get card template names for a note type. Shows what card types are generated from each note.",
        "input_schema": {
            "type": "object",
            "properties": {
                "note_type": {"type": "string", "description": "Name of the note type (e.g. 'ChineseVocabulary')"}
            },
            "required": ["note_type"]
        }
    },
    {
        "name": "get_cards_info",
        "description": "Get all cards for specific notes with template, deck, suspended status, and card state.",
        "input_schema": {
            "type": "object",
            "properties": {
                "note_ids": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "List of note IDs (max 100)"
                }
            },
            "required": ["note_ids"]
        }
    },
    {
        "name": "suspend_card_type",
        "description": "Suspend only cards of a specific template for notes matching a query. Confirm with user first.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Anki search query to select notes"},
                "template_name": {"type": "string", "description": "Card template name to suspend (e.g. 'English-Speaking')"}
            },
            "required": ["query", "template_name"]
        }
    },
    {
        "name": "unsuspend_card_type",
        "description": "Unsuspend only cards of a specific template for notes matching a query. Confirm with user first.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Anki search query to select notes"},
                "template_name": {"type": "string", "description": "Card template name to unsuspend (e.g. 'English-Speaking')"}
            },
            "required": ["query", "template_name"]
        }
    },
    {
        "name": "move_card_type",
        "description": "Move only cards of a specific template to a different deck. Confirm with user first.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Anki search query to select notes"},
                "template_name": {"type": "string", "description": "Card template name to move (e.g. 'English-Speaking')"},
                "deck": {"type": "string", "description": "Target deck name"}
            },
            "required": ["query", "template_name", "deck"]
        }
    },
    # Story generation tools
    {
        "name": "get_vocab_for_story",
        "description": "Get vocabulary for story generation. Returns ~150 known (reviewed) Chinese words and 5-10 target (unseen/suspended) words. Call this before writing a Chinese reading story.",
        "input_schema": {
            "type": "object",
            "properties": {
                "num_known": {
                    "type": "integer",
                    "description": "Number of known words to sample (default 150)"
                },
                "num_target": {
                    "type": "integer",
                    "description": "Number of target/new words to include (default 6)"
                }
            }
        }
    },
    {
        "name": "get_grammar_for_story",
        "description": "Get grammar patterns for story generation. Returns 2-3 grammar patterns with example sentences from the hanly-grammar deck. Call this alongside get_vocab_for_story before writing a Chinese reading story.",
        "input_schema": {
            "type": "object",
            "properties": {
                "num_patterns": {
                    "type": "integer",
                    "description": "Number of grammar patterns to sample (default 3)"
                }
            }
        }
    },
    {
        "name": "lookup_frequency",
        "description": "Look up how common one or more Chinese words are, using the wordfreq corpus (Zipf scale). Returns each word's zipf score and a tier: very common (zipf>=5), common (4-5), mid (3.5-4), uncommon (3-3.5), rare (<3). Use when the user asks how common/useful/frequent a word is, or how to prioritize words.",
        "input_schema": {
            "type": "object",
            "properties": {
                "words": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "One or more Chinese words to look up"
                }
            },
            "required": ["words"]
        }
    },
]

API_TOOL_NAMES = {
    "search_notes", "get_notes_detail", "get_field_values",
    "add_chinese_vocab", "edit_note", "tag_notes", "sync_collection",
    "lookup_frequency"
}
API_TOOLS = [t for t in TOOLS if t["name"] in API_TOOL_NAMES]

# ── Archive detection ─────────────────────────────────────────────────
# Hidden:: holds 219,218 cards and only 1,058 are unsuspended; Hidden::Archive::*
# alone is 214,006 cards with 213,981 suspended -- legacy import pools the user
# parked on purpose. The four "Basic - new hsk 3.0 xiehanzi v3 - *" note types live
# there and carry a field named `Simplified`, same as the live ChineseVocabulary
# notes, so `Simplified:<word>` returns the real card plus 4 archived ones. Without
# a flag that reads as five duplicates and the model proposes deleting four of them.
# A note is archived when EVERY one of its cards is in a Hidden:: deck -- deliberately
# not "and suspended", because a handful of archive cards are unsuspended and the
# conservative direction for a delete guard is to protect more, not less.

def _hidden_deck_ids(col):
    """Deck IDs of `Hidden` and its subdecks. The DB joins name components with \x1f,
    so the subtree test is an exact match or that prefix. A substring test was wrong in
    both directions: it would claim `Mined::Hidden gems`, and it would miss nothing today
    but silently capture any future deck with "Hidden" in any component."""
    return {did for did, name in col.db.all("SELECT id, name FROM decks")
            if name == "Hidden" or name.startswith("Hidden\x1f")}


# anki/consts.py: -3 is MANUALLY_BURIED, -2 is SIBLING_BURIED. The two were swapped here.
_QUEUE_STATE = {-3: "buried-manual", -2: "buried-sibling", -1: "suspended",
                0: "new", 1: "learning", 2: "review", 3: "day-learn", 4: "preview"}


def _card_state(col, card, tmpl_name, today):
    """Compact per-card state for get_notes_detail. `due` means different things by
    card type -- a queue position on a new card, a day number on a review card -- so
    the two go under different keys and are never compared to each other."""
    info = {"ord": card.ord, "template": tmpl_name,
            "deck": col.decks.name(card.odid or card.did),
            "state": _QUEUE_STATE.get(card.queue, str(card.queue)),
            "reviews": card.reps}
    # `due` carries three different units. A new card holds a queue POSITION. A review
    # or day-learn card holds a DAY NUMBER. An intraday learning card holds a unix
    # TIMESTAMP. Reporting them under one key is what let a queue position get written
    # onto a review card and throw its schedule away.
    if card.type == 0:
        info["queue_position"] = card.due
    elif card.queue in (2, 3):
        # A card pulled into a filtered deck keeps its real due in odue; `due` is then a
        # filtered-queue position and subtracting today gives nonsense (-100246).
        info["due_in_days"] = (card.odue or card.due) - today
    elif card.queue == 1:
        info["due_in_minutes"] = max(0, (card.due - int(time.time())) // 60)
    return info


# One complete HSK 3.0 deck was imported years ago under these four note types and parked
# under Hidden::. They carry a field named `Simplified`, same as the live
# ChineseVocabulary notes, so `Simplified:<word>` returns them beside the real card.
# They are the ONLY notes safe to ignore outright. An archived ChineseVocabulary or
# ChineseCharacters note is a different thing entirely -- it is the user's own staged
# backlog (30,556 of 49,930 vocabulary notes), and it must be promoted, never ignored and
# never re-created as a new card.
IMPORT_POOL_NOTETYPE_PREFIX = "Basic - new hsk 3.0 xiehanzi v3"


def _import_pool_note_ids(col, note_ids):
    """Subset of note_ids belonging to the parked xiehanzi import note types."""
    note_ids = [int(n) for n in note_ids]
    if not note_ids:
        return set()
    mids = [m["id"] for m in col.models.all()
            if m["name"].startswith(IMPORT_POOL_NOTETYPE_PREFIX)]
    if not mids:
        return set()
    return set(col.db.list(
        "SELECT id FROM notes WHERE id IN (%s) AND mid IN (%s)"
        % (",".join(str(n) for n in note_ids), ",".join(str(m) for m in mids))))


def _archived_note_ids(col, note_ids):
    """Subset of note_ids whose every card sits in a Hidden:: deck. Notes with no
    card at all are not archived."""
    note_ids = [int(n) for n in note_ids]
    if not note_ids:
        return set()
    hidden = _hidden_deck_ids(col)
    ids_sql = ",".join(str(n) for n in note_ids)
    has_card, live = set(), set()
    for nid, did, odid in col.db.all(
            f"SELECT nid, did, odid FROM cards WHERE nid IN ({ids_sql})"):
        has_card.add(nid)
        if (odid or did) not in hidden:
            live.add(nid)
    return has_card - live


# ── Tool execution ────────────────────────────────────────────────────

def execute_tool(tool_name, tool_input):
    """Execute a tool call and return the result as a string."""

    if tool_name == "sync_collection":
        return _sync_collection()

    if tool_name == "lookup_frequency":
        words = tool_input.get("words", [])
        return json.dumps({"results": [freq_tier(w) for w in words]}, ensure_ascii=False)

    if tool_name == "get_collection_stats":
        col = open_collection()
        try:
            new_count = len(col.find_cards("is:new"))
            due_count = len(col.find_cards("is:due"))
            learn_count = len(col.find_cards("is:learn"))
            total = col.card_count()
            claude_count = len(col.find_notes("tag:claude"))
            return json.dumps({
                "total_cards": total,
                "new": new_count,
                "learning": learn_count,
                "due": due_count,
                "claude_tagged": claude_count,
            })
        finally:
            col.close()

    if tool_name == "add_chinese_vocab":
        col = open_collection()
        try:
            model = col.models.by_name(CHINESE_VOCAB_NOTETYPE)
            if not model:
                return json.dumps({"error": f"Note type '{CHINESE_VOCAB_NOTETYPE}' not found"})

            # DEFAULT_DECK names a deck this collection dropped, so id_for_name gives
            # None and Anki files the note in Default -- where 199 stray cards piled up,
            # including 65 ungated cloze cards. promote_to_vocab sends ord0 to Mined a
            # moment later, so Mined is the right home for the siblings too.
            # promote_to_vocab moves ord 0 to Mined a moment later, and the ord 1 / ord 2
            # templates carry their own deck override, so Mined is the correct home deck.
            # DEFAULT_DECK is honoured only if it actually exists.
            did = col.decks.id_for_name(DEFAULT_DECK) or deck_id(col, "Mined")
            note = col.new_note(model)

            note["Simplified"] = tool_input.get("simplified", "")
            note["Traditional"] = tool_input.get("traditional", "")
            note["Pinyin"] = tool_input.get("pinyin", "")
            note["Meaning"] = tool_input.get("meaning", "")
            note["PartOfSpeech"] = tool_input.get("part_of_speech", "")
            note["SentenceSimplified"] = tool_input.get("sentence_simplified", "")
            note["SentencePinyin"] = tool_input.get("sentence_pinyin", "")
            note["SentenceMeaning"] = tool_input.get("sentence_meaning", "")
            if tool_input.get("notes"):
                note["Notes"] = tool_input["notes"]

            tags = ["claude", "chinese"]
            tags.extend(tool_input.get("tags", []))
            note.tags = tags

            col.add_note(note, did)
            nid = note.id
            # Wild-add: promote into the Mined deck, tag 'mined', place next-up in the queue
            promo = promote_to_vocab(col, [nid])
            # Report where the card actually is, not where it is meant to go. The
            # hardcoded "Mined" was true only because DEFAULT_DECK did not exist.
            landed = next((col.decks.name(c.did) for c in col.get_note(nid).cards()
                           if c.ord == 0), "unknown")
            log_change("add_chinese_vocab", [nid], {
                "simplified": tool_input.get("simplified"),
                "deck": landed,
                "tags": tags + ["mined"],
            })
            return json.dumps({
                "success": True,
                "note_id": nid,
                "simplified": tool_input.get("simplified"),
                "deck": "Mined",
                "placed": "next-up (mined)",
            })
        except Exception as e:
            return json.dumps({"error": str(e)})
        finally:
            col.close()

    if tool_name == "add_general_card":
        col = open_collection()
        try:
            model = col.models.by_name("Basic")
            if not model:
                return json.dumps({"error": "Note type 'Basic' not found"})

            # `Knowledge` does not exist in this collection. id_for_name returned None,
            # Anki filed the card in `Default`, and the tool reported deck "Knowledge".
            # This is the same defect fixed in add_chinese_vocab; it survived there.
            deck = tool_input.get("deck", "Knowledge")
            did = col.decks.id_for_name(deck)
            if did is None:
                return json.dumps({
                    "error": f"No deck named {deck!r}. Nothing was created.",
                    "existing_decks": sorted(d.name for d in col.decks.all_names_and_ids()),
                }, ensure_ascii=False)
            note = col.new_note(model)

            note["Front"] = tool_input.get("front", "")
            note["Back"] = tool_input.get("back", "")

            tags = ["claude"]
            tags.extend(tool_input.get("tags", []))
            note.tags = tags

            col.add_note(note, did)
            nid = note.id
            log_change("add_general_card", [nid], {
                "front": tool_input.get("front", "")[:50],
                "deck": deck,
                "tags": tags,
            })
            return json.dumps({
                "success": True,
                "note_id": nid,
                "front": tool_input.get("front", "")[:80],
                "deck": deck,
            })
        except Exception as e:
            return json.dumps({"error": str(e)})
        finally:
            col.close()

    if tool_name == "get_vocab_for_story":
        num_known = tool_input.get("num_known", 150)
        num_target = tool_input.get("num_target", 6)
        col = open_collection()
        try:
            # Known words: reviewed ChineseVocabulary cards tagged hanly (not new, not suspended)
            known_ids = list(col.find_notes(
                f'"note:{CHINESE_VOCAB_NOTETYPE}" tag:hanly -is:new -is:suspended'
            ))
            # Target words: new or suspended ChineseVocabulary cards tagged hanly
            target_ids = list(col.find_notes(
                f'"note:{CHINESE_VOCAB_NOTETYPE}" tag:hanly (is:new OR is:suspended)'
            ))

            known_sample = random.sample(known_ids, min(num_known, len(known_ids)))
            target_sample = random.sample(target_ids, min(num_target, len(target_ids)))

            def _extract_vocab(nid):
                note = col.get_note(nid)
                model = note.note_type()
                fnames = [f["name"] for f in model["flds"]]
                def _get(name):
                    if name in fnames:
                        idx = fnames.index(name)
                        return strip_html(note.fields[idx]) if idx < len(note.fields) else ""
                    return ""
                return {
                    "simplified": _get("Simplified"),
                    "pinyin": _get("Pinyin"),
                    "meaning": _get("Meaning"),
                }

            known_words = [_extract_vocab(nid) for nid in known_sample]
            target_words = [_extract_vocab(nid) for nid in target_sample]

            return json.dumps({
                "known_words": known_words,
                "known_total": len(known_ids),
                "target_words": target_words,
                "target_pool": len(target_ids),
            }, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"error": str(e)})
        finally:
            col.close()

    if tool_name == "get_grammar_for_story":
        num_patterns = tool_input.get("num_patterns", 3)
        col = open_collection()
        try:
            # Find all hanly-grammar tagged sentences
            grammar_ids = list(col.find_notes('note:ChineseSentences tag:hanly-grammar'))

            # Group by grammar tag
            tag_groups = {}  # {grammar_tag: [note_id, ...]}
            for nid in grammar_ids:
                note = col.get_note(nid)
                for tag in note.tags:
                    if tag.startswith("grammar::"):
                        tag_groups.setdefault(tag, []).append(nid)

            if not tag_groups:
                return json.dumps({"error": "No hanly-grammar sentences found. Run --tag-hanly first."})

            # Sample grammar patterns (prefer tags with more examples)
            available_tags = list(tag_groups.keys())
            selected_tags = random.sample(available_tags, min(num_patterns, len(available_tags)))

            patterns = []
            for tag in selected_tags:
                nids = tag_groups[tag]
                sample_nids = random.sample(nids, min(3, len(nids)))
                examples = []
                grammar_notes = []
                for nid in sample_nids:
                    note = col.get_note(nid)
                    examples.append({
                        "simplified": strip_html(note["Simplified"]),
                        "pinyin": strip_html(note["Pinyin"]),
                        "meaning": strip_html(note["Meaning"]),
                    })
                    gn1 = strip_html(note["GrammarNotes1"]).strip()
                    gn2 = strip_html(note["GrammarNotes2"]).strip()
                    if gn1 and gn1 not in grammar_notes:
                        grammar_notes.append(gn1)
                    if gn2 and gn2 not in grammar_notes:
                        grammar_notes.append(gn2)

                patterns.append({
                    "grammar_tag": tag,
                    "pattern_formulas": grammar_notes[:3],
                    "examples": examples,
                    "total_sentences": len(nids),
                })

            return json.dumps({
                "patterns": patterns,
                "total_grammar_tags": len(tag_groups),
                "total_grammar_sentences": len(grammar_ids),
            }, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"error": str(e)})
        finally:
            col.close()

    # All remaining tools need the collection
    col = open_collection()
    try:
        if tool_name == "search_notes":
            query = tool_input["query"]
            note_ids = list(col.find_notes(query))
            if len(note_ids) <= 200:
                # Three DISJOINT sets, because they call for three different actions.
                # import_pool: parked xiehanzi import notes -- ignore them outright.
                # archived: the user's OWN notes parked under Hidden:: -- promote, never
                #   ignore and never re-create; 30,556 of 49,930 vocabulary notes are here.
                # live: in an active study deck.
                imported = _import_pool_note_ids(col, note_ids)
                archived = _archived_note_ids(col, note_ids) - imported
                return json.dumps({
                    "count": len(note_ids),
                    "import_pool_note_ids": sorted(imported),
                    "archived_note_ids": sorted(archived),
                    "live_note_ids": [n for n in note_ids
                                      if n not in archived and n not in imported],
                })
            else:
                imported = _import_pool_note_ids(col, note_ids)
                archived = _archived_note_ids(col, note_ids) - imported
                return json.dumps({
                    "count": len(note_ids),
                    "note_ids_truncated": True,
                    "import_pool_count": len(imported),
                    "archived_count": len(archived),
                    "live_count": len(note_ids) - len(imported) - len(archived),
                    "sample_live_ids": [n for n in note_ids
                                        if n not in archived and n not in imported][:10],
                })

        elif tool_name == "get_notes_detail":
            note_ids = tool_input["note_ids"][:100]
            today = col.sched.today
            # Computed once, by the SAME helper delete_notes and search_notes use. This
            # was re-derived from resolved deck names, so the two definitions could
            # disagree and the model would see archived:false while delete_notes refused.
            imported = _import_pool_note_ids(col, note_ids)
            archived = _archived_note_ids(col, note_ids) - imported
            results = []
            for nid in note_ids:
                try:
                    note = col.get_note(nid)
                    model = note.note_type()
                    field_names = [f["name"] for f in model["flds"]]
                    cards = note.cards()
                    # A note spans decks -- the live ChineseVocabulary note for a word
                    # has its forward card in HSK, its cloze in Vocab Cloze, and its
                    # production card in Reverse or still parked under Hidden::.
                    # Reporting cards[0] alone hid that.
                    deck_names = list(dict.fromkeys(col.decks.name(c.odid or c.did)
                                                    for c in cards))
                    deck_name = deck_names[0] if deck_names else "Unknown"
                    fields = {}
                    for i, name in enumerate(field_names):
                        if i < len(note.fields):
                            fields[name] = strip_html(note.fields[i])
                    results.append({
                        "note_id": nid,
                        "fields": fields,
                        "tags": note.tags,
                        "deck": deck_name,
                        "decks": deck_names,
                        # archived: the USER'S OWN note, parked under Hidden:: -- promote
                        # it, never ignore it and never re-create it as a new card.
                        # import_pool: a parked xiehanzi import artefact -- ignore it.
                        # The two are disjoint and call for opposite actions.
                        "archived": nid in archived,
                        "import_pool": nid in imported,
                        "note_type": model["name"],
                        # Per-card state, so the standing loop can decide whether to
                        # offer to move the card to the front. That offer only means
                        # something for a NEW card; a review card is in rotation.
                        "card_states": [
                            _card_state(col, c, model["tmpls"][c.ord]["name"], today)
                            for c in cards
                        ],
                        # A note counts as suspended only if EVERY card is. This bot
                        # suspends the reverse (ord 1) and cloze (ord 2) siblings on
                        # purpose -- see tag_hanly_notes and the maturity gate -- so
                        # any() called ~78% of actively-studied notes suspended while
                        # their forward card was live and in review.
                        "suspended": bool(cards) and all(c.queue == -1 for c in cards),
                        "suspended_templates": [model["tmpls"][c.ord]["name"]
                                                for c in cards if c.queue == -1],
                    })
                except Exception as e:
                    results.append({"note_id": nid, "error": str(e)})
            return json.dumps(results, ensure_ascii=False)

        elif tool_name == "get_field_values":
            query = tool_input.get("query", "")
            note_ids = list(col.find_notes(query))[:5000]
            field_names_requested = tool_input.get("fields", [])
            results = []
            for nid in note_ids:
                try:
                    note = col.get_note(nid)
                    model = note.note_type()
                    field_names = [f["name"] for f in model["flds"]]
                    entry = {"id": nid}
                    for fname in field_names_requested:
                        if fname in field_names:
                            idx = field_names.index(fname)
                            entry[fname] = strip_html(note.fields[idx]) if idx < len(note.fields) else ""
                    results.append(entry)
                except Exception:
                    results.append({"id": nid, "_error": "not found"})
            return json.dumps(results, ensure_ascii=False)

        elif tool_name == "list_decks":
            decks = col.decks.all_names_and_ids()
            result = []
            for d in decks:
                count = len(col.find_cards(f'"deck:{d.name}"'))
                result.append({"name": d.name, "cards": count})
            return json.dumps(result, ensure_ascii=False)

        elif tool_name == "list_note_types":
            models = col.models.all_names_and_ids()
            result = []
            for m in models:
                model = col.models.get(m.id)
                field_names = [f["name"] for f in model["flds"]]
                result.append({"name": m.name, "fields": field_names})
            return json.dumps(result, ensure_ascii=False)

        elif tool_name == "suspend_cards":
            query = tool_input["query"]
            note_ids = list(col.find_notes(query))
            card_ids, skipped = _collect_card_ids(col, note_ids)
            col.sched.suspend_cards(card_ids)
            log_change("suspend", note_ids, {"card_count": len(card_ids)})
            msg = f"Suspended {len(card_ids)} card(s) across {len(note_ids) - skipped} note(s)."
            if skipped:
                msg += f" ({skipped} missing notes skipped)"
            return msg

        elif tool_name == "unsuspend_cards":
            query = tool_input["query"]
            note_ids = list(col.find_notes(query))
            card_ids, skipped = _collect_card_ids(col, note_ids)
            col.sched.unsuspend_cards(card_ids)
            log_change("unsuspend", note_ids, {"card_count": len(card_ids)})
            msg = f"Unsuspended {len(card_ids)} card(s) across {len(note_ids) - skipped} note(s)."
            if skipped:
                msg += f" ({skipped} missing notes skipped)"
            return msg

        elif tool_name == "delete_notes":
            query = tool_input["query"]
            note_ids = list(col.find_notes(query))
            # The Hidden:: pools are parked on purpose and read as duplicates of the
            # live card (same word, same `Simplified` field). Refuse the whole call
            # rather than delete a subset, so the model has to come back explicitly.
            if not tool_input.get("include_archived"):
                archived = _archived_note_ids(col, note_ids)
                if archived:
                    return json.dumps({
                        "error": "refused",
                        "reason": f"{len(archived)} of {len(note_ids)} matched note(s) are "
                                  "archived: every card sits in a Hidden:: deck, where the "
                                  "user parks legacy import pools. They are not duplicates "
                                  "of the live card. Deleting them fixes nothing.",
                        "archived_note_ids": sorted(archived)[:50],
                        "archived_count": len(archived),
                        # Capped: an uncapped list sent 188 KB (12,436 ids) into the model
                        # context for a `deck:Hidden` query.
                        "live_note_ids": [n for n in note_ids if n not in archived][:50],
                        "live_count": len(note_ids) - len(archived),
                        "next_step": "Tell the user which notes are archived and leave them "
                                     "alone. To delete only the live ones, re-issue with a "
                                     "query built from the live ids, e.g. "
                                     "`nid:123,456`. Pass include_archived=true only if the "
                                     "user explicitly asks to delete archived notes.",
                    }, ensure_ascii=False)
            col.remove_notes(note_ids)
            log_change("delete", note_ids)
            return f"Deleted {len(note_ids)} note(s)."

        elif tool_name == "tag_notes":
            query = tool_input["query"]
            tags = tool_input.get("tags", [])
            note_ids = list(col.find_notes(query))
            adding_hanly = "hanly" in [t.lower() for t in tags]
            adding_mined = "mined" in [t.lower() for t in tags]

            if adding_mined:
                result = promote_to_vocab(col, note_ids)
                other_tags = [t for t in tags if t.lower() != "mined"]
                if other_tags:
                    for nid in note_ids:
                        try:
                            note = col.get_note(nid)
                            existing = {t.lower() for t in note.tags}
                            for tag in other_tags:
                                if tag.lower() not in existing:
                                    note.tags.append(tag)
                            col.update_note(note)
                        except Exception:
                            pass
                log_change("tag", note_ids, {"tags": tags})
                msg = (f"Tagged {result['tagged']} note(s) 'mined'. Put "
                       f"{result['repositioned_to_front']} new card(s) first among the NEW "
                       f"cards of their own deck (due cards still come before them). Kept "
                       f"{result['kept_in_deck']} card(s) in the study deck they were "
                       f"already in; moved {result['moved_to_mined']} card(s) into Mined. "
                       f"Routed {result['reverse_routed']} production and "
                       f"{result['cloze_routed']} cloze card(s) to their gated decks, "
                       f"suspending {result['reverse_suspended']} of them.")
                if result["forward_unsuspended"]:
                    # Some parked cards are parked on purpose (the ~164 basic HSK
                    # characters). Unsuspending one silently is how a deliberate decision
                    # gets undone without anyone noticing.
                    msg += (f" UNSUSPENDED {result['forward_unsuspended']} card(s) that "
                            "were suspended — say so explicitly, in case any was parked "
                            "on purpose.")
                if result["skipped_import_pool"]:
                    msg += (f" Skipped {result['skipped_import_pool']} parked import-pool "
                            "note(s); they are not the user's cards.")
                if result["already_in_review"]:
                    msg += (f" {result['already_in_review']} card(s) are already in "
                            "learning or review, so their schedule and their position "
                            "were left untouched.")
                if result["decks_missing"]:
                    msg += (" WARNING: no deck named "
                            + " or ".join(repr(n) for n in result["decks_missing"])
                            + " exists, so that routing was skipped.")
                return msg
            elif adding_hanly:
                result = promote_to_hanly(col, note_ids)
                # Also add any non-hanly tags
                other_tags = [t for t in tags if t.lower() != "hanly"]
                if other_tags:
                    for nid in note_ids:
                        try:
                            note = col.get_note(nid)
                            existing = {t.lower() for t in note.tags}
                            for tag in other_tags:
                                if tag.lower() not in existing:
                                    note.tags.append(tag)
                            col.update_note(note)
                        except Exception:
                            pass
                log_change("tag", note_ids, {"tags": tags})
                parts = [f"Tagged {result['tagged']} note(s) with hanly."]
                if result["forward_unsuspended"]:
                    parts.append(f"Unsuspended {result['forward_unsuspended']} forward card(s), "
                                 "wherever they already sat.")
                if result["reverse_suspended"]:
                    parts.append(f"Suspended {result['reverse_suspended']} reverse card(s), "
                                 "wherever they already sat.")
                parts.append(f"Moved {result['moved_to_hanly']} to hanly, {result['moved_to_hanly_reverse']} to hanly-reverse.")
                if result["decks_missing"]:
                    parts.append("WARNING: no deck named "
                                 + " or ".join(repr(n) for n in result["decks_missing"])
                                 + " exists, so no card changed deck. The 'hanly' tag is "
                                   "defunct in this collection — tell the user.")
                return " ".join(parts)
            else:
                skipped = 0
                for nid in note_ids:
                    try:
                        note = col.get_note(nid)
                        existing = {t.lower() for t in note.tags}
                        for tag in tags:
                            if tag.lower() not in existing:
                                note.tags.append(tag)
                        col.update_note(note)
                    except Exception:
                        skipped += 1
                log_change("tag", note_ids, {"tags": tags})
                msg = f"Tagged {len(note_ids) - skipped} note(s) with: {', '.join(tags)}"
                if skipped:
                    msg += f" ({skipped} missing notes skipped)"
                return msg

        elif tool_name == "remove_tags":
            query = tool_input["query"]
            tags = tool_input.get("tags", [])
            tags_lower = {t.lower() for t in tags}
            note_ids = list(col.find_notes(query))
            skipped = 0
            for nid in note_ids:
                try:
                    note = col.get_note(nid)
                    note.tags = [t for t in note.tags if t.lower() not in tags_lower]
                    col.update_note(note)
                except Exception:
                    skipped += 1
            log_change("remove_tag", note_ids, {"tags": tags})
            msg = f"Removed tags from {len(note_ids) - skipped} note(s): {', '.join(tags)}"
            if skipped:
                msg += f" ({skipped} missing notes skipped)"
            return msg

        elif tool_name == "move_cards":
            query = tool_input["query"]
            deck_name = tool_input.get("deck", "Default")
            note_ids = list(col.find_notes(query))
            did = col.decks.id_for_name(deck_name)
            if did is None:
                # Anki answers a None deck id with "your database appears to be in an
                # inconsistent state ... use Check Database", which is false and alarming.
                # Name the real problem and move nothing.
                return json.dumps({
                    "error": f"No deck named {deck_name!r}. Nothing was moved.",
                    "existing_decks": sorted(d.name for d in col.decks.all_names_and_ids()),
                }, ensure_ascii=False)
            card_ids, skipped = _collect_card_ids(col, note_ids)
            col.set_deck(card_ids, did)
            log_change("move_deck", note_ids, {"deck": deck_name, "card_count": len(card_ids)})
            return f"Moved {len(card_ids)} card(s) across {len(note_ids)} note(s) to: {deck_name}"

        elif tool_name == "edit_note":
            nid = tool_input["note_id"]
            new_fields = tool_input.get("fields", {})
            try:
                note = col.get_note(nid)
                model = note.note_type()
                field_names = [f["name"] for f in model["flds"]]
                updated = {}
                skipped = {}
                for fname, fval in new_fields.items():
                    if fname in field_names:
                        idx = field_names.index(fname)
                        old_val = strip_html(note.fields[idx])
                        note.fields[idx] = fval
                        updated[fname] = {"old": old_val[:100], "new": fval[:100]}
                    else:
                        skipped[fname] = f"field not found in note type '{model['name']}'"
                col.update_note(note)
                log_change("edit_note", [nid], {"fields_updated": list(updated.keys())})
                result = {"success": True, "note_id": nid, "updated": updated}
                if skipped:
                    result["skipped"] = skipped
                return json.dumps(result, ensure_ascii=False)
            except Exception as e:
                return json.dumps({"error": str(e)})

        elif tool_name == "get_note_type_templates":
            model = col.models.by_name(tool_input["note_type"])
            if not model:
                return json.dumps({"error": f"Note type '{tool_input['note_type']}' not found"})
            templates = []
            for t in model["tmpls"]:
                templates.append({"ord": t["ord"], "name": t["name"]})
            fields = [f["name"] for f in model["flds"]]
            return json.dumps({"note_type": tool_input["note_type"], "templates": templates, "fields": fields}, ensure_ascii=False)

        elif tool_name == "get_cards_info":
            note_ids = tool_input["note_ids"][:100]
            results = []
            for nid in note_ids:
                try:
                    note = col.get_note(nid)
                    model = note.note_type()
                    cards_info = []
                    for card in note.cards():
                        tmpl_name = model["tmpls"][card.ord]["name"]
                        queue_names = {-1: "suspended", 0: "new", 1: "learning", 2: "review", 3: "relearn"}
                        cards_info.append({
                            "card_id": card.id,
                            "template": tmpl_name,
                            "ord": card.ord,
                            "deck": col.decks.name(card.did),
                            "suspended": card.queue == -1,
                            "state": queue_names.get(card.queue, str(card.queue)),
                            "reviews": card.reps,
                        })
                    results.append({"note_id": nid, "cards": cards_info})
                except Exception as e:
                    results.append({"note_id": nid, "error": str(e)})
            return json.dumps(results, ensure_ascii=False)

        elif tool_name in ("suspend_card_type", "unsuspend_card_type"):
            query = tool_input["query"]
            template_name = tool_input["template_name"]
            note_ids = list(col.find_notes(query))
            card_ids = []
            for nid in note_ids:
                try:
                    note = col.get_note(nid)
                    model = note.note_type()
                    for card in note.cards():
                        if model["tmpls"][card.ord]["name"] == template_name:
                            card_ids.append(card.id)
                except Exception:
                    pass
            if not card_ids:
                return f"No '{template_name}' cards found for query: {query}"
            if tool_name == "suspend_card_type":
                col.sched.suspend_cards(card_ids)
                log_change("suspend_card_type", note_ids, {"template": template_name, "card_count": len(card_ids)})
                return f"Suspended {len(card_ids)} '{template_name}' card(s) across {len(note_ids)} note(s)."
            else:
                col.sched.unsuspend_cards(card_ids)
                log_change("unsuspend_card_type", note_ids, {"template": template_name, "card_count": len(card_ids)})
                return f"Unsuspended {len(card_ids)} '{template_name}' card(s) across {len(note_ids)} note(s)."

        elif tool_name == "move_card_type":
            query = tool_input["query"]
            template_name = tool_input["template_name"]
            deck_name = tool_input["deck"]
            note_ids = list(col.find_notes(query))
            # add_normal_deck_with_name CREATES the deck. A prompt naming a deck that no
            # longer exists would conjure it on preset 1 with different scheduling.
            try:
                did = deck_id(col, deck_name)
            except DeckMissing as e:
                return json.dumps({
                    "error": f"{e}. Nothing was moved.",
                    "existing_decks": sorted(d.name for d in col.decks.all_names_and_ids()),
                }, ensure_ascii=False)
            card_ids = []
            for nid in note_ids:
                try:
                    note = col.get_note(nid)
                    model = note.note_type()
                    for card in note.cards():
                        if model["tmpls"][card.ord]["name"] == template_name:
                            card_ids.append(card.id)
                except Exception:
                    pass
            if not card_ids:
                return f"No '{template_name}' cards found for query: {query}"
            col.set_deck(card_ids, did)
            log_change("move_card_type", note_ids, {"template": template_name, "deck": deck_name, "card_count": len(card_ids)})
            return f"Moved {len(card_ids)} '{template_name}' card(s) to deck '{deck_name}'."

        else:
            return json.dumps({"error": f"Unknown tool: {tool_name}"})
    finally:
        col.close()


# ── Conversation loop ─────────────────────────────────────────────────

async def run_conversation(chat_id, bot, message_obj):
    """Run the Claude conversation loop for a chat.
    Calls Claude with the full history, executes tools, and sends the final text reply.
    """
    # remember the last chat_id so scheduled jobs (e.g. weekly report) can reach the user
    try:
        with open(os.path.expanduser("~/.anki_chat_id"), "w") as _f:
            _f.write(str(chat_id))
    except Exception:
        pass
    MAX_TURNS = 20

    for turn in range(MAX_TURNS):
        await bot.send_chat_action(chat_id, "typing")

        history = chat_histories.get(chat_id, [])

        try:
            response = await asyncio.to_thread(
                claude.messages.create,
                model="claude-sonnet-4-5-20250929",
                max_tokens=4096,
                system=SYSTEM_PROMPT,
                tools=TOOLS + [{"type": "web_search_20250305", "name": "web_search", "max_uses": 3}],
                messages=history,
            )
        except anthropic.BadRequestError as e:
            error_msg = str(e).lower()
            if any(k in error_msg for k in ("too long", "too many tokens", "context length", "content size")):
                log.warning(f"Context too large for chat {chat_id}, trimming history and retrying")
                _trim_history(chat_id, max_messages=6, max_chars=50000)
                history = chat_histories.get(chat_id, [])
                try:
                    response = await asyncio.to_thread(
                        claude.messages.create,
                        model="claude-sonnet-4-5-20250929",
                        max_tokens=4096,
                        system=SYSTEM_PROMPT,
                        tools=TOOLS + [{"type": "web_search_20250305", "name": "web_search", "max_uses": 3}],
                        messages=history,
                    )
                except Exception as retry_err:
                    log.error(f"Retry after trim also failed: {retry_err}")
                    chat_histories[chat_id] = chat_histories.get(chat_id, [])[-2:]
                    await message_obj.reply_text(
                        "History was too large. I've cleared most of it — please try again."
                    )
                    return
            else:
                log.error(f"Claude API error: {e}")
                await message_obj.reply_text(f"Claude API error: {e}")
                return
        except Exception as e:
            log.error(f"Claude API error: {e}")
            await message_obj.reply_text(f"Claude API error: {e}")
            return

        # Separate tool use blocks and text blocks
        tool_use_blocks = [b for b in response.content if b.type == "tool_use"]
        text_blocks = [b for b in response.content if hasattr(b, "text") and b.text.strip()]

        if not tool_use_blocks:
            # Text-only response — send to user and done
            text = "\n\n".join(b.text for b in text_blocks) if text_blocks else "I'm not sure how to help with that."
            # Append assistant response to history
            chat_histories.setdefault(chat_id, []).append({"role": "assistant", "content": text})
            _trim_history(chat_id)
            try:
                await send_long_message(message_obj, text, parse_mode="Markdown")
            except Exception:
                await send_long_message(message_obj, text)
            return

        # Has tool calls — execute them
        # Build assistant content as dicts for the API
        assistant_content = []
        for block in response.content:
            if block.type == "text":
                assistant_content.append({"type": "text", "text": block.text})
            elif block.type == "tool_use":
                assistant_content.append({
                    "type": "tool_use",
                    "id": block.id,
                    "name": block.name,
                    "input": block.input,
                })
            # Skip server-side tool blocks (web_search) — handled within single API call

        chat_histories.setdefault(chat_id, []).append({"role": "assistant", "content": assistant_content})

        # Send any thinking/status text to user
        for block in text_blocks:
            try:
                await send_long_message(message_obj, block.text, parse_mode="Markdown")
            except Exception:
                await send_long_message(message_obj, block.text)

        # Execute each tool
        tool_results = []
        for block in tool_use_blocks:
            log.info(f"Tool call: {block.name}({json.dumps(block.input, ensure_ascii=False)[:200]})")
            try:
                result = execute_tool(block.name, block.input)
            except Exception as e:
                log.error(f"Tool error ({block.name}): {e}")
                result = json.dumps({"error": str(e)})

            tool_results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": _truncate_content(result),
            })

        # Append tool results to history
        chat_histories[chat_id].append({"role": "user", "content": tool_results})
        _trim_history(chat_id)

    # Hit max turns
    await message_obj.reply_text("Reached maximum conversation turns. Please try again.")


# ── API conversation loop ─────────────────────────────────────────────

async def run_api_conversation(word: str, context: str = "") -> dict:
    """Run Claude conversation loop for API card creation. Returns result dict."""
    session_id = f"api_{uuid.uuid4().hex[:8]}"
    prompt = f"Process this word for my Anki collection: {word}"
    if context:
        prompt += f"\nContext: {context}"

    chat_histories[session_id] = [{"role": "user", "content": prompt}]

    MAX_TURNS = 10
    final_text = ""

    try:
        for turn in range(MAX_TURNS):
            history = chat_histories.get(session_id, [])

            try:
                response = await asyncio.to_thread(
                    claude.messages.create,
                    model="claude-sonnet-4-5-20250929",
                    max_tokens=2048,
                    system=API_SYSTEM_PROMPT,
                    tools=API_TOOLS,
                    messages=history,
                )
            except Exception as e:
                log.error(f"API Claude error: {e}")
                return {"status": "error", "message": str(e)}

            tool_use_blocks = [b for b in response.content if b.type == "tool_use"]
            text_blocks = [b for b in response.content if hasattr(b, "text") and b.text.strip()]

            if not tool_use_blocks:
                # Final text response
                final_text = "\n\n".join(b.text for b in text_blocks) if text_blocks else ""
                break

            # Build assistant content
            assistant_content = []
            for block in response.content:
                if block.type == "text":
                    assistant_content.append({"type": "text", "text": block.text})
                elif block.type == "tool_use":
                    assistant_content.append({
                        "type": "tool_use",
                        "id": block.id,
                        "name": block.name,
                        "input": block.input,
                    })

            chat_histories[session_id].append({"role": "assistant", "content": assistant_content})

            # Execute tools
            tool_results = []
            for block in tool_use_blocks:
                log.info(f"API tool call: {block.name}({json.dumps(block.input, ensure_ascii=False)[:200]})")
                try:
                    result = execute_tool(block.name, block.input)
                except Exception as e:
                    log.error(f"API tool error ({block.name}): {e}")
                    result = json.dumps({"error": str(e)})

                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": _truncate_content(result),
                })

            chat_histories[session_id].append({"role": "user", "content": tool_results})

        # Parse JSON from Claude's final response
        try:
            return json.loads(final_text)
        except (json.JSONDecodeError, ValueError):
            return {"status": "completed", "message": final_text}

    finally:
        # Clean up ephemeral session
        chat_histories.pop(session_id, None)


# ── HTTP API server ───────────────────────────────────────────────────

def _bearer_token(header_value):
    """Token out of an `Authorization: Bearer <token>` header, or None if the scheme
    isn't Bearer. A bare `Bearer` with nothing after it yields "" (not None) so it
    compares equal to an empty API_KEY.

    This exists because the previous check was `auth != f'Bearer {API_KEY}'` — a raw
    string compare against the *whole* header. With API_KEY empty that expects the
    literal `'Bearer '` WITH a trailing space, so callers only authenticated if their
    HTTP client preserved trailing header whitespace. curl, urllib and node-fetch do;
    the WHATWG fetch spec says to strip it, so Node's built-in fetch (undici) sends
    `'Bearer'` and got a 401. Auth correctness must not depend on which client the
    caller happens to use, so parse the token and compare that instead."""
    parts = (header_value or "").strip().split(None, 1)
    if not parts or parts[0].lower() != "bearer":
        return None
    return parts[1].strip() if len(parts) > 1 else ""


@web.middleware
async def auth_middleware(request, handler):
    if request.path.startswith('/api/'):
        if _bearer_token(request.headers.get('Authorization', '')) != API_KEY:
            return web.json_response({"error": "unauthorized"}, status=401)
    return await handler(request)


async def handle_api_card(request):
    """POST /api/card — create or improve a card for a word."""
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid JSON"}, status=400)

    word = body.get("word", "").strip()
    ctx = body.get("context", "")
    if not word:
        return web.json_response({"error": "word is required"}, status=400)

    log.info(f"API request: word={word!r}")
    result = await run_api_conversation(word, ctx)
    return web.json_response(result, dumps=lambda obj: json.dumps(obj, ensure_ascii=False))


async def handle_health(request):
    return web.json_response({"status": "ok"})


# ── /api/status: read-only cross-reference for the dictionary site ─────
# Snapshot of every ChineseVocabulary headword -> {deck, interval}, rebuilt at
# most once per TTL so search-driven status checks never open the collection on
# every keystroke (and never contend with anki_op.sh writers). Plus a count of
# prior reader lookups per word as a mining signal.
READER_LOOKUPS = "/home/vincent/anki-headless/freq_data/reader_lookups.jsonl"
DICT_LOOKUPS = "/home/vincent/chinese-projects/chinese-dict/dict_lookups.jsonl"
# Live tap/save events from the dong reader (web + iOS) — the jsonl above froze
# 2026-06-19 when dong's server took over event logging, so this is where the
# reader signal actually accrues now. Read-only; owner's accounts (web=1, Apple=3).
DONG_DB = "/home/vincent/chinese-projects/dong-chinese/server/dongchinese.db"
_status_cache = {"ts": 0.0, "map": {}}
_lookup_cache = {"sig": None, "counts": {}}
STATUS_TTL = 60.0


def _vocab_status_map():
    """{simplified -> {deck, interval}} for all ChineseVocabulary notes (cached).

    Best-effort: if the collection is briefly locked (e.g. the bot's own periodic
    sync holds it open), serve the last snapshot instead of raising. Never 500s."""
    now = time.time()
    if _status_cache["map"] and now - _status_cache["ts"] < STATUS_TTL:
        return _status_cache["map"]
    try:
        col = open_collection()
    except Exception as e:
        log.warning(f"status map: collection unavailable ({e}); serving cached snapshot")
        return _status_cache["map"]
    try:
        # field 0 of ChineseVocabulary is Simplified (verified against notetype)
        rows = col.db.all(
            "SELECT n.flds, c.ivl, c.did FROM notes n "
            "JOIN notetypes nt ON nt.id = n.mid "
            "JOIN cards c ON c.nid = n.id WHERE nt.name = 'ChineseVocabulary'")
        deck_names = {}
        m = {}
        for flds, ivl, did in rows:
            w = flds.split("\x1f", 1)[0].strip()
            if not w:
                continue
            prev = m.get(w)
            if prev is None or ivl > prev["interval"]:
                if did not in deck_names:
                    deck_names[did] = col.decks.name(did)
                m[w] = {"deck": deck_names[did], "interval": ivl}
    except Exception as e:
        log.warning(f"status map: rebuild failed ({e}); serving cached snapshot")
        return _status_cache["map"]
    finally:
        col.close()
    _status_cache.update(ts=now, map=m)
    return m


def _lookup_counts():
    """{word -> times looked up} across the legacy jsonl logs + dong's live
    reading_events (tap/save). Cached by the files' stat signature — dongchinese.db
    is WAL so its mtime/size move on every write, which is exactly the busting we want."""
    sig = []
    for p in (READER_LOOKUPS, DICT_LOOKUPS, DONG_DB):
        try:
            st = os.stat(p)
            sig.append((p, st.st_mtime, st.st_size))
        except OSError:
            sig.append((p, 0, 0))
    sig = tuple(sig)
    if sig == _lookup_cache["sig"]:
        return _lookup_cache["counts"]
    counts = {}
    for p in (READER_LOOKUPS, DICT_LOOKUPS):
        try:
            with open(p, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        w = json.loads(line).get("word", "")
                    except Exception:
                        continue
                    if w:
                        counts[w] = counts.get(w, 0) + 1
        except OSError:
            pass
    try:
        con = sqlite3.connect(f"file:{DONG_DB}?mode=ro", uri=True)
        try:
            for w, n in con.execute(
                    "SELECT word, COUNT(*) FROM reading_events "
                    "WHERE user_id IN (1,3) AND kind IN ('tap','save') "
                    "AND word IS NOT NULL AND word<>'' GROUP BY word"):
                counts[w] = counts.get(w, 0) + n
        finally:
            con.close()
    except Exception as e:
        log.warning(f"lookup counts: dong reading_events unavailable ({e})")
    _lookup_cache.update(sig=sig, counts=counts)
    return counts


async def handle_api_status(request):
    """GET /api/status?words=a,b,c — per-word Anki + lookup status. Read-only."""
    raw = request.query.get("words", "").strip()
    if not raw:
        return web.json_response({})
    words = [w for w in (x.strip() for x in raw.split(",")) if w][:200]
    smap = await asyncio.to_thread(_vocab_status_map)
    counts = _lookup_counts()
    out = {}
    for w in words:
        info = smap.get(w)
        out[w] = {
            "in_deck": info is not None,
            "deck": info["deck"] if info else None,
            "interval": info["interval"] if info else None,
            "lookup_count": counts.get(w, 0),
        }
    return web.json_response(out, dumps=lambda o: json.dumps(o, ensure_ascii=False))


# ── /api/stats & /api/deck/{name}/words: dashboard read-only endpoints ─────
# Same computation as chinese-dashboard/build_stats.py's anki_stats()/_progression(),
# generalized over arbitrary deck names/note types instead of the hardcoded
# Vocab/Mined backbone. Kept independent of build_stats.py on purpose: that script
# still owns writing the static dashboard snapshot; this just exposes the same
# numbers live over HTTP so the dashboard can query them directly.
PDT_OFFSET = 7 * 3600  # matches build_stats.OFF: PDT day bucketing
_stats_cache = {}  # (deck_names_tuple, model_name) -> {"ts": float, "data": dict}
STATS_CACHE_TTL = 60.0


def _stats_day(ts_s):
    return time.strftime("%Y-%m-%d", time.gmtime(ts_s - PDT_OFFSET))


def _stats_progression(col, deck_ids, cv_id, now):
    """Weekly card-maturity composition, reconstructed from the review log.

    Ported unchanged from build_stats._progression (see there for the full
    rationale); deck_ids/cv_id are already resolved ints here."""
    import bisect
    if not deck_ids:
        return []
    ph = ",".join("?" * len(deck_ids))
    rows = col.db.all(
        f"SELECT r.cid, r.id, r.ivl, r.type FROM revlog r JOIN cards c ON r.cid=c.id "
        f"WHERE c.did IN ({ph}) AND c.ord=0 AND c.nid IN (SELECT id FROM notes WHERE mid=?) "
        f"AND r.ease>0 ORDER BY r.id", *deck_ids, cv_id)
    if not rows:
        return []
    per = collections.defaultdict(list)
    for cid, rid, ivl, typ in rows:
        per[cid].append((rid, ivl, typ))
    per = {c: (lg := sorted(v), [x[0] for x in lg]) for c, v in per.items()}

    def bucket(ivl, typ):
        if typ == 2: return "Relearning"   # mid-lapse
        if ivl <= 0: return "Learning"      # sub-day step
        return "Young" if ivl < 21 else "Mature"

    first = rows[0][1] / 1000
    d0 = first - ((first - PDT_OFFSET) % 86400)   # midnight (PDT frame) of first-review day
    out, b = [], d0
    while b <= now + 7 * 86400:
        ms = b * 1000
        c = {"Mature": 0, "Young": 0, "Learning": 0, "Relearning": 0}
        for logs, times in per.values():
            i = bisect.bisect_right(times, ms) - 1
            if i < 0:
                continue
            _, ivl, typ = logs[i]
            c[bucket(ivl, typ)] += 1
        out.append({"date": time.strftime("%Y-%m-%d", time.gmtime(b - PDT_OFFSET)), **c})
        b += 7 * 86400
    return out


def _deck_stats(deck_names, model_name, now, days_window=30):
    """Core of GET /api/stats. Opens the collection once and computes counts, per-card
    word lists, weekly/daily review activity and maturity progression jointly over
    `deck_names`. A deck name absent from the collection (col.decks.id_for_name
    returns None) comes back as an all-zero/empty block, matching build_stats'
    handling of a missing deck exactly — not an error. Same for a missing model name
    (col.models.by_name returns None): the -1 sentinel id just matches nothing.
    `days_window` sets the daily-series window (default 30 — the historical
    contract); the dashboard's range views request more via ?days=."""
    col = open_collection()
    try:
        cv = col.models.by_name(model_name)
        cv_id = cv["id"] if cv else -1
        deck_ids = {name: col.decks.id_for_name(name) for name in deck_names}

        def deck_counts(did):
            if did is None:
                return {"total": 0, "studied": 0, "mature": 0, "new_left": 0, "new_per_day": 0}
            q = "SELECT %s FROM cards WHERE did=? AND ord=0 AND nid IN (SELECT id FROM notes WHERE mid=?)"
            total = col.db.scalar(q % "COUNT(*)", did, cv_id)
            studied = col.db.scalar(q % "COUNT(*)" + " AND type IN (1,2)", did, cv_id)
            mature = col.db.scalar(q % "COUNT(*)" + " AND type=2 AND ivl>=21", did, cv_id)
            new_left = col.db.scalar(q % "COUNT(*)" + " AND type=0 AND queue!=-1", did, cv_id)
            # The deck's CONFIGURED new-cards/day, read from whichever options preset the
            # deck is assigned to (they're shared — see DECK_REFERENCE). The dashboard
            # projects HSK completion from this rather than from observed new-card counts:
            # observed counts include other decks and lag any limit change by ~30 days,
            # so they answer "what did I do" when the projection needs "what will I do".
            new_per_day = col.decks.config_dict_for_deck_id(did)["new"]["perDay"]
            return {"total": total, "studied": studied, "mature": mature,
                    "new_left": new_left, "new_per_day": new_per_day}

        def deck_words(did):
            # Full per-card list for drill-down: compact {w:word, p:pinyin, s:status}.
            # status: 2=mature (type 2, ivl>=21), 1=studied/learning (type 1/2), 0=new.
            if did is None:
                return []
            out = []
            for sfld, flds, ctype, ivl in col.db.all(
                    "SELECT n.sfld, n.flds, c.type, c.ivl FROM cards c JOIN notes n ON n.id=c.nid "
                    "WHERE c.did=? AND c.ord=0 AND n.mid=? ORDER BY n.id DESC", did, cv_id):
                parts = flds.split("\x1f")
                pinyin = parts[1] if len(parts) > 1 else ""
                s = 2 if (ctype == 2 and ivl >= 21) else (1 if ctype in (1, 2) else 0)
                out.append({"w": sfld, "p": pinyin, "s": s})
            return out

        decks_out = {}
        for name in deck_names:
            block = deck_counts(deck_ids[name])
            block["words"] = deck_words(deck_ids[name])
            decks_out[name] = block

        valid_ids = [did for did in deck_ids.values() if did is not None]

        days = collections.OrderedDict()
        for i in range(days_window - 1, -1, -1):
            d = _stats_day(now - i * 86400)
            days[d] = {"date": d, "reviews": 0, "new": 0, "ms": 0}
        recent = {name: [] for name in deck_names}
        week = {"reviews": 0, "retention": None}
        progression = []

        if valid_ids:
            ph = ",".join("?" * len(valid_ids))
            # r.ease>0 excludes manual/reschedule revlog rows (ease=0, e.g. an FSRS bulk
            # reschedule writes one per card) — those aren't reviews and would inflate counts.
            wk_ms = (now - 7 * 86400) * 1000
            rl = col.db.all(
                f"SELECT r.id, r.ease, r.type, r.lastIvl FROM revlog r JOIN cards c ON r.cid=c.id "
                f"WHERE r.id>? AND c.did IN ({ph}) AND c.ord=0 AND r.ease>0", wk_ms, *valid_ids)
            reviews = len(rl)
            mature_revs = [e for _, e, t, liv in rl if liv >= 21 and t in (1, 2)]
            retention = round(100 * sum(1 for e in mature_revs if e >= 2) / len(mature_revs)) if mature_revs else None
            week = {"reviews": reviews, "retention": retention}

            # r.time = milliseconds spent on that one review (Anki caps it per-card at the
            # deck's max-answer-seconds, so a walk-away can't inflate it). Summed per day it
            # gives real Anki study MINUTES — the unit reading/listening/video/writing already
            # report, which is what lets the dashboard stack all five activities on one axis
            # instead of pairing reviews against minutes on a second scale.
            m30 = (now - days_window * 86400) * 1000
            for rid, ease, rtype, liv, rtime in col.db.all(
                    f"SELECT r.id, r.ease, r.type, r.lastIvl, r.time FROM revlog r JOIN cards c ON r.cid=c.id "
                    f"WHERE r.id>? AND c.did IN ({ph}) AND c.ord=0 AND r.ease>0", m30, *valid_ids):
                d = time.strftime("%Y-%m-%d", time.gmtime(rid / 1000 - PDT_OFFSET))
                if d in days:
                    days[d]["reviews"] += 1
                    days[d]["ms"] += rtime or 0
                    if rtype == 0: days[d]["new"] += 1

            for name in deck_names:
                did = deck_ids[name]
                if did is None:
                    continue
                recent[name] = [r[0] for r in col.db.all(
                    "SELECT n.sfld FROM notes n JOIN cards c ON c.nid=n.id "
                    "WHERE c.did=? AND c.ord=0 AND n.mid=? ORDER BY n.id DESC LIMIT 20",
                    did, cv_id)]

            progression = _stats_progression(col, valid_ids, cv_id, now)

        # ms is an accumulator, not part of the contract — emit whole minutes like every
        # other source and drop it, so `daily` stays {date, reviews, new, minutes}. Runs
        # outside `if valid_ids` so a missing deck still yields 0-minute days, not KeyError.
        for v in days.values():
            v["minutes"] = round(v.pop("ms") / 60000)

        return {"decks": decks_out, "recent": recent, "week": week,
                "daily": list(days.values()), "progression": progression}
    finally:
        col.close()


def _cached_deck_stats(deck_names, model_name, days_window=30):
    """Best-effort cache wrapper around _deck_stats: if the collection is briefly
    locked, serve the last snapshot instead of raising — same idea as
    _vocab_status_map. Only propagates the exception when there's nothing cached."""
    key = (tuple(deck_names), model_name, days_window)
    now = time.time()
    cached = _stats_cache.get(key)
    if cached and now - cached["ts"] < STATS_CACHE_TTL:
        return cached["data"]
    try:
        data = _deck_stats(deck_names, model_name, now, days_window)
    except Exception as e:
        log.warning(f"deck stats: collection unavailable ({e}); serving cached snapshot")
        if cached:
            return cached["data"]
        raise
    _stats_cache[key] = {"ts": now, "data": data}
    return data


async def handle_api_stats(request):
    """GET /api/stats?decks=Vocab,Mined&model=ChineseVocabulary — read-only deck
    progress + review activity, for the dashboard. Cached ~60s per (decks, model)."""
    # Default to the real study decks. The old "Vocab" deck was retired in the deck reorg
    # (see DECOUPLING_PLAN.md); a bare call defaulting to it measured an empty deck. The
    # dashboard passes ?decks= explicitly, but the default must not be a dead deck.
    raw = request.query.get("decks", "HSK,HSK7-9,non-HSK,Mined")
    deck_names = [d.strip() for d in raw.split(",") if d.strip()] or ["HSK", "HSK7-9", "non-HSK", "Mined"]
    model_name = request.query.get("model", "ChineseVocabulary").strip() or "ChineseVocabulary"
    # ?days= widens the daily series (dashboard range views); default stays 30.
    try:
        days_window = max(1, min(3660, int(request.query.get("days", "30"))))
    except ValueError:
        days_window = 30
    try:
        data = await asyncio.to_thread(_cached_deck_stats, deck_names, model_name, days_window)
    except Exception as e:
        log.warning(f"/api/stats: collection unavailable ({e})")
        return web.json_response({"error": "collection locked"}, status=503)
    return web.json_response(data, dumps=lambda o: json.dumps(o, ensure_ascii=False))


async def handle_api_sync(request):
    """POST /api/sync — pull the latest reviews from AnkiWeb, then drop the stats
    cache so the next /api/stats reflects them. The dashboard's refresh endpoint
    calls this on page load so a reload shows reviews just done on another device.
    Runs the blocking sync off the event loop; the 5-minute periodic_sync still runs
    independently as the backstop."""
    result = await asyncio.to_thread(_sync_collection)
    _stats_cache.clear()
    _flagged_cache.clear()  # flags are edited on other devices too, not just reviews
    log.info(f"On-demand sync (dashboard): {result}")
    return web.json_response({"result": result})


def _deck_word_list(deck_name, model_name, ord_=0):
    """[{simplified, pinyin, meaning, status}] for one deck/model's cards at template
    `ord_` — same field extraction as _deck_stats' deck_words, plus the note's Meaning
    field (CHINESE_VOCAB_FIELDS field index 2).

    ord_ defaults to 0 (Hanzi-English, the recognition direction) — every caller
    predating this argument wants that. Pass 2 for Cloze-Recall, the production
    direction: `Vocab Cloze` holds *only* ord-2 cards, so an ord-0 query against it
    returns [] and looks indistinguishable from a missing deck (see DECK_REFERENCE —
    the note type is still ChineseVocabulary, the direction lives in the template)."""
    col = open_collection()
    try:
        cv = col.models.by_name(model_name)
        cv_id = cv["id"] if cv else -1
        did = col.decks.id_for_name(deck_name)
        if did is None:
            return []
        out = []
        for sfld, flds, ctype, ivl in col.db.all(
                "SELECT n.sfld, n.flds, c.type, c.ivl FROM cards c JOIN notes n ON n.id=c.nid "
                "WHERE c.did=? AND c.ord=? AND n.mid=? ORDER BY n.id DESC", did, ord_, cv_id):
            parts = flds.split("\x1f")
            pinyin = parts[1] if len(parts) > 1 else ""
            meaning = parts[2] if len(parts) > 2 else ""
            status = 2 if (ctype == 2 and ivl >= 21) else (1 if ctype in (1, 2) else 0)
            out.append({"simplified": sfld, "pinyin": pinyin, "meaning": meaning, "status": status})
        return out
    finally:
        col.close()


# ── /api/flagged: the hand-flagged "come back to this" pile ────────────────
# Anki keeps the flag colour in the low 3 bits of cards.flags (0 = unflagged, 1-7 in
# the order the Anki UI lists them); the upper bits are unrelated, so every read here
# masks with & 7.
#
# Deliberately NOT scoped to the study decks or the vocab note type the way
# /api/stats is: a flag is a hand-placed mark, so one left on a card in any deck is
# exactly the thing worth surfacing — scoping it would silently hide the flags most
# likely to be forgotten. Pinyin/meaning are only read for `model_name` notes (the
# field order is that note type's); other note types fall back to the sort field.
FLAG_NAMES = {1: "Red", 2: "Orange", 3: "Green", 4: "Blue",
              5: "Pink", 6: "Turquoise", 7: "Purple"}
_flagged_cache = {}  # model_name -> {"ts": float, "data": dict}
FLAGGED_CACHE_TTL = 60.0
_TAG_RE = re.compile(r"<!--.*?-->|<[^>]+>", re.S)


def _plain(s):
    """Field text with its HTML stripped — tone <span>s, <br>, and the trailing
    <!--zai yu--> the Chinese-support add-on leaves in Pinyin. Consumers escape what
    they render, so an unstripped field shows its own markup on the page."""
    return re.sub(r"\s+", " ", _TAG_RE.sub(" ", s or "")).strip()


def _flagged_cards(model_name):
    """{total, by_flag, cards} for every flagged card in the collection."""
    col = open_collection()
    try:
        cv = col.models.by_name(model_name)
        cv_id = cv["id"] if cv else -1
        dnames = {}

        def deck_name(did):
            if did not in dnames:
                dnames[did] = col.decks.name(did)
            return dnames[did]

        cards, counts = [], collections.Counter()
        # Ordered by flag then newest note first, so the list reads the way the flags
        # were meant to be worked through rather than in collection order.
        for flags, ord_, ctype, ivl, queue, did, mid, sfld, flds in col.db.all(
                "SELECT c.flags, c.ord, c.type, c.ivl, c.queue, c.did, n.mid, n.sfld, n.flds "
                "FROM cards c JOIN notes n ON n.id=c.nid "
                "WHERE c.flags & 7 > 0 ORDER BY c.flags & 7, n.id DESC"):
            f = flags & 7
            counts[f] += 1
            pinyin = meaning = ""
            if mid == cv_id:
                parts = flds.split("\x1f")
                pinyin = parts[1] if len(parts) > 1 else ""
                meaning = parts[2] if len(parts) > 2 else ""
            # Same `s` encoding as _deck_stats' deck_words (2=mature, 1=seen, 0=new), so
            # the dashboard can style a flagged word exactly like it does elsewhere.
            s = 2 if (ctype == 2 and ivl >= 21) else (1 if ctype in (1, 2) else 0)
            cards.append({"w": _plain(sfld), "p": _plain(pinyin), "m": _plain(meaning), "s": s,
                          "flag": f, "flag_name": FLAG_NAMES.get(f, str(f)),
                          "deck": deck_name(did), "ord": ord_,
                          "suspended": queue == -1})
        return {"total": len(cards),
                "by_flag": [{"flag": f, "name": FLAG_NAMES.get(f, str(f)), "count": n}
                            for f, n in sorted(counts.items())],
                "cards": cards}
    finally:
        col.close()


def _cached_flagged_cards(model_name):
    """Best-effort cache around _flagged_cards, same contract as _cached_deck_stats:
    a briefly-locked collection serves the last snapshot instead of raising."""
    now = time.time()
    cached = _flagged_cache.get(model_name)
    if cached and now - cached["ts"] < FLAGGED_CACHE_TTL:
        return cached["data"]
    try:
        data = _flagged_cards(model_name)
    except Exception as e:
        log.warning(f"flagged cards: collection unavailable ({e}); serving cached snapshot")
        if cached:
            return cached["data"]
        raise
    _flagged_cache[model_name] = {"ts": now, "data": data}
    return data


async def handle_api_flagged(request):
    """GET /api/flagged?model=ChineseVocabulary — every flagged card in the
    collection, grouped by flag colour. Read-only; cached ~60s per model."""
    model_name = request.query.get("model", "ChineseVocabulary").strip() or "ChineseVocabulary"
    try:
        data = await asyncio.to_thread(_cached_flagged_cards, model_name)
    except Exception as e:
        log.warning(f"/api/flagged: collection unavailable ({e})")
        return web.json_response({"error": "collection locked"}, status=503)
    return web.json_response(data, dumps=lambda o: json.dumps(o, ensure_ascii=False))


# ── /api/hsk-levels: per-HSK-3.0-level familiarity ─────────────────────────
# Denominator is the official HSK 3.0 word list (freq_data/hsk30_official.json, 10,978
# words over levels 1-6 and 7-9), NOT the HSK decks' contents — so a level's bar
# reads as "how much of HSK n do I actually know", including the words that have no
# card at all. Matching is by word (notes.sfld) across every non-Hidden deck rather
# than by the HSK::HSKn tag: an HSK word mined into Mined or sitting in non-HSK
# still counts, and suspended cards never do.
#
# The "none" bucket is mostly single characters on purpose: the HSK deck excludes
# single-char words (they're studied in the Hanly app, which this collection doesn't
# track), so `none_single` is reported separately and the dashboard says so.
HSK_VOCAB_PATH = "/home/vincent/anki-headless/freq_data/hsk30_official.json"
HSK_LEVELS = ("1", "2", "3", "4", "5", "6", "7-9")
_hsk_vocab_cache = None
_hsk_stats_cache = {"ts": 0.0, "data": None}


def _hsk_vocab():
    """{level: [{word, pinyin, gloss, ...}, ...]} from the HSK 3.0 list, file order,
    deduped by word within each level, loaded once."""
    global _hsk_vocab_cache
    if _hsk_vocab_cache is None:
        by_level = collections.defaultdict(list)
        seen = collections.defaultdict(set)
        with open(HSK_VOCAB_PATH, encoding="utf-8") as f:
            for entry in json.load(f):
                lvl = entry["level"]
                if entry["word"] not in seen[lvl]:
                    seen[lvl].add(entry["word"])
                    by_level[lvl].append(entry)
        _hsk_vocab_cache = dict(by_level)
    return _hsk_vocab_cache


def _hsk_level_stats():
    """Per-level familiarity buckets over the official HSK 3.0 vocabulary.

    A word's status is the *best* status of any of its ord=0 cards (a word can have
    both a ChineseVocabulary and a ChineseCharacters note), ranked
    new < learning < young < mature. Suspended cards (queue=-1) are ignored, so an
    archived-only word lands in "none" alongside words with no note at all.
    Buckets match the maturity language used everywhere else (ivl>=21 = mature)."""
    vocab = _hsk_vocab()
    col = open_collection()
    try:
        live_decks = {did for did, name in col.db.all("SELECT id, name FROM decks")
                      if "Hidden" not in name}
        rank = {"new": 0, "learning": 1, "young": 2, "mature": 3}
        best = {}
        for sfld, ctype, ivl, queue, did in col.db.all(
                "SELECT n.sfld, c.type, c.ivl, c.queue, c.did FROM cards c "
                "JOIN notes n ON n.id=c.nid WHERE c.ord=0 AND c.queue!=-1"):
            if did not in live_decks:
                continue
            if ctype == 2:
                st = "mature" if ivl >= 21 else "young"
            elif ctype in (1, 3):
                st = "learning"
            else:
                st = "new"
            if sfld not in best or rank[st] > rank[best[sfld]]:
                best[sfld] = st
    finally:
        col.close()

    levels = []
    for level in HSK_LEVELS:
        entries = vocab.get(level, [])
        counts = collections.Counter(best.get(e["word"], "none") for e in entries)
        # Split "none" by length: single chars are the Hanly-only ones (see above).
        none_single = sum(1 for e in entries if len(e["word"]) == 1 and e["word"] not in best)
        # Every word of the level in HSK-list order, each tagged with its status, so the
        # dashboard can list "which HSK 5 words haven't I started" and not just count
        # them. `s` uses the same encoding as /api/deck/{name}/words (2=mature,
        # 1=seen-but-not-solid, 0=has a card, never seen) plus -1 for "no card at all",
        # which is what the chart's Hanly segment counts.
        smap = {"mature": 2, "young": 1, "learning": 1, "new": 0}
        words = [{"w": e["word"], "p": e.get("pinyin", ""), "g": e.get("gloss", ""),
                  "s": smap.get(best.get(e["word"]), -1)} for e in entries]
        levels.append({"level": level, "total": len(entries),
                       "mature": counts["mature"], "young": counts["young"],
                       "learning": counts["learning"], "new": counts["new"],
                       "none": counts["none"], "none_single": none_single,
                       "words": words})
    return {"levels": levels}


def _cached_hsk_level_stats():
    """Same best-effort caching as _cached_deck_stats: serve the last snapshot if the
    collection is briefly locked, and only raise when there's nothing cached."""
    now = time.time()
    if _hsk_stats_cache["data"] and now - _hsk_stats_cache["ts"] < STATS_CACHE_TTL:
        return _hsk_stats_cache["data"]
    try:
        data = _hsk_level_stats()
    except Exception as e:
        log.warning(f"hsk level stats: collection unavailable ({e}); serving cached snapshot")
        if _hsk_stats_cache["data"]:
            return _hsk_stats_cache["data"]
        raise
    _hsk_stats_cache.update(ts=now, data=data)
    return data


async def handle_api_hsk_levels(request):
    """GET /api/hsk-levels — familiarity across HSK 3.0 levels 1-6 and 7-9."""
    try:
        data = await asyncio.to_thread(_cached_hsk_level_stats)
    except Exception as e:
        log.warning(f"/api/hsk-levels: collection unavailable ({e})")
        return web.json_response({"error": "collection locked"}, status=503)
    return web.json_response(data, dumps=lambda o: json.dumps(o, ensure_ascii=False))


async def handle_api_deck_words(request):
    """GET /api/deck/{name}/words?model=ChineseVocabulary&ord=0 — full per-card word
    list for one deck (drill-down for the dashboard). aiohttp already URL-decodes the
    {name} path segment. Missing deck -> {"deck": name, "words": []}, not an error.

    `ord` selects the card template and defaults to 0 (recognition), so callers that
    predate it are unaffected; comprehensiblemandarin's Write module passes ord=2 to
    read `Vocab Cloze`'s production-direction cards. A non-integer ord is a 400 rather
    than a silent fallback to 0 — quietly serving the recognition deck to a caller that
    asked for production would be wrong in exactly the way that's hard to notice."""
    deck_name = request.match_info["name"]
    model_name = request.query.get("model", "ChineseVocabulary").strip() or "ChineseVocabulary"
    raw_ord = request.query.get("ord", "0").strip() or "0"
    try:
        ord_ = int(raw_ord)
    except ValueError:
        return web.json_response({"error": f"ord must be an integer, got {raw_ord!r}"}, status=400)
    try:
        words = await asyncio.to_thread(_deck_word_list, deck_name, model_name, ord_)
    except Exception as e:
        log.warning(f"/api/deck/{deck_name}/words: collection unavailable ({e})")
        return web.json_response({"error": "collection locked"}, status=503)
    return web.json_response({"deck": deck_name, "ord": ord_, "words": words},
                              dumps=lambda o: json.dumps(o, ensure_ascii=False))


def create_web_app():
    app = web.Application(middlewares=[auth_middleware])
    app.router.add_post('/api/card', handle_api_card)
    app.router.add_get('/api/status', handle_api_status)
    app.router.add_get('/api/stats', handle_api_stats)
    app.router.add_post('/api/sync', handle_api_sync)
    app.router.add_get('/api/hsk-levels', handle_api_hsk_levels)
    app.router.add_get('/api/flagged', handle_api_flagged)
    app.router.add_get('/api/deck/{name}/words', handle_api_deck_words)
    app.router.add_get('/health', handle_health)
    return app


# ── Telegram handlers ─────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Anki Card Bot\n\n"
        "Send me a message and I'll help you create Anki cards or manage your collection.\n\n"
        "Examples:\n"
        "  `学习` — creates a Chinese vocab card\n"
        "  `好好学习天天向上` — Chinese phrase card\n"
        "  `mitochondria is the powerhouse of the cell` — general card\n"
        "  `suspend all cards tagged test` — collection management\n"
        "  `how many cards do I have?` — stats query\n\n"
        "Commands:\n"
        "  /status — due counts & recent additions\n"
        "  /decks — list available decks\n"
        "  /clear — clear conversation history\n"
        "  /help — usage guide",
        parse_mode="Markdown",
    )


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    col = open_collection()
    try:
        new_count = len(col.find_cards("is:new"))
        due_count = len(col.find_cards("is:due"))
        learn_count = len(col.find_cards("is:learn"))
        total = col.card_count()
        recent_count = len(col.find_notes("tag:claude"))

        msg = (
            f"Total cards: {total}\n"
            f"New: {new_count} | Learning: {learn_count} | Due: {due_count}\n\n"
            f"Cards tagged 'claude': {recent_count}"
        )
        await update.message.reply_text(msg)
    finally:
        col.close()


async def cmd_decks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    col = open_collection()
    try:
        decks = col.decks.all_names_and_ids()
        lines = []
        # The old filter was `d.name == "Default" or "::" in d.name`, which listed only
        # Default and subdecks -- every top-level study deck (HSK, HSK7-9, non-HSK,
        # Reverse, Vocab Cloze, Mined) was missing, and the `if not lines` fallback never
        # fired because Hidden::* always matched. List every deck that holds a card.
        for d in sorted(decks, key=lambda x: x.name):
            count = len(col.find_cards(f'"deck:{d.name}"'))
            if count > 0:
                lines.append(f"  {d.name} ({count})")
        await update.message.reply_text("Decks:\n" + "\n".join(lines[:30]))
    finally:
        col.close()


async def cmd_log(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not CHANGELOG_FILE.exists():
        await update.message.reply_text("No changes logged yet.")
        return
    lines = CHANGELOG_FILE.read_text().strip().split("\n")
    recent = lines[-20:]
    output = []
    for line in recent:
        entry = json.loads(line)
        ts = entry["ts"][5:19]
        action = entry["action"]
        count = entry.get("count", "")
        detail = ""
        if "simplified" in entry:
            detail = f" {entry['simplified']}"
        elif "front" in entry:
            detail = f" {entry['front']}"
        elif "tags_added" in entry:
            detail = f" +{','.join(entry['tags_added'])}"
        count_str = f" ({count})" if count else ""
        output.append(f"`{ts}` {action}{count_str}{detail}")
    await send_long_message(update.message, "\n".join(output), parse_mode="Markdown")


async def cmd_clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    cleared = []
    if chat_id in chat_histories:
        del chat_histories[chat_id]
        cleared.append("conversation history")
    if context.chat_data.get("json_buffer") is not None:
        context.chat_data["json_buffer"] = None
        cleared.append("JSON buffer")
    if cleared:
        await update.message.reply_text(f"Cleared: {', '.join(cleared)}")
    else:
        await update.message.reply_text("Nothing to clear.")


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Usage Guide\n\n"
        "Just send me text and I'll help:\n\n"
        "Chinese vocab: send Chinese characters (e.g. `考虑`)\n"
        "General card: describe what you want to learn\n"
        "Collection management: ask to search, suspend, tag, move cards\n"
        "Photos: send an image of Chinese text for OCR\n\n"
        "I'll always show you a preview before creating cards, "
        "and ask for confirmation before modifying your collection.\n\n"
        "Commands:\n"
        "  /status — collection stats\n"
        "  /decks — list decks\n"
        "  /clear — clear conversation history\n"
        "  /log — recent changes\n"
        "  /start — welcome message",
        parse_mode="Markdown",
    )


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle document uploads — try to parse any text-like document as JSON."""
    doc = update.message.document
    if not doc:
        return

    chat_id = update.effective_chat.id
    log.info(f"Received document: name={doc.file_name} mime={doc.mime_type} size={doc.file_size}")
    await context.bot.send_chat_action(chat_id, "typing")

    file = await context.bot.get_file(doc.file_id)
    async with httpx.AsyncClient() as client:
        resp = await client.get(file.file_path)
        content = resp.content

    try:
        data = json.loads(content)
    except (json.JSONDecodeError, UnicodeDecodeError):
        await update.message.reply_text(
            f"Couldn't parse as JSON (file: {doc.file_name}, type: {doc.mime_type}).\n"
            "Send a valid JSON file to analyze."
        )
        return

    await _process_json_text(update, context, chat_id, data)


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle photo messages — add image to conversation and let Claude handle it."""
    chat_id = update.effective_chat.id
    photo = update.message.photo[-1]  # Highest resolution
    caption = update.message.caption or ""

    log.info(f"Received photo (file_id={photo.file_id}, caption={caption!r})")
    await context.bot.send_chat_action(chat_id, "typing")

    # Download the photo
    file = await context.bot.get_file(photo.file_id)
    async with httpx.AsyncClient() as client:
        resp = await client.get(file.file_path)
        image_bytes = resp.content

    # Determine media type
    ext = file.file_path.rsplit(".", 1)[-1].lower() if "." in file.file_path else "jpg"
    media_types = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp"}
    media_type = media_types.get(ext, "image/jpeg")

    image_b64 = base64.b64encode(image_bytes).decode("utf-8")

    # Build multimodal message
    content = [
        {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": image_b64}},
    ]
    if caption:
        content.append({"type": "text", "text": caption})
    else:
        content.append({"type": "text", "text": "What Chinese words are in this image? Offer to create cards for them."})

    chat_histories.setdefault(chat_id, []).append({"role": "user", "content": content})
    _trim_history(chat_id)

    await run_conversation(chat_id, context.bot, update.message)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if not text:
        return

    chat_id = update.effective_chat.id
    log.info(f"Received: {text[:100]}...")

    # ── JSON buffering (handles Telegram splitting large pastes) ──
    stripped = text.strip()
    json_buf = context.chat_data.get("json_buffer")

    if json_buf is not None:
        json_buf.append(text)
        combined = "".join(json_buf).strip()
        log.info(f"JSON buffer: +{len(text)} chars, total {len(combined)}")

        try:
            data = json.loads(combined)
            context.chat_data["json_buffer"] = None
            _cancel_json_flush(context, chat_id)
            log.info(f"JSON complete ({len(combined)} chars), processing")
            await _process_json_text(update, context, chat_id, data)
            return
        except json.JSONDecodeError:
            _schedule_json_flush(update, context, chat_id)
            return

    # Detect new JSON starting
    is_json_start = (stripped.startswith("{") or stripped.startswith("[")) and len(stripped) > 100
    is_json_fragment = _looks_like_json_fragment(stripped) and len(stripped) > 200

    if is_json_start or is_json_fragment:
        if is_json_start:
            try:
                data = json.loads(stripped)
                log.info("Complete JSON in single message")
                await _process_json_text(update, context, chat_id, data)
                return
            except json.JSONDecodeError:
                pass

        context.chat_data["json_buffer"] = [text]
        log.info(f"Started JSON buffer ({len(stripped)} chars)")
        _schedule_json_flush(update, context, chat_id)
        return

    # ── Normal message → add to history and run conversation ──
    chat_histories.setdefault(chat_id, []).append({"role": "user", "content": text})
    _trim_history(chat_id)

    await run_conversation(chat_id, context.bot, update.message)


# ── JSON handling (unchanged) ─────────────────────────────────────────

_json_flush_tasks = {}


def _cancel_json_flush(context, chat_id):
    existing = _json_flush_tasks.get(chat_id)
    if existing and not existing.done():
        existing.cancel()
    _json_flush_tasks.pop(chat_id, None)


def _schedule_json_flush(update, context, chat_id):
    """Schedule a JSON flush 3 seconds from now, cancelling any existing one."""
    existing = _json_flush_tasks.get(chat_id)
    if existing and not existing.done():
        existing.cancel()

    async def _flush():
        await asyncio.sleep(3)
        json_buf = context.chat_data.get("json_buffer")
        if not json_buf:
            return

        combined = "".join(json_buf).strip()
        context.chat_data["json_buffer"] = None
        _json_flush_tasks.pop(chat_id, None)
        log.info(f"JSON flush triggered ({len(combined)} chars)")

        try:
            data = json.loads(combined)
            await _process_json_text_direct(context.bot, update.message, chat_id, data, context)
        except json.JSONDecodeError as e:
            await update.message.reply_text(
                f"Received {len(combined)} chars but JSON is incomplete.\n"
                f"Error near position {e.pos}: {e.msg}\n\n"
                "Try sending as a file attachment instead."
            )

    _json_flush_tasks[chat_id] = asyncio.create_task(_flush())


async def _process_json_text(update, context, chat_id, data):
    """Save JSON data as snapshot and run analysis."""
    await _process_json_text_direct(context.bot, update.message, chat_id, data, context)


async def _process_json_text_direct(bot, message, chat_id, data, context):
    """Process JSON data: save snapshot and run analysis."""
    await bot.send_chat_action(chat_id, "typing")

    SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    snap_path = SNAPSHOTS_DIR / f"{timestamp}.json"
    with open(snap_path, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    try:
        result = subprocess.run(
            ["/home/vincent/anki-headless/.venv/bin/python", ANALYZE_SCRIPT, str(snap_path), "--tag-hanly"],
            capture_output=True, text=True, timeout=120,
        )
        output = result.stdout
        if result.stderr:
            output += f"\nWarnings:\n{result.stderr[-500:]}"
    except subprocess.TimeoutExpired:
        output = "Analysis timed out (>120s)"
    except Exception as e:
        output = f"Analysis failed: {e}"

    await send_long_message(message, output)
    context.chat_data["last_json_snapshot"] = str(snap_path)


# ── Main ──────────────────────────────────────────────────────────────

def _sync_gated_templates():
    """Run both maturity gates. See _apply_template_gate for the rule."""
    col = None
    try:
        col = open_collection()
        msgs = []
        for gate in (apply_reverse_gate, apply_cloze_gate):
            r = gate(col)
            if r.get("error"):
                # Loud, every run. A gate that quietly does nothing is the failure this
                # whole rewrite exists to stop.
                msgs.append(f"{r['deck']} gate NOT RUN — {r['error']}")
            elif r["moved"] or r["unsuspended"] or r["suspended"]:
                msgs.append(f"{r['deck']}: moved {r['moved']}, unsuspended "
                            f"{r['unsuspended']}, suspended {r['suspended']}")
        return "; ".join(msgs) or None
    except Exception as e:
        return f"Template gates failed: {e}"
    finally:
        if col is not None:
            col.close()


def _sync_grammar_reverse_cards():
    """Unsuspend hanly-grammar-reverse cards when the forward card has been reviewed."""
    col = open_collection()
    try:
        # Notes whose forward card has been started in hanly-grammar
        learned_notes = set()
        # These two decks live under Hidden:: -- the old unqualified names matched
        # nothing, exactly like the reverse job did.
        for cid in col.find_cards('"deck:Hidden::hanly-grammar" -is:new -is:suspended'):
            card = col.get_card(cid)
            learned_notes.add(card.nid)

        # Unsuspend grammar-reverse cards for those notes
        to_unsuspend = []
        for cid in col.find_cards('"deck:Hidden::hanly-grammar-reverse" is:suspended'):
            card = col.get_card(cid)
            if card.nid in learned_notes:
                to_unsuspend.append(cid)

        if to_unsuspend:
            col.sched.unsuspend_cards(to_unsuspend)
            return f"Unsuspended {len(to_unsuspend)} grammar reverse cards"
        return None
    except Exception as e:
        return f"Grammar reverse sync failed: {e}"
    finally:
        col.close()


async def periodic_sync(context):
    """Background job: sync with AnkiWeb, then run the maturity gates.

    Each step is isolated. A failure in one must not skip the others -- a transient
    collection lock during the sync used to abort the coroutine before either gate ran,
    while APScheduler still logged the job as successful.
    """
    for label, fn in (("sync", _sync_collection),
                      ("gates", _sync_gated_templates),
                      ("grammar-reverse", _sync_grammar_reverse_cards)):
        try:
            result = await asyncio.to_thread(fn)
        except Exception as e:
            log.error(f"Periodic {label} raised: {type(e).__name__}: {e}")
            continue
        if result:
            log.info(f"Periodic {label}: {result}")


async def main_async():
    log.info("Starting Anki Telegram bot + API server...")

    # Resolve every required deck ONCE, loudly. A rename used to leave a lookup returning
    # None and the job carried on doing nothing for months. Now it is visible on the
    # first restart after the rename.
    col = open_collection()
    try:
        gone = missing_decks(col)
    finally:
        col.close()
    if gone:
        log.error("REQUIRED DECKS MISSING: %s — the maturity gates and card creation "
                  "will not work correctly until these exist or the constants in bot.py "
                  "are updated.", ", ".join(repr(n) for n in gone))
    else:
        log.info("Deck check: all %d required decks resolve", len(REQUIRED_DECKS))

    # Build Telegram app
    tg_app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    tg_app.add_handler(CommandHandler("start", cmd_start))
    tg_app.add_handler(CommandHandler("status", cmd_status))
    tg_app.add_handler(CommandHandler("decks", cmd_decks))
    tg_app.add_handler(CommandHandler("help", cmd_help))
    tg_app.add_handler(CommandHandler("clear", cmd_clear))
    tg_app.add_handler(CommandHandler("log", cmd_log))
    tg_app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    tg_app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    tg_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    tg_app.job_queue.run_repeating(periodic_sync, interval=300, first=10)
    log.info("Scheduled AnkiWeb sync every 5 minutes")

    # Start HTTP API server
    web_app = create_web_app()
    runner = web.AppRunner(web_app)
    await runner.setup()
    site = web.TCPSite(runner, '127.0.0.1', API_PORT)
    await site.start()
    log.info(f"API server listening on 127.0.0.1:{API_PORT}")
    if API_KEY:
        log.info("API auth: bearer key configured")
    else:
        # Not fatal — the 127.0.0.1 bind is the real boundary — but say it out loud
        # so an empty key is a visible choice rather than something discovered later
        # while debugging a 401 (or worse, not discovered at all).
        log.warning("API auth: api_key is EMPTY in .bot_config.json — every local "
                    "process can call /api/*; only the 127.0.0.1 bind restricts access")

    # Start Telegram polling (the 3 steps that run_polling() wraps)
    await tg_app.initialize()
    await tg_app.updater.start_polling()
    await tg_app.start()
    log.info("Telegram polling started. Press Ctrl+C to stop.")

    # Wait for shutdown signal
    stop = asyncio.Event()
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    await stop.wait()

    # Graceful shutdown
    log.info("Shutting down...")
    await tg_app.updater.stop()
    await tg_app.stop()
    await tg_app.shutdown()
    await runner.cleanup()


def main():
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
