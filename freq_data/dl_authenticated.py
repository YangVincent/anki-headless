#!/usr/bin/env python3
"""Download all manifest files via the authenticated Drive API (bypasses the
anonymous throttle). Refreshes the gcloud token periodically. Skips existing,
guards disk. Preserves the folder's directory structure under BASE."""
import json, os, os.path as osp, re, shutil, subprocess, time, urllib.request, urllib.error

ROOT = "/home/vincent/anki-headless/freq_data/textbooks"
BASE = osp.join(ROOT, "Learning Mandarin Material (DO NOT SELL) @binkybing")
MIN_FREE_GB = 3.0
man = json.load(open("/tmp/drive_manifest.json"))

def token():
    return subprocess.check_output(["gcloud", "auth", "print-access-token"], text=True).strip()

tok = token(); tok_t = time.time()
done = skip = fail = 0
fails = []
total = len(man)
for i, e in enumerate(man, 1):
    target = osp.join(BASE, e["path"])
    if osp.exists(target) and osp.getsize(target) > 0:
        skip += 1; continue
    if shutil.disk_usage(ROOT).free / 1e9 < MIN_FREE_GB:
        print(f"[ABORT] free disk < {MIN_FREE_GB}GB at {i}/{total}", flush=True); break
    if time.time() - tok_t > 2400:           # refresh every 40 min
        tok = token(); tok_t = time.time()
    fid = re.search(r"id=([\w-]+)", e["url"]).group(1)
    os.makedirs(osp.dirname(target), exist_ok=True)
    url = f"https://www.googleapis.com/drive/v3/files/{fid}?alt=media&supportsAllDrives=true"
    for attempt in (1, 2):
        try:
            req = urllib.request.Request(url, headers={"Authorization": f"Bearer {tok}"})
            with urllib.request.urlopen(req, timeout=300) as r, open(target, "wb") as f:
                shutil.copyfileobj(r, f)
            if osp.getsize(target) > 0:
                done += 1
            else:
                fail += 1; fails.append((e["path"], "empty"))
            break
        except urllib.error.HTTPError as ex:
            if ex.code == 401 and attempt == 1:
                tok = token(); tok_t = time.time(); continue   # token expired mid-run
            fail += 1; fails.append((e["path"], f"HTTP {ex.code}"))
            if osp.exists(target) and osp.getsize(target) == 0: os.remove(target)
            break
        except Exception as ex:
            fail += 1; fails.append((e["path"], str(ex)[:100]))
            if osp.exists(target) and osp.getsize(target) == 0: os.remove(target)
            break
    if i % 15 == 0 or i == total:
        print(f"[{i}/{total}] done={done} skip={skip} fail={fail} "
              f"free={shutil.disk_usage(ROOT).free/1e9:.1f}GB", flush=True)

print(f"\nFINISHED: downloaded={done} skipped={skip} failed={fail} (total={total})", flush=True)
if fails:
    json.dump(fails, open("/tmp/dl_auth_failures.json", "w"), ensure_ascii=False, indent=1)
    print(f"failures -> /tmp/dl_auth_failures.json ({len(fails)})", flush=True)
    for p, er in fails[:10]:
        print(f"  FAIL {p[:65]} :: {er}", flush=True)
