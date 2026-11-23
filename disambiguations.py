"""Versioned registry for vocabulary distinctions shown in Anki and the dashboard."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

REGISTRY_PATH = Path(__file__).with_name("disambiguations.json")
_ID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class RegistryError(ValueError):
    pass


def validate_registry(data: dict) -> dict:
    if not isinstance(data, dict) or data.get("version") != 1:
        raise RegistryError("registry must be an object with version 1")
    categories = data.get("categories")
    groups = data.get("groups")
    if not isinstance(categories, list) or not isinstance(groups, list):
        raise RegistryError("categories and groups must be lists")

    category_ids = []
    for category in categories:
        if not isinstance(category, dict):
            raise RegistryError("each category must be an object")
        cid = category.get("id")
        if not isinstance(cid, str) or not _ID.fullmatch(cid):
            raise RegistryError(f"invalid category id: {cid!r}")
        if not isinstance(category.get("label"), str) or not category["label"].strip():
            raise RegistryError(f"category {cid!r} needs a label")
        category_ids.append(cid)
    if len(category_ids) != len(set(category_ids)):
        raise RegistryError("category ids must be unique")

    group_ids = []
    for group in groups:
        if not isinstance(group, dict):
            raise RegistryError("each group must be an object")
        gid = group.get("id")
        if not isinstance(gid, str) or not _ID.fullmatch(gid):
            raise RegistryError(f"invalid group id: {gid!r}")
        if group.get("category") not in category_ids:
            raise RegistryError(f"group {gid!r} has unknown category {group.get('category')!r}")
        if not isinstance(group.get("rule"), str) or not group["rule"].strip():
            raise RegistryError(f"group {gid!r} needs a decision rule")
        if "title" in group and (not isinstance(group["title"], str) or not group["title"].strip()):
            raise RegistryError(f"group {gid!r} has an invalid title")
        members = group.get("members")
        if not isinstance(members, list) or len(members) < 2:
            raise RegistryError(f"group {gid!r} needs at least two members")
        words = []
        for member in members:
            if not isinstance(member, dict):
                raise RegistryError(f"group {gid!r} has a non-object member")
            word = member.get("word")
            cue = member.get("cue")
            if not isinstance(word, str) or not word.strip():
                raise RegistryError(f"group {gid!r} has a member without a word")
            if not isinstance(cue, str) or not cue.strip():
                raise RegistryError(f"group {gid!r} member {word!r} needs a cue")
            if "pattern" in member and not isinstance(member["pattern"], str):
                raise RegistryError(f"group {gid!r} member {word!r} has a non-string pattern")
            words.append(word)
        if len(words) != len(set(words)):
            raise RegistryError(f"group {gid!r} contains a word more than once")
        group_ids.append(gid)
    if len(group_ids) != len(set(group_ids)):
        raise RegistryError("group ids must be unique")
    return data


def load_registry(path: str | Path = REGISTRY_PATH) -> dict:
    with Path(path).open(encoding="utf-8") as handle:
        return validate_registry(json.load(handle))


def upsert_group(group: dict, path: str | Path = REGISTRY_PATH) -> dict:
    path = Path(path)
    data = load_registry(path)
    groups = data["groups"]
    for index, existing in enumerate(groups):
        if existing["id"] == group.get("id"):
            groups[index] = group
            break
    else:
        groups.append(group)
    validate_registry(data)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temp, path)
    return data
