#!/usr/bin/env python3
"""Normal sync of the collection to AnkiWeb (no media). Reports status.
Does NOT force a full upload — if FULL_SYNC is required, stops and reports."""
import os, json, sys
from anki.collection import Collection
from anki.sync import SyncAuth

AUTH=os.path.expanduser("~/.anki_auth")
data=json.load(open(AUTH))
auth=SyncAuth(); auth.hkey=data["hkey"]
if data.get("endpoint"): auth.endpoint=data["endpoint"]

col=Collection("/home/vincent/anki-headless/collection.anki2")
try:
    # login state / server endpoint
    out=col.sync_collection(auth, sync_media=False)
    if out.new_endpoint:
        auth.endpoint=out.new_endpoint
        json.dump({"hkey":auth.hkey,"endpoint":auth.endpoint}, open(AUTH,"w"))
        os.chmod(AUTH,0o600)
    NO_CHANGES,NORMAL,FULL = 0,1,2
    req=out.required
    if req==NO_CHANGES:
        print("SYNC: already in sync, no changes needed.")
    elif req==NORMAL:
        print("SYNC: normal sync completed — local changes uploaded/merged.")
    elif req==FULL:
        print("SYNC: FULL SYNC REQUIRED — server and local diverged.")
        print("  Not forcing automatically (a full upload would overwrite any")
        print("  phone-side changes). Decide direction before proceeding.")
        sys.exit(2)
    else:
        print(f"SYNC: completed (status {req}).")
finally:
    col.close()
