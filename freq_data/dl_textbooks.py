#!/usr/bin/env python3
"""Download every file in the Drive manifest via single-file gdown (no 50-file cap).
Skips files already present (non-zero size). Aborts if free disk < MIN_FREE_GB."""
import json, os, re, shutil, subprocess, sys, time

ROOT = "/home/vincent/anki-headless/freq_data/textbooks"
BASE = os.path.join(ROOT, "Learning Mandarin Material (DO NOT SELL) @binkybing")
GDOWN = "/home/vincent/anki-headless/.venv/bin/gdown"
MIN_FREE_GB = 3.0
manifest = json.load(open("/tmp/drive_manifest.json"))

def free_gb(p): return shutil.disk_usage(p).free / 1e9

done = skipped = failed = 0
fails = []
total = len(manifest)
for i, e in enumerate(manifest, 1):
    m = re.search(r"id=([\w-]+)", e["url"])
    if not m:
        fails.append((e["path"], "no-id")); failed += 1; continue
    fid = m.group(1)
    target = os.path.join(BASE, e["path"])
    if os.path.exists(target) and os.path.getsize(target) > 0:
        skipped += 1; continue
    if free_gb(ROOT) < MIN_FREE_GB:
        print(f"[ABORT] free disk {free_gb(ROOT):.1f}GB < {MIN_FREE_GB}GB, stopping at {i}/{total}", flush=True)
        break
    os.makedirs(os.path.dirname(target), exist_ok=True)
    r = subprocess.run([GDOWN, "--id", fid, "-O", target, "--quiet"],
                       capture_output=True, text=True)
    if r.returncode == 0 and os.path.exists(target) and os.path.getsize(target) > 0:
        done += 1
    else:
        failed += 1
        fails.append((e["path"], (r.stderr or "")[-200:].strip()))
        if os.path.exists(target) and os.path.getsize(target) == 0:
            os.remove(target)
    if i % 10 == 0 or i == total:
        print(f"[{i}/{total}] done={done} skip={skipped} fail={failed} free={free_gb(ROOT):.1f}GB", flush=True)

print(f"\nFINISHED: downloaded={done} skipped={skipped} failed={failed}", flush=True)
if fails:
    json.dump(fails, open("/tmp/dl_failures.json", "w"), ensure_ascii=False, indent=1)
    print(f"failures logged to /tmp/dl_failures.json ({len(fails)})", flush=True)
    for p, err in fails[:15]:
        print(f"  FAIL {p} :: {err[:80]}", flush=True)
