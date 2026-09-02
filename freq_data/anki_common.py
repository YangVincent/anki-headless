"""Shared helpers for the collection-mutating scripts (park/hsk/leech/reinstate/…).

Was copy-pasted `_sync` in nine scripts; centralized here. The one behavioral change is
that the backend sync now runs OFF the main thread: anki/_backend.py prints a full stack
trace ("blocked main thread for Nms") for any backend call that runs on the main thread
longer than 0.2s. That guard exists to catch UI-freezing calls in the desktop app; a
headless CLI has no UI thread to protect, so every sync tripped it with noise. Running the
call on a worker thread makes `current_thread() is main_thread()` false, so the guard never
fires — which is exactly what it's asking for.
"""
import json
import threading
from pathlib import Path

AUTH_FILE = Path("~/.anki_auth").expanduser()


def off_main(fn, *args, **kwargs):
    """Run a (slow) Anki backend call on a worker thread and return its result, so Anki's
    main-thread-blocking diagnostic stays quiet. Exceptions propagate to the caller."""
    box: dict = {}

    def worker():
        try:
            box["value"] = fn(*args, **kwargs)
        except BaseException as exc:  # noqa: BLE001 — re-raised on the calling thread below
            box["error"] = exc

    t = threading.Thread(target=worker, name="anki-backend")
    t.start()
    t.join()
    if "error" in box:
        raise box["error"]
    return box["value"]


def sync(col, *, media: bool = False) -> None:
    """Push the collection to AnkiWeb and print a one-line status.

    The status used to come from `out.required`, which is the state AFTER the sync. It
    printed "nothing further to send" for a sync that had just uploaded everything, so
    the line could not tell a busy sync from an idle one. anki_sync counts the unsent
    rows first and reports both halves.
    """
    import sys
    from pathlib import Path as _Path
    sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))
    import anki_sync
    from anki.sync import SyncAuth

    cred = json.loads(AUTH_FILE.read_text())
    auth = SyncAuth()
    auth.hkey = cred["hkey"]
    if cred.get("endpoint"):
        auth.endpoint = cred["endpoint"]
    print("sync: " + off_main(anki_sync.sync, col, auth, media=media))
