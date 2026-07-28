#!/usr/bin/env python3
"""Propose which words were underlined on a photographed page.

Measured behaviour of the two halves (page 006, 48 real marks):
  * detecting the pencil strokes works well — 43 found, landing on real underlines
  * OCR'ing a crop above a stroke to read the word does NOT — 13/33 usable, because a
    2-4 character crop gives the recognizer no context and underline extents don't line
    up with word boundaries

So this never OCRs the crop. It maps each stroke's x-range onto the OCR'd LINE text
(line recognition is accurate), widens the window a couple of characters to absorb
mapping drift, segments that window with jieba, and offers the resulting words as
CANDIDATES. Vincent confirms them in the upload form — nothing is recorded unconfirmed,
because a wrong entry silently corrupts the known-set calibration.

  page_propose.py --page 007 --photo <jpg>   ->  status/<page>.propose.json
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, "/home/vincent/anki-headless/freq_data")

OUT = Path("/home/vincent/anki-headless/generated/pageview")
STATUS = OUT / "status"
HAN = re.compile(r"[一-鿿]")
OCR_PX = 1400        # OCR resolution (bigger OOMs on this box)
DET_PX = 2400        # detection resolution (pencil strokes vanish when smaller)
PAD_CHARS = 5        # widen the mapped window; interpolation drifts by a char or two


def detect_strokes(img_bgr, min_w=40, max_h=10, min_ratio=8):
    """Long, thin, near-horizontal dark strokes = hand-drawn underlines."""
    import cv2
    g = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    bw = cv2.adaptiveThreshold(g, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                               cv2.THRESH_BINARY_INV, 31, 10)
    ker = cv2.getStructuringElement(cv2.MORPH_RECT, (min_w, 1))
    hor = cv2.morphologyEx(bw, cv2.MORPH_OPEN, ker)
    _, _, stats, _ = cv2.connectedComponentsWithStats(hor, 8)
    out = []
    for s in stats[1:]:
        x, y, w, h = s[0], s[1], s[2], s[3]
        if w >= min_w and h <= max_h and w / max(h, 1) >= min_ratio:
            out.append((int(x), int(y), int(w), int(h)))
    out.sort(key=lambda s: (s[1], s[0]))
    return out


def main():
    import cv2
    import jieba
    from PIL import Image
    from page_view import ocr_lines, word_quad  # noqa: F401  (shared OCR settings)

    ap = argparse.ArgumentParser()
    ap.add_argument("--page", required=True)
    ap.add_argument("--photo", required=True)
    a = ap.parse_args()

    im = Image.open(a.photo)
    if im.width > im.height:
        im = im.rotate(-90, expand=True)

    det = im.copy(); det.thumbnail((DET_PX, DET_PX), Image.LANCZOS)
    ocr_im = im.copy(); ocr_im.thumbnail((OCR_PX, OCR_PX), Image.LANCZOS)
    dpath, opath = STATUS / f"_det{a.page}.png", STATUS / f"_ocr{a.page}.png"
    STATUS.mkdir(parents=True, exist_ok=True)
    det.save(dpath); ocr_im.save(opath)

    strokes = detect_strokes(cv2.imread(str(dpath)))
    lines = [l for l in ocr_lines(opath)
             if l["score"] >= 0.90
             and len(HAN.findall(l["text"])) / max(len(l["text"]), 1) >= 0.6
             and (max(p[0] for p in l["quad"]) - min(p[0] for p in l["quad"])) >= 0.25 * ocr_im.width]
    scale = ocr_im.width / det.width      # detection coords -> OCR coords

    proposals = []
    for (x, y, w, h) in strokes:
        sx, sy, sw = x * scale, y * scale, w * scale
        # the line this stroke sits under: its bottom edge should be just above the stroke
        best, bestd = None, 1e9
        for ln in lines:
            xs = [p[0] for p in ln["quad"]]; ys = [p[1] for p in ln["quad"]]
            if sx + sw < min(xs) or sx > max(xs):
                continue
            d = abs(sy - max(ys))
            if d < bestd and d < 0.6 * (max(ys) - min(ys)) + 12:
                best, bestd = ln, d
        if not best:
            continue
        xs = [p[0] for p in best["quad"]]
        left, width = min(xs), max(xs) - min(xs)
        text = best["text"]; n = len(text)
        i0 = max(0, int((sx - left) / width * n) - PAD_CHARS)
        i1 = min(n, int((sx + sw - left) / width * n) + PAD_CHARS)
        window = text[i0:i1]
        cands = [t for t in jieba.cut(window) if HAN.search(t)]
        if not cands:
            continue
        proposals.append({"window": window,
                          "candidates": cands,
                          "best": max(cands, key=len)})

    # de-duplicate consecutive identical suggestions from one long underline
    seen, clean = set(), []  # dedup by window, not best-guess
    for p in proposals:
        key = p["window"]
        if key in seen:
            continue
        seen.add(key); clean.append(p)

    (STATUS / f"{a.page}.propose.json").write_text(json.dumps(
        {"page": a.page, "strokes": len(strokes), "lines": len(lines),
         "proposals": clean}, ensure_ascii=False), encoding="utf-8")
    for f in (dpath, opath):
        f.unlink(missing_ok=True)
    print(f"{len(strokes)} strokes, {len(lines)} lines -> {len(clean)} proposals")


if __name__ == "__main__":
    main()
