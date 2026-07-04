#!/usr/bin/env python3
"""Populate CustomFreq (tier + zipf + stars) on every Vocab ChineseVocabulary
note, and add a frequency line to the card back template. Idempotent — safe to
re-run after new cards are added. Dry-run unless --apply. Run via anki_op.sh.
NOTE: the template edit bumps the notetype schema -> next sync is a full upload."""
import re, sys, csv
from anki.collection import Collection
from wordfreq import zipf_frequency

ROOT="/home/vincent/anki-headless"
APPLY="--apply" in sys.argv

# --- segmentation-fragment detector ----------------------------------------
# wordfreq's Chinese wordlist inflates the zipf of cross-boundary bigrams
# (开会+要 -> "会要", 一个+中 -> "个中"), so junk like 会要/个中 gets badged
# "★★★★★ very common". jieba is an independent check: for a genuine word it
# keeps the token whole and has a real whole-word frequency; for a fragment it
# splits the token AND has zero whole-word frequency. NOTE: this over-catches —
# it also flags real but low-freq literary/compound words (人中=philtrum, 他者,
# 日至=solstice). So we FLAG for human review, never auto-relabel or suspend.
_FREQ = None
def is_fragment(word):
    global _FREQ
    if _FREQ is None:
        import jieba
        jieba.initialize(); _FREQ = jieba.dt.FREQ
        is_fragment._cut = lambda w: list(jieba.cut(w, HMM=False))
    if len(word) < 2 or not re.fullmatch(r"[一-鿿]+", word):
        return False
    return len(is_fragment._cut(word)) > 1 and _FREQ.get(word, 0) == 0

def scan_fragments(col, cv, fi, vd, out_path=f"{ROOT}/freq_data/frag_triage.csv",
                   min_zipf=4.5, active_only=True):
    """Write suspect fragments (high wordfreq zipf but jieba says fragment) to CSV
    for review. Read-only. Run periodically / after mining to catch inflated cards
    before they sort to the front of the queue. See suspend_frags.py to act on it."""
    q = ("SELECT n.id,n.flds FROM cards c JOIN notes n ON c.nid=n.id "
         "WHERE c.did=? AND n.mid=?" + (" AND c.queue!=-1" if active_only else ""))
    rows, out = col.db.all(q, vd, cv["id"]), []
    for nid, flds in rows:
        f = flds.split(chr(31))
        w = re.sub(r"<[^>]+>", "", f[fi["Simplified"]]).strip()
        z = zipf_frequency(w, "zh")
        if z >= min_zipf and is_fragment(w):
            out.append((round(z, 2), w, nid, "/".join(is_fragment._cut(w)),
                        f[fi["Meaning"]][:60]))
    out.sort(reverse=True)
    with open(out_path, "w", newline="") as fh:
        cw = csv.writer(fh); cw.writerow(["wf_zipf","word","nid","jieba_seg","meaning"])
        cw.writerows(out)
    print(f"flagged {len(out)} suspect fragments -> {out_path} (review before suspending)")
    return out

def badge(word):
    z = zipf_frequency(word, "zh")
    if z >= 5:    tier, stars = "very common", 5
    elif z >= 4:  tier, stars = "common", 4
    elif z >= 3.5: tier, stars = "mid", 3
    elif z >= 3:  tier, stars = "uncommon", 2
    elif z > 0:   tier, stars = "rare", 1
    else:         return "rare · zipf 0"
    return f"{'★'*stars} {tier} · zipf {z:.1f}"

FREQ_TMPL = ('{{#CustomFreq}}<div class="freqbadge" '
             'style="font-size:11px;color:#9aa;margin-top:6px">{{CustomFreq}}</div>'
             '{{/CustomFreq}}')

col=Collection(f"{ROOT}/collection.anki2")
try:
    SEP=chr(31)
    cv=next(m for m in col.models.all() if m["name"]=="ChineseVocabulary")
    fi={f["name"]:i for i,f in enumerate(cv["flds"])}
    vd=col.decks.id_for_name("Vocab")
    if "--scan-fragments" in sys.argv:
        scan_fragments(col, cv, fi, vd); sys.exit(0)
    nids=col.db.list("SELECT DISTINCT n.id FROM cards c JOIN notes n ON c.nid=n.id WHERE c.did=? AND n.mid=?", vd, cv["id"])
    print(f"Vocab ChineseVocabulary notes: {len(nids)}")
    tmpl_has = FREQ_TMPL.split('"')[0] in cv["tmpls"][0]["afmt"] or "freqbadge" in cv["tmpls"][0]["afmt"]
    print(f"template already shows frequency: {tmpl_has}")
    if APPLY:
        updated=0
        for nid in nids:
            note=col.get_note(nid)
            w=re.sub(r"<[^>]+>","",note.fields[fi["Simplified"]]).strip()
            if not w: continue
            val=badge(w)
            if note.fields[fi["CustomFreq"]] != val:
                note.fields[fi["CustomFreq"]]=val
                col.update_note(note); updated+=1
        print(f"populated CustomFreq on {updated} notes")
        if not tmpl_has:
            # insert the frequency line right after the Meaning block on the back
            t=cv["tmpls"][0]
            anchor='<div class=wordtype>{{Meaning}}</div>'
            if anchor in t["afmt"]:
                t["afmt"]=t["afmt"].replace(anchor, anchor+"\n"+FREQ_TMPL, 1)
            else:
                t["afmt"]=t["afmt"]+"\n"+FREQ_TMPL
            col.models.update_dict(cv)
            print("added frequency line to card back template (schema changed -> full sync needed)")
        else:
            print("template unchanged")
    else:
        print("DRY-RUN. sample badges:", [badge(w) for w in ["的","朋友","央行","残酷","犄角"]])
finally:
    col.close()
