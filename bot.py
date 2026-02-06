#!/usr/bin/env python3
"""Telegram bot that uses Claude to create Anki cards from messages."""

import base64
import json
import logging
import os
import re
import unicodedata

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
CHINESE_VOCAB_FIELDS = ["Simplified", "Pinyin", "Meaning", "Traditional", "Notes",
                        "Audio", "Strokes", "ColorPinyin", "Frequency", "CustomFreq",
                        "PartOfSpeech", "Homophone", "SentenceSimplified",
                        "SentenceTraditional", "SentenceSimplifiedCloze",
                        "SentenceTraditionalCloze", "SentencePinyin",
                        "SentenceMeaning", "SentenceAudio"]

logging.basicConfig(format="%(asctime)s [%(levelname)s] %(message)s", level=logging.INFO)
log = logging.getLogger(__name__)


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


def sync_collection():
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


def has_cjk(text):
    """Check if text contains CJK characters."""
    return any(unicodedata.category(ch).startswith("Lo") and
               "\u4e00" <= ch <= "\u9fff" or "\u3400" <= ch <= "\u4dbf"
               for ch in text)


def is_chinese_vocab(text):
    """Heuristic: short message with CJK characters = vocab lookup."""
    clean = text.strip()
    # Remove hashtags for detection purposes
    clean = re.sub(r"#\w+", "", clean).strip()
    if not has_cjk(clean):
        return False
    # Short-ish text (up to ~20 chars after removing non-CJK) is likely vocab
    cjk_chars = [ch for ch in clean if "\u4e00" <= ch <= "\u9fff" or "\u3400" <= ch <= "\u4dbf"]
    return len(cjk_chars) <= 10 and len(clean) <= 30


def extract_tags_from_message(text):
    """Extract #hashtags from message text."""
    tags = re.findall(r"#(\w+)", text)
    return [t for t in tags if t.lower() not in ("card", "anki")]


def find_duplicates(col, text):
    """Search for existing notes matching the text across fields."""
    # Extract CJK characters for Chinese searches
    clean = re.sub(r"#\w+", "", text).strip()
    if has_cjk(clean):
        # Search by simplified characters
        cjk_text = re.sub(r"[^\u4e00-\u9fff\u3400-\u4dbf]", "", clean)
        if cjk_text:
            note_ids = col.find_notes(f"Simplified:{cjk_text}")
            if not note_ids:
                # Also try a broader search
                note_ids = col.find_notes(cjk_text)
            return note_ids
    else:
        # General search — use key terms
        words = clean.split()
        if len(words) <= 3:
            query = clean
        else:
            query = " ".join(words[:5])
        note_ids = col.find_notes(query)
        return note_ids
    return []


# ── Claude API ────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are an Anki card creation assistant running as a Telegram bot. Analyze the user's message and return structured JSON.

IMPORTANT: First decide if the message is a CONVERSATION (question, greeting, request for help, chatting) or a CARD REQUEST (vocabulary, fact, knowledge to memorize).

## Conversation Mode
If the user is asking a question about the bot, chatting, greeting, or anything that is NOT a request to create a flashcard, return:
```json
{
  "type": "conversation",
  "reply": "Your helpful response here"
}
```
The bot can: create Chinese vocab cards from characters/words, create general knowledge cards, detect duplicates, sync to AnkiWeb. Commands: /status, /decks, /help.

## Chinese Vocabulary Mode
If the message contains Chinese characters and appears to be a vocabulary word or short phrase to learn, return:
```json
{
  "type": "chinese_vocab",
  "simplified": "简体字",
  "traditional": "繁體字",
  "pinyin": "jiǎntǐzì",
  "meaning": "English definition(s)",
  "part_of_speech": "noun/verb/adj/etc",
  "sentence_simplified": "Example sentence in simplified Chinese",
  "sentence_pinyin": "Example sentence pinyin",
  "sentence_meaning": "Example sentence translation"
}
```

Important for Chinese vocab:
- Use tone-marked pinyin (ā á ǎ à), NOT numbered pinyin
- Provide a concise but complete meaning in English
- If traditional is the same as simplified, still include it
- Include a natural example sentence

## General Card Mode
For messages that are clearly requesting to memorize a fact, concept, or piece of knowledge (e.g. "add a card about X", "mitochondria is the powerhouse of the cell", explicit learning content), return:
```json
{
  "type": "general",
  "deck": "suggested deck path (use :: for nesting)",
  "front": "Question or front of card",
  "back": "Answer or back of card",
  "tags": ["relevant", "tags"]
}
```

For general cards:
- Make the front a clear question
- Make the back a concise but complete answer
- Suggest an appropriate deck name (default: "Knowledge")
- Include relevant topic tags

## Rules
- ALWAYS return valid JSON and nothing else
- NO markdown code fences, just raw JSON
- When in doubt between conversation and card creation, prefer CONVERSATION — it's better to ask than to create an unwanted card
- For Chinese: if the user sends a single character or word, look it up. If they send a phrase, treat it as vocabulary too.
"""


def ask_claude(message_text):
    """Send message to Claude and parse JSON response."""
    response = claude.messages.create(
        model="claude-sonnet-4-5-20250929",
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": message_text}],
    )
    text = response.content[0].text.strip()
    # Strip markdown code fences if present
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return json.loads(text)


OCR_SYSTEM_PROMPT = """You extract Chinese vocabulary from images. Analyze the image and identify distinct Chinese words or phrases that would be useful as flashcards.

Return a JSON array of words found. For each word provide:
```json
{
  "words": [
    {
      "simplified": "词语",
      "traditional": "詞語",
      "pinyin": "cíyǔ",
      "meaning": "word; term",
      "part_of_speech": "noun",
      "sentence_simplified": "这个词语很常见。",
      "sentence_pinyin": "Zhège cíyǔ hěn chángjiàn.",
      "sentence_meaning": "This word is very common."
    }
  ]
}
```

Rules:
- Use tone-marked pinyin (ā á ǎ à), NOT numbered
- Extract individual WORDS, not full sentences (unless the image shows a single sentence/phrase to learn)
- Deduplicate — don't list the same word twice
- If the image contains non-Chinese text or no text, return {"words": []}
- If there's a mix, focus on the Chinese words
- ALWAYS return valid JSON and nothing else, NO markdown code fences
"""


def ask_claude_ocr(image_bytes, media_type, caption=None):
    """Send image to Claude for OCR extraction. Returns parsed JSON."""
    image_b64 = base64.b64encode(image_bytes).decode("utf-8")
    content = [
        {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": image_b64}},
    ]
    if caption:
        content.append({"type": "text", "text": f"User's note: {caption}"})

    response = claude.messages.create(
        model="claude-sonnet-4-5-20250929",
        max_tokens=2048,
        system=OCR_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": content}],
    )
    text = response.content[0].text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return json.loads(text)


# Per-chat pending words from image OCR: {chat_id: [word_dicts]}
pending_image_words = {}


# ── Card creation ─────────────────────────────────────────────────────

def add_chinese_vocab_card(data, extra_tags):
    """Add a Chinese vocabulary card. Returns (note_id, message)."""
    col = open_collection()
    try:
        model = col.models.by_name(CHINESE_VOCAB_NOTETYPE)
        if not model:
            return None, f"Note type '{CHINESE_VOCAB_NOTETYPE}' not found"

        did = col.decks.id_for_name(DEFAULT_DECK)
        note = col.new_note(model)

        note["Simplified"] = data.get("simplified", "")
        note["Traditional"] = data.get("traditional", "")
        note["Pinyin"] = data.get("pinyin", "")
        note["Meaning"] = data.get("meaning", "")
        note["PartOfSpeech"] = data.get("part_of_speech", "")
        note["SentenceSimplified"] = data.get("sentence_simplified", "")
        note["SentencePinyin"] = data.get("sentence_pinyin", "")
        note["SentenceMeaning"] = data.get("sentence_meaning", "")

        tags = ["claude", "chinese"]
        tags.extend(extra_tags)
        note.tags = tags

        col.add_note(note, did)
        nid = note.id

        msg = (
            f"**{data['simplified']}** ({data.get('traditional', '')})\n"
            f"*{data.get('pinyin', '')}*\n"
            f"{data.get('meaning', '')}\n\n"
            f"Deck: `{DEFAULT_DECK}`"
        )
        return nid, msg
    finally:
        col.close()


def add_general_card(data, extra_tags):
    """Add a general (Basic) card. Returns (note_id, message)."""
    col = open_collection()
    try:
        model = col.models.by_name("Basic")
        if not model:
            return None, "Note type 'Basic' not found"

        deck = data.get("deck", "Knowledge")
        did = col.decks.id_for_name(deck)
        note = col.new_note(model)

        note["Front"] = data.get("front", "")
        note["Back"] = data.get("back", "")

        tags = ["claude"]
        tags.extend(data.get("tags", []))
        tags.extend(extra_tags)
        note.tags = tags

        col.add_note(note, did)
        nid = note.id

        front_preview = data.get("front", "")
        if len(front_preview) > 80:
            front_preview = front_preview[:77] + "..."
        msg = (
            f"**Q:** {front_preview}\n"
            f"**A:** {data.get('back', '')}\n\n"
            f"Deck: `{deck}`"
        )
        return nid, msg
    finally:
        col.close()


def tag_existing_notes(note_ids, extra_tags):
    """Add 'claude' tag (and any extra tags) to existing notes."""
    col = open_collection()
    try:
        tagged = []
        for nid in note_ids[:5]:  # Limit to first 5 matches
            note = col.get_note(nid)
            existing = {t.lower() for t in note.tags}
            added = []
            for tag in ["claude"] + extra_tags:
                if tag.lower() not in existing:
                    note.tags.append(tag)
                    added.append(tag)
            if added:
                col.update_note(note)
                tagged.append(nid)

        return tagged
    finally:
        col.close()


# ── Telegram handlers ─────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Anki Card Bot\n\n"
        "Send me a message and I'll create an Anki card from it.\n\n"
        "Examples:\n"
        "  `学习` — creates a Chinese vocab card\n"
        "  `好好学习天天向上` — Chinese phrase card\n"
        "  `mitochondria is the powerhouse of the cell` — general card\n"
        "  `学习 #hsk4 #important` — vocab card with extra tags\n\n"
        "Commands:\n"
        "  /status — due counts & recent additions\n"
        "  /decks — list available decks\n"
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

        # Recent claude-tagged additions
        recent = col.find_notes("tag:claude")
        recent_count = len(recent)

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
                # Only show top-level or commonly used
                count = len(col.find_cards(f'"deck:{d.name}"'))
                if count > 0:
                    lines.append(f"  {d.name} ({count})")
        if not lines:
            lines = [f"  {d.name}" for d in decks]
        await update.message.reply_text("Decks:\n" + "\n".join(lines[:30]))
    finally:
        col.close()


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Usage Guide\n\n"
        "Just send me text and I'll create a card:\n\n"
        "Chinese vocab: send Chinese characters (e.g. `考虑`)\n"
        "General card: describe what you want to learn\n"
        "Add tags: include `#tagname` in your message\n\n"
        "If a matching card already exists, I'll tag it with `claude` "
        "instead of creating a duplicate.\n\n"
        "Commands:\n"
        "  /status — collection stats\n"
        "  /decks — list decks\n"
        "  /start — welcome message",
        parse_mode="Markdown",
    )


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle photo messages — OCR extract words and ask for confirmation."""
    chat_id = update.effective_chat.id
    photo = update.message.photo[-1]  # Highest resolution
    caption = update.message.caption or ""
    extra_tags = extract_tags_from_message(caption) if caption else []

    log.info(f"Received photo (file_id={photo.file_id}, caption={caption!r})")
    await context.bot.send_chat_action(chat_id, "typing")

    # Download the photo
    file = await context.bot.get_file(photo.file_id)
    async with httpx.AsyncClient() as client:
        resp = await client.get(file.file_path)
        image_bytes = resp.content

    # Determine media type from file path
    ext = file.file_path.rsplit(".", 1)[-1].lower() if "." in file.file_path else "jpg"
    media_types = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp"}
    media_type = media_types.get(ext, "image/jpeg")

    # Send to Claude for OCR
    try:
        data = ask_claude_ocr(image_bytes, media_type, caption or None)
    except Exception as e:
        log.error(f"OCR error: {e}")
        await update.message.reply_text(f"Failed to analyze image: {e}")
        return

    words = data.get("words", [])
    if not words:
        await update.message.reply_text("No Chinese words found in the image.")
        return

    # Check for duplicates per word
    col = open_collection()
    try:
        for w in words:
            existing = col.find_notes(f"Simplified:{w['simplified']}")
            w["_duplicate"] = bool(existing)
    finally:
        col.close()

    # Store pending words and show them
    for w in words:
        w["_extra_tags"] = extra_tags
    pending_image_words[chat_id] = words

    lines = []
    for i, w in enumerate(words, 1):
        dupe = " (exists)" if w.get("_duplicate") else ""
        lines.append(f"{i}. **{w['simplified']}** ({w.get('traditional', '')}) — "
                     f"_{w.get('pinyin', '')}_  {w.get('meaning', '')}{dupe}")

    msg = "Words found:\n\n" + "\n".join(lines)
    msg += "\n\nReply with:\n  `all` — add all new words\n  `1,3,5` — add specific ones\n  `no` — cancel"
    await update.message.reply_text(msg, parse_mode="Markdown")


def parse_image_confirmation(text):
    """Parse user's reply to image word list. Returns list of 1-based indices, 'all', or None."""
    text = text.strip().lower()
    if text in ("no", "cancel", "n", "nah", "nope"):
        return "cancel"
    if text in ("all", "yes", "y", "yeah", "yep", "ok"):
        return "all"
    # Try to parse comma/space separated numbers
    nums = re.findall(r"\d+", text)
    if nums:
        return [int(n) for n in nums]
    return None


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if not text:
        return

    chat_id = update.effective_chat.id
    log.info(f"Received: {text}")

    # Check if this is a reply to a pending image word list
    if chat_id in pending_image_words:
        choice = parse_image_confirmation(text)
        words = pending_image_words[chat_id]

        if choice == "cancel":
            del pending_image_words[chat_id]
            await update.message.reply_text("Cancelled.")
            return

        if choice is not None:
            del pending_image_words[chat_id]

            if choice == "all":
                indices = list(range(len(words)))
            else:
                indices = [n - 1 for n in choice if 1 <= n <= len(words)]

            if not indices:
                await update.message.reply_text("No valid selections. Cancelled.")
                return

            added = []
            skipped = []
            for i in indices:
                w = words[i]
                if w.get("_duplicate"):
                    skipped.append(w["simplified"])
                    continue
                extra_tags = w.get("_extra_tags", [])
                nid, msg = add_chinese_vocab_card(w, extra_tags)
                if nid:
                    added.append(w["simplified"])

            parts = []
            if added:
                parts.append(f"Added {len(added)} card(s): {', '.join(added)}")
            if skipped:
                parts.append(f"Skipped {len(skipped)} duplicate(s): {', '.join(skipped)}")

            if added:
                sync_msg = sync_collection()
                parts.append(f"_{sync_msg}_")

            await update.message.reply_text("\n".join(parts), parse_mode="Markdown")
            return

        # If we couldn't parse the reply, fall through to normal handling
        # (user might have sent a new unrelated message)
        del pending_image_words[chat_id]

    extra_tags = extract_tags_from_message(text)
    # Remove hashtags from the text sent to Claude
    clean_text = re.sub(r"\s*#\w+", "", text).strip()
    if not clean_text:
        await update.message.reply_text("Please send some text to create a card from.")
        return

    # Step 1: Check for duplicates
    col = open_collection()
    try:
        dupes = find_duplicates(col, text)
    finally:
        col.close()

    if dupes:
        tagged = tag_existing_notes(dupes, extra_tags)
        count = len(dupes)
        tag_msg = ""
        if tagged:
            tag_msg = f" (tagged {len(tagged)} note(s))"
        # Show a preview of the first match
        col = open_collection()
        try:
            note = col.get_note(dupes[0])
            fields = [strip_html(f) for f in note.fields if f.strip()]
            preview = " | ".join(fields[:3])
            if len(preview) > 100:
                preview = preview[:97] + "..."
        finally:
            col.close()

        await update.message.reply_text(
            f"Found {count} existing card(s){tag_msg}:\n`{preview}`",
            parse_mode="Markdown",
        )
        return

    # Step 2: Ask Claude to parse the message
    await context.bot.send_chat_action(update.effective_chat.id, "typing")
    try:
        data = ask_claude(clean_text)
    except Exception as e:
        log.error(f"Claude error: {e}")
        await update.message.reply_text(f"Claude API error: {e}")
        return

    # Step 3: Handle response
    if data.get("type") == "conversation":
        await update.message.reply_text(data.get("reply", "I'm not sure how to help with that."))
        return

    try:
        if data.get("type") == "chinese_vocab":
            nid, msg = add_chinese_vocab_card(data, extra_tags)
        else:
            nid, msg = add_general_card(data, extra_tags)

        if nid is None:
            await update.message.reply_text(f"Failed to add card: {msg}")
            return

        # Sync to AnkiWeb
        sync_msg = sync_collection()

        await update.message.reply_text(
            f"Card added!\n\n{msg}\n\n_{sync_msg}_",
            parse_mode="Markdown",
        )
        log.info(f"Added note {nid}")
    except Exception as e:
        log.error(f"Card creation error: {e}")
        await update.message.reply_text(f"Error adding card: {e}")


# ── Main ──────────────────────────────────────────────────────────────

def main():
    log.info("Starting Anki Telegram bot...")
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("decks", cmd_decks))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    log.info("Bot is running. Press Ctrl+C to stop.")
    app.run_polling()


if __name__ == "__main__":
    main()
