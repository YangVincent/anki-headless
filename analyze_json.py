#!/usr/bin/env python3
"""Analyze a JSON snapshot: structure, diff vs previous, known-character tagging."""

import json
import os
import sys
from datetime import datetime
from pathlib import Path

SNAPSHOTS_DIR = Path("/home/vincent/anki/json_snapshots")
COLLECTION_PATH = "/home/vincent/anki/collection.anki2"


def describe_value(v, depth=0, max_depth=3):
    """Recursively describe a JSON value's structure."""
    if depth >= max_depth:
        return type(v).__name__
    if isinstance(v, dict):
        if not v:
            return "{}"
        items = []
        for k in list(v.keys())[:10]:
            items.append(f"{k}: {describe_value(v[k], depth + 1, max_depth)}")
        suffix = f" ... +{len(v) - 10} more" if len(v) > 10 else ""
        return "{ " + ", ".join(items) + suffix + " }"
    elif isinstance(v, list):
        if not v:
            return "[]"
        sample = describe_value(v[0], depth + 1, max_depth)
        return f"[{sample}, ...] ({len(v)} items)"
    elif isinstance(v, str):
        if len(v) > 50:
            return f'str("{v[:50]}...")'
        return f'str("{v}")'
    elif isinstance(v, bool):
        return f"bool({v})"
    elif isinstance(v, int):
        return f"int({v})"
    elif isinstance(v, float):
        return f"float({v})"
    elif v is None:
        return "null"
    return type(v).__name__


def _has_cjk(s):
    return any("\u4e00" <= c <= "\u9fff" or "\u3400" <= c <= "\u4dbf" for c in s)


def extract_chinese_words(data, path=""):
    """Try to find Chinese words/characters in the JSON, whatever its structure.
    Returns a dict of {word: progressPercent} (deduped, _reverse stripped).
    If no progress info is available, defaults to 1.0."""
    words = {}

    if isinstance(data, dict):
        for key, val in data.items():
            # Check keys themselves (e.g. {"学": {...}, "中_reverse": {...}})
            clean_key = key.replace("_reverse", "").strip()
            if clean_key and _has_cjk(clean_key):
                # Extract progress if value is a dict with progressPercent
                progress = 1.0
                if isinstance(val, dict) and "progressPercent" in val:
                    progress = val["progressPercent"]
                # Keep the higher progress if we've seen this word before
                if clean_key not in words or progress > words[clean_key]:
                    words[clean_key] = progress
            # Check string values
            if isinstance(val, str) and _has_cjk(val):
                words.setdefault(val.strip(), 1.0)
            elif isinstance(val, (dict, list)) and not (clean_key and _has_cjk(clean_key)):
                words.update(extract_chinese_words(val, f"{path}.{key}"))
    elif isinstance(data, list):
        for i, item in enumerate(data):
            if isinstance(item, str) and _has_cjk(item):
                words.setdefault(item.strip(), 1.0)
            elif isinstance(item, (dict, list)):
                words.update(extract_chinese_words(item, f"{path}[{i}]"))
    return words


def extract_characters(words):
    """Extract unique individual characters from a set of words."""
    chars = set()
    for w in words:
        for c in w:
            if "\u4e00" <= c <= "\u9fff" or "\u3400" <= c <= "\u4dbf":
                chars.add(c)
    return chars


def get_previous_snapshot():
    """Get the most recent previous snapshot file."""
    snapshots = sorted(SNAPSHOTS_DIR.glob("*.json"))
    if len(snapshots) < 2:
        return None
    # Return second-to-last (the latest is the one we just saved)
    return snapshots[-2]


def save_snapshot(data, filename=None):
    """Save JSON data as a timestamped snapshot. Returns the path."""
    SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    if filename is None:
        filename = datetime.now().strftime("%Y%m%d_%H%M%S") + ".json"
    path = SNAPSHOTS_DIR / filename
    with open(path, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return path


def analyze_structure(data):
    """Return a human-readable structure analysis."""
    lines = []
    lines.append(f"Type: {type(data).__name__}")

    if isinstance(data, dict):
        lines.append(f"Top-level keys ({len(data)}):")
        for key in list(data.keys())[:20]:
            lines.append(f"  {key}: {describe_value(data[key], depth=1)}")
        if len(data) > 20:
            lines.append(f"  ... +{len(data) - 20} more keys")
    elif isinstance(data, list):
        lines.append(f"Array with {len(data)} items")
        if data:
            lines.append(f"First item: {describe_value(data[0], depth=0, max_depth=4)}")

    # Extract Chinese content
    words_dict = extract_chinese_words(data)
    mastered = {w for w, p in words_dict.items() if p >= 1.0}
    partial = {w: p for w, p in words_dict.items() if 0 < p < 1.0}
    lines.append(f"\nChinese words/chars found: {len(words_dict)}")
    lines.append(f"Fully mastered (100%): {len(mastered)}")
    lines.append(f"Partially learned: {len(partial)}")
    mastered_chars = extract_characters(mastered)
    lines.append(f"Unique mastered characters: {len(mastered_chars)}")
    if mastered:
        sample = sorted(mastered)[:20]
        lines.append(f"Sample mastered: {', '.join(sample)}")

    return "\n".join(lines)


def diff_snapshots(current_data, previous_path):
    """Compare current JSON to a previous snapshot. Returns diff summary."""
    with open(previous_path) as f:
        prev_data = json.load(f)

    curr_dict = extract_chinese_words(current_data)
    prev_dict = extract_chinese_words(prev_data)

    curr_mastered = {w for w, p in curr_dict.items() if p >= 1.0}
    prev_mastered = {w for w, p in prev_dict.items() if p >= 1.0}

    new_mastered = curr_mastered - prev_mastered
    lost_mastery = prev_mastered - curr_mastered

    curr_chars = extract_characters(curr_mastered)
    prev_chars = extract_characters(prev_mastered)
    new_chars = curr_chars - prev_chars

    lines = []
    lines.append(f"Previous snapshot: {previous_path.name}")
    lines.append(f"Mastered before: {len(prev_mastered)} -> now: {len(curr_mastered)}")
    lines.append(f"Newly mastered: {len(new_mastered)}")
    lines.append(f"Lost mastery: {len(lost_mastery)}")
    lines.append(f"New characters: {len(new_chars)}")

    if new_mastered:
        sample = sorted(new_mastered)[:30]
        lines.append(f"\nNewly mastered: {', '.join(sample)}")
        if len(new_mastered) > 30:
            lines.append(f"  ... +{len(new_mastered) - 30} more")

    if new_chars:
        lines.append(f"New chars: {''.join(sorted(new_chars))}")

    return lines, curr_mastered, curr_chars


def find_hanly_candidates(known_chars):
    """Find notes in Anki whose simplified text is composed entirely of known characters.
    Returns list of (note_id, simplified) that should get the 'hanly' tag."""
    from anki.collection import Collection
    import re

    col = Collection(COLLECTION_PATH)
    try:
        # Get all notes in Chinese vocab deck
        all_notes = col.find_notes("")
        candidates = []
        already_tagged = 0

        for nid in all_notes:
            note = col.get_note(nid)
            model = note.note_type()
            if model["name"] != "ChineseVocabulary":
                continue
            field_names = [f["name"] for f in model["flds"]]
            if "Simplified" not in field_names:
                continue

            simplified = re.sub(r"<[^>]+>", "", note["Simplified"]).strip()
            if not simplified:
                continue

            # Only multi-character words
            word_chars = {c for c in simplified if "\u4e00" <= c <= "\u9fff" or "\u3400" <= c <= "\u4dbf"}
            if len(word_chars) < 2 or len(simplified) < 2:
                continue

            if word_chars <= known_chars:
                if "hanly" in [t.lower() for t in note.tags]:
                    already_tagged += 1
                else:
                    candidates.append((nid, simplified))

        return candidates, already_tagged
    finally:
        col.close()


CHANGELOG_FILE = Path("/home/vincent/anki/changelog.jsonl")


def _log_change(action, note_ids=None, details=None):
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


def tag_hanly(note_ids):
    """Add 'hanly' tag to the given note IDs. Returns count tagged."""
    from anki.collection import Collection
    col = Collection(COLLECTION_PATH)
    try:
        count = 0
        tagged_ids = []
        for nid in note_ids:
            note = col.get_note(nid)
            if "hanly" not in [t.lower() for t in note.tags]:
                note.tags.append("hanly")
                col.update_note(note)
                tagged_ids.append(nid)
                count += 1
        if tagged_ids:
            _log_change("tag_hanly", tagged_ids)
        return count
    finally:
        col.close()


def main():
    if len(sys.argv) < 2:
        print("Usage: analyze_json.py <file.json> [--tag-hanly]")
        sys.exit(1)

    filepath = sys.argv[1]
    do_tag = "--tag-hanly" in sys.argv

    with open(filepath) as f:
        data = json.load(f)

    # Save as snapshot
    snap_path = save_snapshot(data)
    print(f"Saved snapshot: {snap_path.name}\n")

    # Structure analysis
    print("=== Structure ===")
    print(analyze_structure(data))

    # Filter to mastered words only
    words_dict = extract_chinese_words(data)
    mastered = {w for w, p in words_dict.items() if p >= 1.0}
    mastered_chars = extract_characters(mastered)

    # Diff against previous
    prev = get_previous_snapshot()
    if prev:
        print("\n=== Diff vs Previous ===")
        lines, mastered, mastered_chars = diff_snapshots(data, prev)
        print("\n".join(lines))

    # Hanly candidates (multi-char words made from mastered characters only)
    if mastered_chars:
        print(f"\n=== Hanly Candidates (multi-char words from {len(mastered_chars)} mastered chars) ===")
        candidates, already = find_hanly_candidates(mastered_chars)
        print(f"Already tagged 'hanly': {already}")
        print(f"New candidates: {len(candidates)}")
        if candidates:
            for nid, simp in candidates[:20]:
                print(f"  {simp} (note {nid})")
            if len(candidates) > 20:
                print(f"  ... +{len(candidates) - 20} more")

        if do_tag and candidates:
            count = tag_hanly([nid for nid, _ in candidates])
            print(f"\nTagged {count} notes with 'hanly'")

    print("\nDone.")


if __name__ == "__main__":
    main()
