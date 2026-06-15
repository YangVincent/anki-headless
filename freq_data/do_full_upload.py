#!/usr/bin/env python3
"""Force a full UPLOAD of the local collection to AnkiWeb (needed after the
template schema change). Aborts if the server unexpectedly has newer data."""
import os, json
from anki.collection import Collection
from anki.sync import SyncAuth

AUTH=os.path.expanduser("~/.anki_auth")
data=json.load(open(AUTH))
auth=SyncAuth(); auth.hkey=data["hkey"]
if data.get("endpoint"): auth.endpoint=data["endpoint"]

NO_CHANGES,NORMAL,FULL,FULL_DL,FULL_UL = 0,1,2,3,4
col=Collection("/home/vincent/anki-headless/collection.anki2")
try:
    res=col.sync_collection(auth, sync_media=False)
    if res.new_endpoint:
        auth.endpoint=res.new_endpoint
        json.dump({"hkey":auth.hkey,"endpoint":auth.endpoint}, open(AUTH,"w")); os.chmod(AUTH,0o600)
    req=res.required
    if req in (FULL, FULL_UL):
        print(f"Full sync required (status {req}); uploading local -> AnkiWeb ...")
        col.full_upload_or_download(auth=auth, server_usn=res.server_media_usn, upload=True)
        print("FULL UPLOAD COMPLETE.")
    elif req==FULL_DL:
        print("ABORT: server has NEWER data (FULL_DOWNLOAD). Not overwriting it.")
        print("  Resolve manually — phone may have un-synced changes.")
        raise SystemExit(2)
    elif req==NORMAL:
        print("Normal sync completed (no full sync needed).")
    elif req==NO_CHANGES:
        print("Already in sync.")
    else:
        print(f"Sync status {req}.")
finally:
    col.close()
