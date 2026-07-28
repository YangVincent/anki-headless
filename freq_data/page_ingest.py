#!/usr/bin/env python3
"""Process one uploaded page photo end to end, unattended.

Called by the upload endpoint (dong app, behind /chinese/reader/ auth) as a detached
subprocess so a 30-60s OCR never blocks an HTTP request. Runs the same two steps that
were previously manual:

    page_marks.py   marked words -> study table + known-set calibration (reading_marks.json)
    page_view.py    photo + marks -> generated/pageview/page-NNN.html

Writes generated/pageview/status/<page>.json throughout so the browser can poll and
show progress, then land on the finished page.

  page_ingest.py --page 007 --photo <jpg> --marked 词1 词2 ...
"""
import argparse
import json
import subprocess
import sys
import traceback
from datetime import datetime
from pathlib import Path

ROOT = Path("/home/vincent/anki-headless")
PY = ROOT / ".venv/bin/python"            # paddleocr + jieba live here
DONG_PY = Path("/home/vincent/chinese-projects/dong-chinese/server/venv/bin/python")
BOOK_TXT = "/home/vincent/chinese-projects/ebooks/shiri_zhongyan_vol1.txt"
STATUS = ROOT / "generated/pageview/status"


def set_status(page, state, msg, **extra):
    STATUS.mkdir(parents=True, exist_ok=True)
    (STATUS / f"{page}.json").write_text(json.dumps(
        {"page": page, "state": state, "message": msg,
         "updated": datetime.now().isoformat(timespec="seconds"), **extra},
        ensure_ascii=False), encoding="utf-8")


def run(cmd, env_extra=None):
    import os
    env = {**os.environ, **(env_extra or {})}
    p = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=1800)
    if p.returncode != 0:
        raise RuntimeError(f"{cmd[1]} failed:\n{p.stdout[-800:]}\n{p.stderr[-800:]}")
    return p.stdout


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--page", required=True)
    ap.add_argument("--photo", required=True)
    ap.add_argument("--marked", nargs="*", default=[])
    ap.add_argument("--book", default="十日终焉·囚笼")
    a = ap.parse_args()

    try:
        set_status(a.page, "running", "recording marked words…")
        # page_marks needs the dong venv (report_data -> sqlalchemy); page_view needs the
        # anki venv (paddleocr). Each gets the interpreter it can actually import under.
        if a.marked:
            out = run([str(DONG_PY), str(ROOT / "freq_data/page_marks.py"),
                       "--book", a.book, "--page", a.page, "--src", BOOK_TXT,
                       "--marked", *a.marked])
            tally = next((l.strip() for l in out.splitlines() if "substantial" in l), "")
            set_status(a.page, "running", "rendering page image and overlay…", tally=tally)
        else:
            tally = ""
            set_status(a.page, "running", "no marked words given — rendering photo only")

        run([str(PY), str(ROOT / "freq_data/page_view.py"),
             "--book", a.book, "--page", a.page, "--photo", a.photo],
            env_extra={"FLAGS_use_mkldnn": "0"})   # oneDNN path crashes in this build

        set_status(a.page, "done", "ready", tally=tally,
                   url=f"page-{a.page}.html", marked=len(a.marked))
    except Exception as e:
        set_status(a.page, "error", str(e)[:600], trace=traceback.format_exc()[-1200:])
        sys.exit(1)


if __name__ == "__main__":
    main()
