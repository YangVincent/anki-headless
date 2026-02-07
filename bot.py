#!/usr/bin/env python3
"""Telegram bot that uses Claude to create Anki cards via a conversational loop."""

import asyncio
import base64
import json
import logging
import os
import random
import re
import subprocess
import unicodedata
from datetime import datetime
from pathlib import Path

import anthropic
import httpx
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

# ── Config ────────────────────────────────────────────────────────────

CONFIG_FILE = "/home/vincent/anki/.bot_config.json"
COLLECTION_PATH = "/home/vincent/anki/collection.anki2"
AUTH_FILE = os.path.expanduser("~/.anki_auth")

DEFAULT_DECK = "Knowledge::Languages::Chinese::Vocabulary"
CHINESE_VOCAB_NOTETYPE = "ChineseVocabulary"
SNAPSHOTS_DIR = Path("/home/vincent/anki/json_snapshots")
CHANGELOG_FILE = Path("/home/vincent/anki/changelog.jsonl")
ANALYZE_SCRIPT = "/home/vincent/anki/analyze_json.py"
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
    with open(CHANGELOG_FILE, "a") as f:
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

    col = open_collection()
    try:
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


def _trim_history(chat_id, max_messages=50):
    """Trim conversation history from the front, keeping recent messages."""
    hist = chat_histories.get(chat_id, [])
    if len(hist) > max_messages:
        chat_histories[chat_id] = hist[-max_messages:]


# ── Unified system prompt ─────────────────────────────────────────────

SYSTEM_PROMPT = """You are an Anki card creation and collection management assistant running as a Telegram bot. You help the user create flashcards and manage their Anki collection through natural conversation.

## Capabilities
1. **Chinese vocabulary cards** — create ChineseVocabulary note type cards
2. **General cards** — create Basic note type cards for any topic
3. **Collection management** — search, suspend, unsuspend, delete, tag, move cards
4. **Image analysis** — OCR Chinese text from photos, offer to create cards
5. **Collection stats** — report on deck sizes, due counts, etc.

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
1. Call `get_vocab_for_story` to get known vocabulary and target words
2. If the user wants a news-based or current-events story, use `web_search` to find recent Chinese news headlines for inspiration
3. Write the story following this format exactly:

**Header**: 📖 Chinese story #N (HSK level, topic tag):
**Title**: 【Chinese title】 followed by English translation on same line
**Body**: ~350-400 Chinese characters. Use 90-95% known vocab from the list. Write in first person, conversational tone. Use short paragraphs. Mix in dialogue for engagement. Build to an interesting or thought-provoking conclusion.
**Target words**: Weave in ~5-7 target words naturally. Annotate each on first use as: word（pinyin - meaning）
**Footer**: After a --- separator:
  📝 Key vocab: bullet list of all target words with pinyin and meaning
  📰 Based on: one-line summary of the real news story (if news-based)

4. The user can ask for a specific topic, difficulty adjustment, or more/fewer new words
5. If the user wants to create cards for the target words, offer to do so

## Important Rules
- **Always confirm before destructive actions** (delete, suspend, unsuspend, tag, move). Show what will be affected and ask the user to confirm before calling the modification tool.
- **Always sync after modifications** — call sync_collection after any add/delete/suspend/tag/move operation.
- For card creation, show a preview of what you'll create and ask for confirmation before calling add_chinese_vocab or add_general_card.
- When analyzing images, list the words you found and ask which ones to create cards for.
- Keep responses concise — this is a Telegram chat, not an essay.
- For large result sets needing semantic filtering, use get_field_values to inspect content efficiently.
- When user confirms (yes/y/ok/sure/do it), proceed with the action without asking again.
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
        "description": "Delete notes matching a query. DESTRUCTIVE — always confirm with user first.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Anki search query to select notes"}
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
        "name": "sync_collection",
        "description": "Sync the collection to AnkiWeb.",
        "input_schema": {
            "type": "object",
            "properties": {}
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
]

# ── Tool execution ────────────────────────────────────────────────────

def execute_tool(tool_name, tool_input):
    """Execute a tool call and return the result as a string."""

    if tool_name == "sync_collection":
        return _sync_collection()

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

            did = col.decks.id_for_name(DEFAULT_DECK)
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
            log_change("add_chinese_vocab", [nid], {
                "simplified": tool_input.get("simplified"),
                "deck": DEFAULT_DECK,
                "tags": tags,
            })
            return json.dumps({
                "success": True,
                "note_id": nid,
                "simplified": tool_input.get("simplified"),
                "deck": DEFAULT_DECK,
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

            deck = tool_input.get("deck", "Knowledge")
            did = col.decks.id_for_name(deck)
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

    # All remaining tools need the collection
    col = open_collection()
    try:
        if tool_name == "search_notes":
            query = tool_input["query"]
            note_ids = list(col.find_notes(query))
            if len(note_ids) <= 200:
                return json.dumps({"count": len(note_ids), "note_ids": note_ids})
            else:
                return json.dumps({"count": len(note_ids), "note_ids_truncated": True, "sample_ids": note_ids[:10]})

        elif tool_name == "get_notes_detail":
            note_ids = tool_input["note_ids"][:100]
            results = []
            for nid in note_ids:
                try:
                    note = col.get_note(nid)
                    model = note.note_type()
                    field_names = [f["name"] for f in model["flds"]]
                    cards = note.cards()
                    deck_name = col.decks.name(cards[0].did) if cards else "Unknown"
                    fields = {}
                    for i, name in enumerate(field_names):
                        if i < len(note.fields):
                            val = strip_html(note.fields[i])
                            fields[name] = val[:200] if len(val) > 200 else val
                    results.append({
                        "note_id": nid,
                        "fields": fields,
                        "tags": note.tags,
                        "deck": deck_name,
                        "note_type": model["name"],
                        "suspended": any(c.queue == -1 for c in cards),
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
                            val = strip_html(note.fields[idx]) if idx < len(note.fields) else ""
                            entry[fname] = val[:200] if len(val) > 200 else val
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
            col.remove_notes(note_ids)
            log_change("delete", note_ids)
            return f"Deleted {len(note_ids)} note(s)."

        elif tool_name == "tag_notes":
            query = tool_input["query"]
            tags = tool_input.get("tags", [])
            note_ids = list(col.find_notes(query))
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
            card_ids, skipped = _collect_card_ids(col, note_ids)
            col.set_deck(card_ids, did)
            log_change("move_deck", note_ids, {"deck": deck_name, "card_count": len(card_ids)})
            return f"Moved {len(card_ids)} card(s) across {len(note_ids)} note(s) to: {deck_name}"

        else:
            return json.dumps({"error": f"Unknown tool: {tool_name}"})
    finally:
        col.close()


# ── Conversation loop ─────────────────────────────────────────────────

async def run_conversation(chat_id, bot, message_obj):
    """Run the Claude conversation loop for a chat.
    Calls Claude with the full history, executes tools, and sends the final text reply.
    """
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
                await message_obj.reply_text(block.text, parse_mode="Markdown")
            except Exception:
                await message_obj.reply_text(block.text)

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
                "content": result,
            })

        # Append tool results to history
        chat_histories[chat_id].append({"role": "user", "content": tool_results})
        _trim_history(chat_id)

    # Hit max turns
    await message_obj.reply_text("Reached maximum conversation turns. Please try again.")


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
        for d in decks:
            if d.name == "Default" or "::" in d.name:
                count = len(col.find_cards(f'"deck:{d.name}"'))
                if count > 0:
                    lines.append(f"  {d.name} ({count})")
        if not lines:
            lines = [f"  {d.name}" for d in decks]
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
            ["/home/vincent/anki/.venv/bin/python", ANALYZE_SCRIPT, str(snap_path)],
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

def _sync_reverse_cards():
    """Unsuspend hanly-reverse cards for words started in hanly deck."""
    col = open_collection()
    try:
        # Notes that have been started (reviewed at least once)
        learned_notes = set(col.find_notes(
            f'"note:{CHINESE_VOCAB_NOTETYPE}" tag:hanly -is:new -is:suspended'
        ))
        # Currently active reverse cards
        active_reverse = set()
        for cid in col.find_cards('deck:hanly-reverse -is:suspended'):
            card = col.get_card(cid)
            active_reverse.add(card.nid)

        # Find reverse cards that should be unsuspended
        to_unsuspend = []
        for cid in col.find_cards('deck:hanly-reverse is:suspended'):
            card = col.get_card(cid)
            if card.nid in learned_notes:
                to_unsuspend.append(cid)

        if to_unsuspend:
            col.sched.unsuspend_cards(to_unsuspend)
            return f"Unsuspended {len(to_unsuspend)} reverse cards"
        return None
    except Exception as e:
        return f"Reverse sync failed: {e}"
    finally:
        col.close()


async def periodic_sync(context):
    """Background job: sync collection with AnkiWeb, then update reverse cards."""
    result = await asyncio.to_thread(_sync_collection)
    log.info(f"Periodic sync: {result}")
    reverse_result = await asyncio.to_thread(_sync_reverse_cards)
    if reverse_result:
        log.info(f"Periodic sync: {reverse_result}")


def main():
    log.info("Starting Anki Telegram bot...")
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("decks", cmd_decks))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("clear", cmd_clear))
    app.add_handler(CommandHandler("log", cmd_log))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Sync with AnkiWeb every 5 minutes
    app.job_queue.run_repeating(periodic_sync, interval=300, first=10)
    log.info("Scheduled AnkiWeb sync every 5 minutes")

    log.info("Bot is running. Press Ctrl+C to stop.")
    app.run_polling()


if __name__ == "__main__":
    main()
