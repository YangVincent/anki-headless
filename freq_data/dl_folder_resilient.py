#!/usr/bin/env python3
"""Resilient resumable Drive-folder download: replicates gdown.download_folder's
loop (same uc?id session that downloaded the first 54) but skips existing files,
catches per-file errors instead of aborting, and guards disk space.
Usage: dl_folder_resilient.py <folder_url_or_id> <output_dir> [max_files]"""
import os, os.path as osp, shutil, sys, json
from gdown.download_folder import (
    _download_and_parse_google_drive_link, _get_directory_structure,
    _get_session, _sanitize_filename,
)
from gdown.download import download

FOLDER = sys.argv[1]
OUTPUT = sys.argv[2]
MAX = int(sys.argv[3]) if len(sys.argv) > 3 else 10**9
MIN_FREE_GB = 3.0
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/98.0.4758.102 Safari/537.36")

folder_id = FOLDER.rstrip("/").split("/")[-1].split("?")[0]
sess, _ = _get_session(proxy=None, use_cookies=True, user_agent=UA)
print("Retrieving folder tree...", flush=True)
gf = _download_and_parse_google_drive_link(sess=sess, folder_id=folder_id, quiet=True, verify=True)
gf.name = _sanitize_filename(filename=gf.name)
ds = _get_directory_structure(gf, previous_path="")
root_dir = osp.join(OUTPUT, gf.name)
os.makedirs(root_dir, exist_ok=True)

files = [(i, p) for i, p in ds if i is not None]
print(f"tree: {len(files)} files under {gf.name!r}", flush=True)

done = skip = fail = 0
fails = []
attempted = 0
for fid, path in files:
    local = osp.join(root_dir, path)
    if osp.exists(local) and osp.getsize(local) > 0:
        skip += 1; continue
    if shutil.disk_usage(OUTPUT).free / 1e9 < MIN_FREE_GB:
        print(f"[ABORT] free disk < {MIN_FREE_GB}GB", flush=True); break
    if attempted >= MAX:
        print(f"[STOP] hit max_files={MAX}", flush=True); break
    attempted += 1
    os.makedirs(osp.dirname(local), exist_ok=True)
    out = local if osp.splitext(local)[1] else osp.dirname(local) + os.sep
    try:
        r = download(url="https://drive.google.com/uc?id=" + fid, output=out,
                     quiet=True, use_cookies=True, verify=True, resume=False)
        if r and osp.exists(r) and osp.getsize(r) > 0:
            done += 1
        else:
            fail += 1; fails.append((path, "empty/none"))
    except Exception as e:
        fail += 1; fails.append((path, str(e)[:160].replace("\n", " ")))
        if osp.exists(local) and osp.getsize(local) == 0:
            os.remove(local)
    if (done + fail) % 10 == 0:
        print(f"  attempted={attempted} done={done} fail={fail} skip={skip} "
              f"free={shutil.disk_usage(OUTPUT).free/1e9:.1f}GB", flush=True)

print(f"\nFINISHED: done={done} skipped={skip} failed={fail} (tree={len(files)})", flush=True)
if fails:
    json.dump(fails, open("/tmp/dl_failures.json", "w"), ensure_ascii=False, indent=1)
    print(f"failures -> /tmp/dl_failures.json", flush=True)
    for p, e in fails[:8]:
        print(f"  FAIL {p[:70]} :: {e[:70]}", flush=True)
