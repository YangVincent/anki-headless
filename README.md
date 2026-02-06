# Anki Telegram Bot

A Telegram bot that uses Claude to create and manage Anki flashcards through natural conversation.

## How It Works

The bot runs a single conversational loop: every message (text or photo) is appended to a per-chat history, then sent to Claude along with a system prompt and 16 tool definitions. Claude decides what to do — look up a word, search the collection, create a card, suspend notes, etc. — by calling tools. The bot executes each tool against the local Anki collection, feeds results back to Claude, and loops until Claude produces a text reply. This replaces the previous classifier→router→handler architecture with three separate state machines.

### Flow

```
User message → append to chat history → call Claude with history + tools
                                              ↓
                                    ┌─── tool_use? ───┐
                                    │                  │
                                   yes                 no
                                    │                  │
                              execute tool        send text reply
                              append result        to user, done
                              to history
                                    │
                                    └──→ call Claude again (loop)
```

### Tools (16 total)

**Read-only:** `search_notes`, `get_notes_detail`, `get_field_values`, `list_decks`, `list_note_types`, `get_collection_stats`

**Card creation:** `add_chinese_vocab`, `add_general_card`

**Modification:** `suspend_cards`, `unsuspend_cards`, `tag_notes`, `remove_tags`, `delete_notes`, `move_cards`

**Meta:** `sync_collection`

Claude is instructed to always confirm before destructive actions and always sync after modifications.

### Conversation History

Each chat gets a rolling history (`chat_histories` dict, trimmed to 50 messages). This means Claude has context for follow-up questions like "what did you just suspend?" without any state machine.

Photos are added as multimodal messages (base64 image + caption), so Claude handles OCR natively.

`/clear` wipes the history for the current chat.

## Commands

| Command | Description |
|---------|-------------|
| `/status` | Collection stats (new/due/learning counts) |
| `/decks` | List decks with card counts |
| `/log` | Recent changelog entries |
| `/clear` | Clear conversation history |
| `/help` | Usage guide |

These bypass Claude and query the collection directly for speed.

## Setup

Requires a `.bot_config.json` in the project directory:

```json
{
  "telegram_bot_token": "...",
  "anthropic_api_key": "...",
  "default_deck": "Knowledge::Languages::Chinese::Vocabulary"
}
```

Dependencies: `anthropic`, `httpx`, `python-telegram-bot`, `anki` (installed in `.venv`).

Managed with pm2: `pm2 restart anki-bot`

## Files

- `bot.py` — the bot (single file)
- `cli.py` — standalone Anki CLI tool
- `anki-cli` — shell wrapper for cli.py
- `analyze_json.py` — JSON snapshot analysis script
- `changelog.jsonl` — append-only change log
