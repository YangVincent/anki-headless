"""Sync to AnkiWeb and report what actually moved.

WHY THIS EXISTS. All three sync call sites logged the same misleading line. They printed
`SyncCollectionResponse.required`, which is the state AFTER the sync, and then wrote
English that reads like a statement about what the sync DID:

    bot.py            required == 0  ->  "Synced (no changes needed)"
    anki_common.py    required == 0  ->  "nothing further to send"
    cli.py            required == 0  ->  "Already in sync, no changes needed."

Zero after a sync means "nothing is left pending". It does not mean nothing was sent, and
the two are opposites when the sync just uploaded something. On 2026-09-02 a run changed
602 notes; the very next periodic sync uploaded all of them and logged "Synced (no changes
needed)". Every one of the last 58 sync lines in the bot log says that, so the log cannot
distinguish a busy sync from an idle one, and it cannot answer "did my change reach my
phone" -- the one question anybody reads it for.

The response carries no counts, so this measures them first. Anki stamps `usn = -1` on
every row it changes locally and clears it on a successful sync, which makes the pending
set exactly countable BEFORE the call and verifiable after.
"""

# (table, plural noun) for every table Anki marks with usn = -1 when it changes locally.
# `graves` is the deletion log; a delete that never reaches the server comes back on the
# next download, so it belongs in the count as much as an edit does.
PENDING = (
    ("notes", "note", "notes"),
    ("cards", "card", "cards"),
    ("decks", "deck", "decks"),
    ("notetypes", "note type", "note types"),
    ("graves", "deletion", "deletions"),
)

NO_CHANGES, NORMAL_SYNC, FULL_SYNC, FULL_DOWNLOAD, FULL_UPLOAD = range(5)


class Report(str):
    """The status line, plus whether it describes a healthy sync.

    A str subclass so every existing caller that prints or formats it keeps working.
    `ok` exists because the bot used to decide log severity by searching the message for
    "failed" / "error" -- and the first clear message this module produced, "nothing left
    pending", contains the word "pending" and was logged as an ERROR. Severity is a fact
    the sync knows; it must not be re-derived from English.
    """

    def __new__(cls, message: str, ok: bool):
        self = super().__new__(cls, message)
        self.ok = ok
        return self


def pending(col) -> dict:
    """Rows this collection has changed but not yet sent, by table. Empty dict if none."""
    out = {}
    for table, one, many in PENDING:
        try:
            n = col.db.scalar(f"select count() from {table} where usn = -1") or 0
        except Exception:
            continue          # a table this Anki version does not have
        if n:
            out[one if n == 1 else many] = n
    return out


def describe(counts: dict) -> str:
    """'602 notes and 1,806 cards', or 'nothing'."""
    if not counts:
        return "nothing"
    return " and ".join(f"{n:,} {noun}" for noun, n in counts.items())


def sync(col, auth, *, media: bool = False) -> str:
    """Sync, and return a line that says what was sent and what remains.

    The two halves are always both present, because either one alone is ambiguous:
    "sent nothing" and "nothing left" look identical in a log that prints only one.
    """
    outgoing = pending(col)
    result = col.sync_collection(auth, sync_media=media)

    # AnkiWeb can move an account to a different server and tells you once, in this
    # response. Dropping it costs the next sync a redirect, so update the caller's auth
    # in place; the caller decides whether to persist it.
    if result.new_endpoint:
        auth.endpoint = result.new_endpoint

    if result.required == FULL_SYNC:
        return Report(f"FULL SYNC REQUIRED — {describe(outgoing)} still unsent. "
                      f"Resolve by hand: anki-cli sync --upload | --download", ok=False)
    if result.required == FULL_DOWNLOAD:
        return Report("server has newer data — a full download is required", ok=False)
    if result.required == FULL_UPLOAD:
        return Report("local has newer data — a full upload is required", ok=False)

    left = pending(col)
    sent = "sent nothing (already in sync)" if not outgoing else f"sent {describe(outgoing)}"
    if left:
        return Report(f"{sent}; {describe(left)} STILL PENDING", ok=False)
    if result.required == NORMAL_SYNC:
        return Report(f"{sent}; the server reports more to apply", ok=True)
    return Report(f"{sent}; nothing left pending", ok=True)
