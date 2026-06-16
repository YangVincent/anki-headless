#!/usr/bin/env python3
"""Build a calibration filtered deck: 25 unseen Vocab cards at each of 5 freq
depths (zipf ~5,4.5,4,3.5,3), tagged 'calibration', gathered into a filtered
deck the user can study. Reschedule ON so answers hit the revlog. Run via anki_op.sh."""
import re, json, random
from anki.collection import Collection
from wordfreq import zipf_frequency
random.seed(7)
ROOT="/home/vincent/anki-headless"
def clean(s): return re.sub(r'<[^>]+>','',s or '').strip()

col=Collection(f"{ROOT}/collection.anki2")
try:
    cv=next(m for m in col.models.all() if m['name']=='ChineseVocabulary'); fi={f['name']:i for i,f in enumerate(cv['flds'])}; SEP=chr(31)
    vd=col.decks.id_for_name("Vocab")
    # all NEW, non-suspended forward Vocab cards with their word+zipf
    rows=col.db.all("SELECT c.id,n.id,n.flds FROM cards c JOIN notes n ON c.nid=n.id WHERE c.did=? AND c.ord=0 AND c.type=0 AND c.queue!=-1", vd)
    pool=[]
    for cid,nid,flds in rows:
        w=clean(flds.split(SEP)[fi['Simplified']])
        if w and re.fullmatch(r'[一-鿿]+',w): pool.append((cid,nid,w,zipf_frequency(w,'zh')))
    chosen=[]
    for target in [5.0,4.5,4.0,3.5,3.0]:
        band=[p for p in pool if target-0.15<=p[3]<target+0.15]
        random.shuffle(band)
        pick=band[:25]
        chosen.extend((cid,nid,w,z,target) for cid,nid,w,z in pick)
        print(f"  zipf ~{target}: {len(pick)} cards")
    # tag the notes
    nids=list({nid for _,nid,_,_,_ in chosen})
    col.tags.bulk_add(nids,"calibration")
    json.dump([{"nid":nid,"word":w,"zipf":round(z,2),"band":t} for _,nid,w,z,t in chosen],
              open(f"{ROOT}/freq_data/calibration_cards.json","w"), ensure_ascii=False)
    # create filtered deck
    d=col.sched.get_or_create_filtered_deck(deck_id=0)
    d.name="Calibration"
    d.config.reschedule=True
    del d.config.search_terms[:]
    st=d.config.search_terms.add(); st.search="deck:Vocab tag:calibration"; st.limit=200; st.order=0
    col.sched.add_or_update_filtered_deck(d)
    cal_did=col.decks.id_for_name("Calibration")
    gathered=col.db.scalar("SELECT COUNT(*) FROM cards WHERE did=?",cal_did)
    print(f"tagged {len(nids)} notes; filtered deck 'Calibration' gathered {gathered} cards")
finally:
    col.close()
