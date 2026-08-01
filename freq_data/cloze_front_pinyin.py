#!/usr/bin/env python3
"""Show the sentence's reading, with the target word's syllables blanked, on the cloze front.

The Cloze-Recall front gave only the blanked hanzi sentence, so a sentence you couldn't
read yet was unreadable — the pinyin sat on the back, where it arrives too late to help
you attempt the sentence. This puts the reading on the front with the answer's syllables
replaced by "[ ]", so the sentence can be read aloud without handing over the word.

The blank is computed in the template at render time rather than stored in a new field:
adding a field to a notetype bumps the schema stamp and forces a FULL sync, which would
discard any reviews sitting unsynced on a phone. Editing a template is a normal sync
(verified on a scratch copy before writing this).

Matching folds both strings to letters-only lowercase, so it survives the spacing and
apostrophe differences between the two fields ("fāng àn" vs "fāng'àn"), then retries
tone-insensitively to absorb sandhi (bù/bú, yī/yì), then tries each reading of a
multi-reading Pinyin field ("mì mǎ; mì ma"). That covers 17387/17448 cloze cards; the
remaining 61 have genuine typos in their stored SentencePinyin (说服 recorded as "shuìfú",
常识 as "chánshí") and fall back to showing no pinyin, exactly as before this change.

Usage: bash freq_data/anki_op.sh cloze-front-pinyin freq_data/cloze_front_pinyin.py --apply
"""
import argparse
import re

from anki.collection import Collection

ROOT = "/home/vincent/anki-headless"
MARKER = "cz-pinyin-out"

BLOCK = """
{{#SentencePinyin}}
<div id="cz-pinyin-src" style="display:none"><span id="cz-pinyin-sent">{{SentencePinyin}}</span><span id="cz-pinyin-word">{{Pinyin}}</span></div>
<div class="reading" id="cz-pinyin-out"></div>
<script>
(function () {
  var out = document.getElementById("cz-pinyin-out");
  if (!out) return;
  out.textContent = "";
  var sentEl = document.getElementById("cz-pinyin-sent");
  var wordEl = document.getElementById("cz-pinyin-word");
  if (!sentEl || !wordEl) return;
  var sent = (sentEl.textContent || "").trim();
  var word = (wordEl.textContent || "").trim();
  if (!sent) return;

  // letters only, lowercased; map[i] is where norm[i] sat in the original string
  function fold(s, dropTones) {
    var norm = "", map = [];
    for (var i = 0; i < s.length; i++) {
      var base = s[i].normalize("NFD").replace(/[\\u0300-\\u036f]/g, "");
      if (!/^[a-zA-Z]$/.test(base)) continue;
      norm += (dropTones ? base : s[i]).toLowerCase();
      map.push(i);
    }
    return [norm, map];
  }

  var readings = word.split(/[;,\\u3001\\uff0c/\\n()\\uff08\\uff09]/)
    .map(function (x) { return x.trim(); })
    .filter(function (x) { return x; });

  var result = null;
  for (var pass = 0; pass < 2 && !result; pass++) {
    for (var k = 0; k < readings.length && !result; k++) {
      var S = fold(sent, pass === 1), W = fold(readings[k], pass === 1);
      if (!W[0]) continue;
      var at = S[0].indexOf(W[0]);
      if (at < 0) continue;
      result = sent.slice(0, S[1][at]) + "[ ]" + sent.slice(S[1][at + W[0].length - 1] + 1);
    }
  }
  if (result) out.textContent = result;
})();
</script>
{{/SentencePinyin}}
""".rstrip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=f"{ROOT}/collection.anki2")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--revert", action="store_true")
    args = ap.parse_args()

    col = Collection(args.db)
    try:
        scm_before = col.db.scalar("select scm from col")
        nt = col.models.by_name("ChineseVocabulary")
        tmpl = next(t for t in nt["tmpls"] if t["name"] == "Cloze-Recall")
        qfmt = tmpl["qfmt"]
        present = MARKER in qfmt

        if args.revert:
            new = re.sub(r"\n\{\{#SentencePinyin\}\}.*?\{\{/SentencePinyin\}\}", "",
                         qfmt, flags=re.S)
        elif present:
            print("already installed — nothing to do")
            return
        else:
            # sits inside the existing SentenceSimplifiedCloze guard, under the sentence
            anchor = "<div class=chinese>{{SentenceSimplifiedCloze}}</div>"
            if anchor not in qfmt:
                print(f"ERROR: anchor not found in front template:\n{qfmt}")
                return
            new = qfmt.replace(anchor, anchor + BLOCK)

        print("--- new front template ---")
        print(new)
        if args.apply:
            tmpl["qfmt"] = new
            col.models.save(nt)
            scm_after = col.db.scalar("select scm from col")
            print(f"\nschema stamp {scm_before} -> {scm_after}: "
                  f"{'FULL SYNC REQUIRED' if scm_after != scm_before else 'normal sync'}")
            again = next(t for t in col.models.by_name("ChineseVocabulary")["tmpls"]
                         if t["name"] == "Cloze-Recall")
            print(f"verify: marker present on front = {MARKER in again['qfmt']}")
            print(f"verify: back untouched = {MARKER not in again['afmt']}")
        else:
            print("\nDRY-RUN — nothing written.")
    finally:
        col.close()


if __name__ == "__main__":
    main()
