#!/usr/bin/env python3
"""Server-side copy of the whole manifest into the user's Drive, preserving the
folder tree, nested under an existing parent folder. Idempotent: skips folders
and files that already exist (so it's safe to re-run / resume). Refreshes the
gcloud token as needed. Nothing is downloaded or modified in the source."""
import json, subprocess, sys, time, urllib.parse, urllib.request, urllib.error

PARENT = "1PrZ17XB7xJy81-V2V5QcFYKvskQUMtLU"          # "Chinese Textbooks" (owned by user)
ROOT_NAME = "Learning Mandarin Material (DO NOT SELL) @binkybing"
man = json.load(open("/tmp/drive_manifest.json"))

_tok = {"v": None, "t": 0}
def token():
    if time.time() - _tok["t"] > 2400 or _tok["v"] is None:
        _tok["v"] = subprocess.check_output(["gcloud", "auth", "print-access-token"], text=True).strip()
        _tok["t"] = time.time()
    return _tok["v"]

def api(method, url, body=None):
    for attempt in (1, 2):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method,
            headers={"Authorization": f"Bearer {token()}", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 401 and attempt == 1:
                _tok["t"] = 0; continue
            if e.code in (403, 429, 500, 503) and attempt == 1:
                time.sleep(3); continue
            raise

def q_escape(s): return s.replace("\\", "\\\\").replace("'", "\\'")

def find_child(name, parent, folder=None):
    qy = f"'{parent}' in parents and name='{q_escape(name)}' and trashed=false"
    if folder is True:  qy += " and mimeType='application/vnd.google-apps.folder'"
    if folder is False: qy += " and mimeType!='application/vnd.google-apps.folder'"
    url = "https://www.googleapis.com/drive/v3/files?q=" + urllib.parse.quote(qy) + "&fields=files(id,name)"
    fs = api("GET", url).get("files", [])
    return fs[0]["id"] if fs else None

def ensure_folder(name, parent):
    fid = find_child(name, parent, folder=True)
    if fid: return fid
    r = api("POST", "https://www.googleapis.com/drive/v3/files",
            {"name": name, "mimeType": "application/vnd.google-apps.folder", "parents": [parent]})
    return r["id"]

# 1) root folder under "Chinese Textbooks"
root_id = ensure_folder(ROOT_NAME, PARENT)
print(f"root folder: {ROOT_NAME} -> {root_id}", flush=True)

# 2) create all directory paths, caching path -> folderId
folder_cache = {"": root_id}
def folder_for(dirpath):
    if dirpath in folder_cache: return folder_cache[dirpath]
    parent = folder_for(dirpath.rsplit("/", 1)[0] if "/" in dirpath else "")
    fid = ensure_folder(dirpath.rsplit("/", 1)[-1], parent)
    folder_cache[dirpath] = fid
    return fid

# 3) copy each file
import re
copied = skipped = failed = 0
fails = []
total = len(man)
for i, e in enumerate(man, 1):
    path = e["path"]
    src = re.search(r"id=([\w-]+)", e["url"]).group(1)
    d, name = (path.rsplit("/", 1) if "/" in path else ("", path))
    try:
        dest_folder = folder_for(d)
        if find_child(name, dest_folder, folder=False):
            skipped += 1
        else:
            api("POST", f"https://www.googleapis.com/drive/v3/files/{src}/copy",
                {"name": name, "parents": [dest_folder]})
            copied += 1
    except Exception as ex:
        failed += 1; fails.append((path, str(ex)[:120]))
    if i % 20 == 0 or i == total:
        print(f"[{i}/{total}] copied={copied} skipped={skipped} failed={failed}", flush=True)

print(f"\nFINISHED: copied={copied} skipped={skipped} failed={failed} (total={total})", flush=True)
if fails:
    json.dump(fails, open("/tmp/copy_failures.json", "w"), ensure_ascii=False, indent=1)
    for p, er in fails[:10]: print(f"  FAIL {p[:65]} :: {er}", flush=True)
