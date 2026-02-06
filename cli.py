#!/usr/bin/env python3
"""Anki CLI — full terminal interface to an Anki collection."""

import argparse
import getpass
import json
import os
import re
import sys
import time

DEFAULT_COLLECTION = "/home/vincent/anki/collection.anki2"
AUTH_FILE = os.path.expanduser("~/.anki_auth")


def strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text)


def open_collection(path: str):
    from anki.collection import Collection
    return Collection(path)


def save_auth(hkey: str, endpoint: str | None):
    data = {"hkey": hkey, "endpoint": endpoint or ""}
    with open(AUTH_FILE, "w") as f:
        json.dump(data, f)
    os.chmod(AUTH_FILE, 0o600)


def load_auth():
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


# ── Deck commands ──────────────────────────────────────────────────────

def cmd_deck_list(args):
    col = open_collection(args.collection)
    try:
        decks = col.decks.all_names_and_ids()
        if not decks:
            print("No decks found.")
            return
        for d in decks:
            count = len(col.find_cards(f'"deck:{d.name}"'))
            print(f"  {d.name}  ({count} cards)")
    finally:
        col.close()


def cmd_deck_create(args):
    col = open_collection(args.collection)
    try:
        col.decks.id_for_name(args.name)
        print(f"Deck created: {args.name}")
    finally:
        col.close()


def cmd_deck_rename(args):
    col = open_collection(args.collection)
    try:
        did = col.decks.id_for_name(args.old)
        if not did:
            print(f"Deck not found: {args.old}", file=sys.stderr)
            sys.exit(1)
        deck = col.decks.get(did)
        deck["name"] = args.new
        col.decks.save(deck)
        print(f"Renamed '{args.old}' -> '{args.new}'")
    finally:
        col.close()


def cmd_deck_delete(args):
    col = open_collection(args.collection)
    try:
        did = col.decks.id_for_name(args.name)
        if not did:
            print(f"Deck not found: {args.name}", file=sys.stderr)
            sys.exit(1)
        col.decks.remove([did])
        print(f"Deleted deck: {args.name}")
    finally:
        col.close()


# ── Card/Note commands ─────────────────────────────────────────────────

def cmd_add(args):
    col = open_collection(args.collection)
    try:
        did = col.decks.id_for_name(args.deck)
        if not did:
            print(f"Deck not found: {args.deck}", file=sys.stderr)
            sys.exit(1)

        notetype_name = args.notetype or "Basic"
        model = col.models.by_name(notetype_name)
        if not model:
            print(f"Note type not found: {notetype_name}", file=sys.stderr)
            sys.exit(1)

        note = col.new_note(model)

        if args.fields:
            values = args.fields.split("::")
            field_names = [f["name"] for f in model["flds"]]
            for i, val in enumerate(values):
                if i < len(field_names):
                    note[field_names[i]] = val
        else:
            if args.front is not None:
                note["Front"] = args.front
            if args.back is not None:
                note["Back"] = args.back

        if args.tags:
            note.tags = args.tags.split(",")

        col.add_note(note, did)
        print(f"Added note {note.id} to '{args.deck}'")
    finally:
        col.close()


def cmd_list(args):
    col = open_collection(args.collection)
    try:
        query = args.query or ""
        card_ids = col.find_cards(query)
        if not card_ids:
            print("No cards found.")
            return
        for cid in card_ids:
            card = col.get_card(cid)
            note = card.note()
            fields = [strip_html(f) for f in note.fields]
            preview = " | ".join(fields)
            if len(preview) > 100:
                preview = preview[:97] + "..."
            deck_name = col.decks.name(card.did)
            print(f"  [{cid}] ({deck_name}) {preview}")
    finally:
        col.close()


def cmd_show(args):
    col = open_collection(args.collection)
    try:
        card = col.get_card(args.card_id)
        note = card.note()
        model = note.note_type()
        field_names = [f["name"] for f in model["flds"]]

        print(f"Card ID:   {card.id}")
        print(f"Note ID:   {note.id}")
        print(f"Deck:      {col.decks.name(card.did)}")
        print(f"Note Type: {model['name']}")
        print(f"Tags:      {' '.join(note.tags) if note.tags else '(none)'}")
        print()
        for i, name in enumerate(field_names):
            val = strip_html(note.fields[i]) if i < len(note.fields) else ""
            print(f"── {name} ──")
            print(val)
            print()

        # Card stats
        queue_names = {0: "new", 1: "learning", 2: "review", 3: "relearning", -1: "suspended", -2: "buried"}
        print(f"Queue:     {queue_names.get(card.queue, card.queue)}")
        print(f"Interval:  {card.ivl} days")
        print(f"Ease:      {card.factor / 10}%")
        print(f"Reviews:   {card.reps}")
        print(f"Lapses:    {card.lapses}")
    finally:
        col.close()


def cmd_edit(args):
    col = open_collection(args.collection)
    try:
        note = col.get_note(args.note_id)
        model = note.note_type()
        field_names = [f["name"] for f in model["flds"]]

        if args.front is not None and "Front" in field_names:
            note["Front"] = args.front
        if args.back is not None and "Back" in field_names:
            note["Back"] = args.back
        if args.fields is not None:
            values = args.fields.split("::")
            for i, val in enumerate(values):
                if i < len(field_names):
                    note[field_names[i]] = val

        col.update_note(note)
        print(f"Updated note {note.id}")
    finally:
        col.close()


def cmd_delete(args):
    col = open_collection(args.collection)
    try:
        col.remove_notes(args.note_ids)
        print(f"Deleted {len(args.note_ids)} note(s)")
    finally:
        col.close()


# ── Review commands ────────────────────────────────────────────────────

def cmd_review(args):
    col = open_collection(args.collection)
    try:
        query = "is:due"
        if args.deck:
            query = f'"deck:{args.deck}" is:due'

        card_ids = col.find_cards(query)
        if not card_ids:
            # Also check for new cards
            query_new = "is:new"
            if args.deck:
                query_new = f'"deck:{args.deck}" is:new'
            card_ids = col.find_cards(query_new)

        if not card_ids:
            print("No cards to review!")
            return

        print(f"Found {len(card_ids)} card(s) to review. Press Ctrl+C to stop.\n")
        reviewed = 0

        for cid in card_ids:
            card = col.get_card(cid)
            note = card.note()
            model = note.note_type()
            field_names = [f["name"] for f in model["flds"]]

            # Show front
            front_idx = 0
            front_text = strip_html(note.fields[front_idx]) if note.fields else "(empty)"
            deck_name = col.decks.name(card.did)
            print(f"─── [{deck_name}] Card {cid} ───")
            print(f"\n{front_text}\n")

            input("  [Press Enter to show answer]")

            # Show all fields (back)
            for i, name in enumerate(field_names):
                if i == 0:
                    continue
                val = strip_html(note.fields[i]) if i < len(note.fields) else ""
                print(f"\n  {name}: {val}")

            print("\n  Rate: 1=Again  2=Hard  3=Good  4=Easy")
            while True:
                try:
                    choice = input("  > ").strip()
                    if choice in ("1", "2", "3", "4"):
                        break
                    print("  Enter 1-4")
                except EOFError:
                    print()
                    return

            # Answer the card using the scheduler
            from anki.consts import BUTTON_ONE, BUTTON_TWO, BUTTON_THREE, BUTTON_FOUR
            buttons = {"1": BUTTON_ONE, "2": BUTTON_TWO, "3": BUTTON_THREE, "4": BUTTON_FOUR}
            col.sched.answer_card(card, buttons[choice])
            reviewed += 1
            print()

        print(f"Session complete! Reviewed {reviewed} card(s).")
    except KeyboardInterrupt:
        print(f"\nStopped. Reviewed {reviewed} card(s).")
    finally:
        col.close()


def cmd_due(args):
    col = open_collection(args.collection)
    try:
        if args.deck:
            prefix = f'"deck:{args.deck}"'
        else:
            prefix = ""

        new_count = len(col.find_cards(f"{prefix} is:new".strip()))
        due_count = len(col.find_cards(f"{prefix} is:due".strip()))
        learn_count = len(col.find_cards(f"{prefix} is:learn".strip()))

        print(f"  New:      {new_count}")
        print(f"  Learning: {learn_count}")
        print(f"  Due:      {due_count}")
    finally:
        col.close()


# ── Note type commands ─────────────────────────────────────────────────

def cmd_notetype_list(args):
    col = open_collection(args.collection)
    try:
        models = col.models.all_names_and_ids()
        for m in models:
            model = col.models.get(m.id)
            field_names = [f["name"] for f in model["flds"]]
            print(f"  {m.name}: {', '.join(field_names)}")
    finally:
        col.close()


# ── Tag commands ───────────────────────────────────────────────────────

def cmd_tag_list(args):
    col = open_collection(args.collection)
    try:
        tags = col.tags.all()
        if not tags:
            print("No tags found.")
            return
        for t in sorted(tags):
            print(f"  {t}")
    finally:
        col.close()


def cmd_tag_add(args):
    col = open_collection(args.collection)
    try:
        note = col.get_note(args.note_id)
        for tag in args.tags:
            note.tags.append(tag)
        col.update_note(note)
        print(f"Added tags to note {args.note_id}: {', '.join(args.tags)}")
    finally:
        col.close()


def cmd_tag_remove(args):
    col = open_collection(args.collection)
    try:
        note = col.get_note(args.note_id)
        for tag in args.tags:
            note.tags = [t for t in note.tags if t.lower() != tag.lower()]
        col.update_note(note)
        print(f"Removed tags from note {args.note_id}: {', '.join(args.tags)}")
    finally:
        col.close()


# ── Import/Export commands ─────────────────────────────────────────────

def cmd_import(args):
    col = open_collection(args.collection)
    try:
        from anki.importing.apkg import AnkiPackageImporter
        imp = AnkiPackageImporter(col, args.file)
        imp.run()
        print(f"Imported: {args.file}")
    finally:
        col.close()


def cmd_export(args):
    col = open_collection(args.collection)
    try:
        from anki.exporting import AnkiPackageExporter
        exp = AnkiPackageExporter(col)
        if args.deck:
            did = col.decks.id_for_name(args.deck)
            if not did:
                print(f"Deck not found: {args.deck}", file=sys.stderr)
                sys.exit(1)
            exp.did = did
        exp.exportInto(args.file)
        print(f"Exported to: {args.file}")
    finally:
        col.close()


# ── Stats command ──────────────────────────────────────────────────────

def cmd_stats(args):
    col = open_collection(args.collection)
    try:
        total_notes = col.note_count()
        total_cards = col.card_count()
        new_count = len(col.find_cards("is:new"))
        due_count = len(col.find_cards("is:due"))
        learn_count = len(col.find_cards("is:learn"))
        review_count = len(col.find_cards("is:review"))
        suspended = len(col.find_cards("is:suspended"))
        buried = len(col.find_cards("is:buried"))

        print(f"  Total notes:  {total_notes}")
        print(f"  Total cards:  {total_cards}")
        print()
        print(f"  New:          {new_count}")
        print(f"  Learning:     {learn_count}")
        print(f"  Review:       {review_count}")
        print(f"  Due:          {due_count}")
        print(f"  Suspended:    {suspended}")
        print(f"  Buried:       {buried}")
    finally:
        col.close()


# ── Sync commands ──────────────────────────────────────────────────────

def cmd_sync_login(args):
    username = args.username or input("AnkiWeb username (email): ")
    password = args.password or getpass.getpass("AnkiWeb password: ")

    col = open_collection(args.collection)
    try:
        auth = col.sync_login(username=username, password=password, endpoint=None)
        save_auth(auth.hkey, auth.endpoint if auth.endpoint else None)
        print("Login successful! Auth token saved.")
    finally:
        col.close()


def cmd_sync(args):
    auth = load_auth()
    if auth is None:
        print("Not logged in. Run: anki-cli sync login", file=sys.stderr)
        sys.exit(1)

    col = open_collection(args.collection)
    try:
        # SyncCollectionResponse.ChangesRequired enum values
        NO_CHANGES = 0
        NORMAL_SYNC = 1
        FULL_SYNC = 2
        FULL_DOWNLOAD = 3
        FULL_UPLOAD = 4

        # Always call sync_collection first to get endpoint and server info
        print("Syncing...")
        result = col.sync_collection(auth, sync_media=False)

        # Update auth with new endpoint if provided
        if result.new_endpoint:
            auth.endpoint = result.new_endpoint
            save_auth(auth.hkey, auth.endpoint)

        server_msg = result.server_message
        if server_msg:
            print(f"Server: {server_msg}")

        changes = result.required

        if changes == NO_CHANGES:
            print("Already in sync, no changes needed.")
        elif changes == NORMAL_SYNC:
            print("Sync complete.")
        elif changes == FULL_SYNC:
            print("Full sync required.")
            if args.upload:
                print("Uploading local collection to AnkiWeb...")
                col.full_upload_or_download(auth=auth, server_usn=result.server_media_usn, upload=True)
                print("Full upload complete.")
            elif args.download:
                print("Downloading collection from AnkiWeb...")
                col.full_upload_or_download(auth=auth, server_usn=result.server_media_usn, upload=False)
                print("Full download complete.")
            else:
                print("Use --upload or --download to resolve full sync.")
                print("  --upload   = overwrite AnkiWeb with local data")
                print("  --download = overwrite local with AnkiWeb data")
                sys.exit(1)
        elif changes == FULL_DOWNLOAD:
            print("Server has newer data. Downloading...")
            col.full_upload_or_download(auth=auth, server_usn=result.server_media_usn, upload=False)
            print("Download complete.")
        elif changes == FULL_UPLOAD:
            print("Local has newer data. Uploading...")
            col.full_upload_or_download(auth=auth, server_usn=result.server_media_usn, upload=True)
            print("Upload complete.")
        else:
            print(f"Sync complete (status: {changes}).")

        # Sync media unless skipped
        if not args.no_media and changes != FULL_SYNC:
            print("Syncing media...")
            col.sync_media(auth)
            print("Media sync started in background.")
    finally:
        col.close()


def cmd_sync_status(args):
    auth = load_auth()
    if auth is None:
        print("Not logged in. Run: anki-cli sync login", file=sys.stderr)
        sys.exit(1)

    col = open_collection(args.collection)
    try:
        status = col.sync_status(auth)
        names = {0: "No changes", 1: "Normal sync needed", 2: "Full sync needed"}
        print(f"  Status: {names.get(status.required, f'Unknown ({status.required})')}")
    finally:
        col.close()


def cmd_sync_logout(args):
    if os.path.exists(AUTH_FILE):
        os.remove(AUTH_FILE)
        print("Logged out. Auth token removed.")
    else:
        print("Not logged in.")


# ── Argument parser ────────────────────────────────────────────────────

def build_parser():
    parser = argparse.ArgumentParser(prog="anki-cli", description="Anki CLI wrapper")
    parser.add_argument("--collection", "-c", default=DEFAULT_COLLECTION,
                        help="Path to collection.anki2")
    sub = parser.add_subparsers(dest="command")

    # deck
    deck_parser = sub.add_parser("deck", help="Deck management")
    deck_sub = deck_parser.add_subparsers(dest="deck_command")

    deck_sub.add_parser("list", help="List all decks")

    dc = deck_sub.add_parser("create", help="Create a deck")
    dc.add_argument("name")

    dr = deck_sub.add_parser("rename", help="Rename a deck")
    dr.add_argument("old")
    dr.add_argument("new")

    dd = deck_sub.add_parser("delete", help="Delete a deck")
    dd.add_argument("name")

    # add
    add_p = sub.add_parser("add", help="Add a card/note")
    add_p.add_argument("deck")
    add_p.add_argument("--front", "-f")
    add_p.add_argument("--back", "-b")
    add_p.add_argument("--notetype", "-n", help="Note type name (default: Basic)")
    add_p.add_argument("--fields", help="Fields separated by :: for custom note types")
    add_p.add_argument("--tags", "-t", help="Comma-separated tags")

    # list
    list_p = sub.add_parser("list", help="Search/list cards")
    list_p.add_argument("query", nargs="?", default="")

    # show
    show_p = sub.add_parser("show", help="Show card details")
    show_p.add_argument("card_id", type=int)

    # edit
    edit_p = sub.add_parser("edit", help="Edit a note")
    edit_p.add_argument("note_id", type=int)
    edit_p.add_argument("--front", "-f")
    edit_p.add_argument("--back", "-b")
    edit_p.add_argument("--fields", help="Fields separated by ::")

    # delete
    del_p = sub.add_parser("delete", help="Delete notes")
    del_p.add_argument("note_ids", type=int, nargs="+")

    # review
    rev_p = sub.add_parser("review", help="Interactive review session")
    rev_p.add_argument("deck", nargs="?")

    # due
    due_p = sub.add_parser("due", help="Show due card counts")
    due_p.add_argument("deck", nargs="?")

    # notetype
    nt_parser = sub.add_parser("notetype", help="Note type management")
    nt_sub = nt_parser.add_subparsers(dest="notetype_command")
    nt_sub.add_parser("list", help="List note types and fields")

    # tag
    tag_parser = sub.add_parser("tag", help="Tag management")
    tag_sub = tag_parser.add_subparsers(dest="tag_command")
    tag_sub.add_parser("list", help="List all tags")

    ta = tag_sub.add_parser("add", help="Add tags to a note")
    ta.add_argument("note_id", type=int)
    ta.add_argument("tags", nargs="+")

    tr = tag_sub.add_parser("remove", help="Remove tags from a note")
    tr.add_argument("note_id", type=int)
    tr.add_argument("tags", nargs="+")

    # import
    imp_p = sub.add_parser("import", help="Import an .apkg file")
    imp_p.add_argument("file")

    # export
    exp_p = sub.add_parser("export", help="Export to .apkg file")
    exp_p.add_argument("file")
    exp_p.add_argument("--deck", "-d")

    # stats
    sub.add_parser("stats", help="Show collection stats")

    # sync
    sync_parser = sub.add_parser("sync", help="Sync with AnkiWeb")
    sync_parser.add_argument("--upload", action="store_true", help="Force full upload")
    sync_parser.add_argument("--download", action="store_true", help="Force full download")
    sync_parser.add_argument("--no-media", action="store_true", help="Skip media sync")
    sync_sub = sync_parser.add_subparsers(dest="sync_command")

    login_p = sync_sub.add_parser("login", help="Log in to AnkiWeb")
    login_p.add_argument("--username", "-u")
    login_p.add_argument("--password", "-p")

    sync_sub.add_parser("status", help="Check sync status")
    sync_sub.add_parser("logout", help="Remove saved auth token")

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    dispatch = {
        "deck": lambda: {
            "list": cmd_deck_list,
            "create": cmd_deck_create,
            "rename": cmd_deck_rename,
            "delete": cmd_deck_delete,
        }.get(args.deck_command, lambda a: print("Usage: anki-cli deck {list|create|rename|delete}"))(args),

        "add": lambda: cmd_add(args),
        "list": lambda: cmd_list(args),
        "show": lambda: cmd_show(args),
        "edit": lambda: cmd_edit(args),
        "delete": lambda: cmd_delete(args),
        "review": lambda: cmd_review(args),
        "due": lambda: cmd_due(args),

        "notetype": lambda: {
            "list": cmd_notetype_list,
        }.get(args.notetype_command, lambda a: print("Usage: anki-cli notetype {list}"))(args),

        "tag": lambda: {
            "list": cmd_tag_list,
            "add": cmd_tag_add,
            "remove": cmd_tag_remove,
        }.get(args.tag_command, lambda a: print("Usage: anki-cli tag {list|add|remove}"))(args),

        "import": lambda: cmd_import(args),
        "export": lambda: cmd_export(args),
        "stats": lambda: cmd_stats(args),

        "sync": lambda: {
            "login": cmd_sync_login,
            "status": cmd_sync_status,
            "logout": cmd_sync_logout,
            None: lambda a: cmd_sync(a),
        }.get(args.sync_command, lambda a: cmd_sync(a))(args),
    }

    handler = dispatch.get(args.command)
    if handler:
        handler()
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
