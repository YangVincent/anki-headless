#!/usr/bin/env python3
"""Read the underlined words off a page photo by sending it to Claude.

Why this exists: OpenCV finds the pencil strokes fine (page_propose.py) but cannot
say which word each stroke sits under — 29-44% recall, 9-18% precision, measured.
PaddleOCR reads the LINE accurately but a 2-4 character crop gives it no context.
Reading the page as an image is the only method that has scored well, so this hands
the page to the model instead of trying to reconstruct the answer locally.

The one thing that made a difference when doing this by hand: don't look at the whole
page at once. Crop it into overlapping horizontal bands so each band arrives large
enough that a faint pencil line is visible, then stitch the per-band answers back
together in page order.

  page_read.py --photo <jpg> [--page 007] [--json]

Prints the words space-separated (paste straight into the upload form), and with
--json writes generated/pageview/status/<page>.read.json.
"""
import argparse
import base64
import io
import json
import re
import sys
from pathlib import Path

import anthropic
from PIL import Image

ROOT = Path("/home/vincent/anki-headless")
STATUS = ROOT / "generated/pageview/status"
CONFIG = json.loads((ROOT / ".bot_config.json").read_text())

MODEL = "claude-opus-5"
BANDS = 8          # a page of this novel is ~20 lines; 8 bands ≈ 2-3 lines each
OVERLAP = 0.08     # fraction of band height repeated into the next band
BAND_MAX = 2400    # long edge per band, upscaling if needed (Opus 5 tops out at 2576)
SRC_MAX = 3400     # cap the source before cropping; phone photos are bigger than useful

PROMPT = """These are overlapping horizontal bands of one page of a Chinese novel, in
reading order (band 1 is the top of the page). The page has been marked in pencil, and
the marks are faint — a thin grey line under a word, sometimes wavering, sometimes
running slightly past the word at either end.

Work through the bands one at a time. In each band, read every printed line and check
underneath it for a pencil stroke. For each stroke you find, report the line it belongs
to and the word or phrase the stroke sits under.

- Report only strokes you can actually see. Never guess which words a learner would
  probably mark, and never add a word because it looks hard or unusual.
- Equally, do not skip a stroke because the word under it looks ordinary or easy — a
  large fraction of the marks are on common words, and those are the ones most often
  missed. Faintness is not a reason to drop one either.
- Give the span the stroke covers as a single entry — not its individual characters,
  and not the whole sentence around it. A stroke that runs under two adjacent words is
  two entries.
- One line often carries several separate underlines. Check the whole width of every
  line, not just the first mark on it.
- Ignore handwriting in the margins, page numbers, headers, and any printed punctuation
  or typographic emphasis.
- Bands overlap, so a line near a band edge appears twice. Report its words once.

A typical marked page in this book carries somewhere between twenty and fifty
underlines, so if you finish a page with only a handful, go back and look again."""

SCHEMA = {
    "type": "object",
    "properties": {
        "marks": {
            "type": "array",
            "description": "One entry per pencil underline, in page order (top to bottom, "
                           "left to right).",
            "items": {
                "type": "object",
                "properties": {
                    "band": {"type": "integer", "description": "Band number the mark is in."},
                    "line": {"type": "string",
                             "description": "The printed line of text containing the "
                                            "underline, transcribed."},
                    "word": {"type": "string",
                             "description": "The word or phrase the pencil stroke sits under."},
                },
                "required": ["band", "line", "word"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["marks"],
    "additionalProperties": False,
}


def bands(photo: Path, n=BANDS):
    """Overlapping horizontal strips of the page, top to bottom.

    Strips are scaled UP to BAND_MAX when they come out small. That adds no information,
    but it does give the vision encoder several times as many patches over the same
    pencil stroke, and a faint stroke is exactly what gets lost at low patch density.
    """
    im = Image.open(photo)
    if im.mode != "RGB":
        im = im.convert("RGB")
    if im.width > im.height:                       # phone held sideways
        im = im.rotate(-90, expand=True)
    if max(im.size) > SRC_MAX:
        im.thumbnail((SRC_MAX, SRC_MAX), Image.LANCZOS)

    step = im.height / n
    pad = step * OVERLAP
    out = []
    for i in range(n):
        top = max(0, int(i * step - pad))
        bot = min(im.height, int((i + 1) * step + pad))
        crop = im.crop((0, top, im.width, bot))
        scale = BAND_MAX / max(crop.size)
        if scale != 1:
            crop = crop.resize((max(1, round(crop.width * scale)),
                                max(1, round(crop.height * scale))), Image.LANCZOS)
        buf = io.BytesIO()
        crop.save(buf, format="PNG")
        out.append(base64.standard_b64encode(buf.getvalue()).decode())
    return out


def read_page(photo: Path, n=BANDS, passes=1):
    """Read the page `passes` times and union the results.

    Misses are close to independent between runs — a stroke one pass overlooks the next
    usually catches — while false positives are rare, so the union buys recall at very
    little cost in precision.
    """
    words, usage = [], None
    for _ in range(passes):
        w, u = _one_pass(photo, n)
        words += w
        usage = u if usage is None else _add_usage(usage, u)
    return _dedupe(words), usage


class _Usage:
    def __init__(self, i, o):
        self.input_tokens, self.output_tokens = i, o


def _add_usage(a, b):
    return _Usage(a.input_tokens + b.input_tokens, a.output_tokens + b.output_tokens)


def _dedupe(words):
    """Drop repeats, and drop a span that is wholly inside one already reported."""
    out = []
    for w in words:
        if any(w == o or (len(w) >= 2 and w in o) for o in out):
            continue
        out.append(w)
    return out


def _one_pass(photo: Path, n):
    client = anthropic.Anthropic(api_key=CONFIG["anthropic_api_key"])
    content = []
    for i, b64 in enumerate(bands(photo, n), 1):
        content.append({"type": "text", "text": f"Band {i} of {n}:"})
        content.append({"type": "image",
                        "source": {"type": "base64", "media_type": "image/png", "data": b64}})
    content.append({"type": "text", "text": PROMPT})

    with client.messages.stream(
        model=MODEL,
        max_tokens=16000,
        thinking={"type": "adaptive"},
        output_config={"effort": "high", "format": {"type": "json_schema", "schema": SCHEMA}},
        messages=[{"role": "user", "content": content}],
    ) as stream:
        resp = stream.get_final_message()
    if resp.stop_reason == "refusal":
        raise RuntimeError(f"refused: {getattr(resp.stop_details, 'category', None)}")
    text = next(b.text for b in resp.content if b.type == "text")
    words = [m["word"] for m in json.loads(text)["marks"]]

    # tidy: strip punctuation/whitespace, drop non-Chinese, collapse the repeats that
    # come from band overlap (keep first occurrence, order preserved)
    clean, seen = [], set()
    for w in words:
        w = re.sub(r"[\s。，、；：？！“”‘’（）《》…—\.,;:!?\"'()]", "", w)
        if not w or not re.search(r"[一-鿿]", w) or w in seen:
            continue
        seen.add(w)
        clean.append(w)
    return clean, resp.usage


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--photo", required=True)
    ap.add_argument("--page")
    ap.add_argument("--json", action="store_true", help="also write status/<page>.read.json")
    a = ap.parse_args()

    words, usage = read_page(Path(a.photo))
    print(" ".join(words))
    print(f"[{len(words)} words | in {usage.input_tokens} out {usage.output_tokens}]",
          file=sys.stderr)

    if a.json:
        if not a.page:
            sys.exit("--json needs --page")
        STATUS.mkdir(parents=True, exist_ok=True)
        (STATUS / f"{a.page}.read.json").write_text(
            json.dumps({"page": a.page, "words": words,
                        "usage": {"input": usage.input_tokens, "output": usage.output_tokens}},
                       ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
