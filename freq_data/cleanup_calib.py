from anki.collection import Collection
col=Collection("/home/vincent/anki-headless/collection.anki2")
try:
    did=col.decks.id_for_name("Calibration")
    if did:
        try: col.sched.empty_filtered_deck(did)
        except Exception as e: print("empty:",e)
        col.decks.remove([did]); print("removed Calibration deck")
    nids=col.find_notes("tag:calibration")
    if nids: col.tags.bulk_remove(list(nids),"calibration"); print(f"removed tag from {len(nids)} notes")
    print("Calibration cards still in Vocab/new:", col.db.scalar("SELECT COUNT(*) FROM cards c JOIN notes n ON c.nid=n.id WHERE n.id IN (%s)"%','.join(map(str,nids)) if nids else "SELECT 0"))
finally:
    col.close()
