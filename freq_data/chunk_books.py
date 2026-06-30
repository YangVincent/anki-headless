#!/usr/bin/env python3
"""Split cleaned per-book text into ~chunk-sized pieces at page boundaries, so each
piece fits comfortably in one subagent's context for lesson/essay/grammar synthesis.
Writes freq_data/chunks/<slug>__NN.txt. Re-runnable."""
import os, glob, sys

CLEAN = "/home/vincent/anki-headless/freq_data/clean"
CHUNKS = "/home/vincent/anki-headless/freq_data/chunks"
MAX = 70000  # chars per chunk (~40k tokens of Chinese)

def chunk_one(path):
    sg = os.path.splitext(os.path.basename(path))[0]
    text = open(path, encoding="utf-8").read()
    header, _, body = text.partition("\n\n")     # keep "# <title>" header
    pages = body.split("\n\n")
    chunks, cur = [], ""
    for p in pages:
        if cur and len(cur) + len(p) > MAX:
            chunks.append(cur); cur = ""
        cur += p + "\n\n"
    if cur.strip():
        chunks.append(cur)
    paths = []
    for i, c in enumerate(chunks):
        out = f"{CHUNKS}/{sg}__{i:02d}.txt"
        with open(out, "w", encoding="utf-8") as fh:
            fh.write(header + "\n\n" + c)
        paths.append(out)
    return paths

if __name__ == "__main__":
    os.makedirs(CHUNKS, exist_ok=True)
    only = sys.argv[1] if len(sys.argv) > 1 else None
    files = glob.glob(f"{CLEAN}/*.txt")
    if only:
        files = [f for f in files if only in f]
    nb = nc = 0
    for f in sorted(files):
        ps = chunk_one(f); nb += 1; nc += len(ps)
    print(f"chunked {nb} books -> {nc} chunks in {CHUNKS}/")
