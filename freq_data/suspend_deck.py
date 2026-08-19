#!/usr/bin/env python3
"""Suspend every card in one deck (and its subdecks). Reversible with unsuspend.

Usage: bash freq_data/anki_op.sh <label> freq_data/suspend_deck.py "<Deck Name>" --apply
"""
import sys, time
sys.path.insert(0, "/home/vincent/anki-headless")
import bot

args = [a for a in sys.argv[1:] if a != "--apply"]
APPLY = "--apply" in sys.argv
if not args:
    print('usage: suspend_deck.py "<Deck Name>" [--apply]'); sys.exit(1)
DECK = args[0]

col = None
for _ in range(30):
    try:
        col = bot.open_collection(); break
    except Exception:
        time.sleep(2)
if col is None:
    print("collection locked"); sys.exit(1)

try:
    if col.decks.id_for_name(DECK) is None:
        print(f"no deck named {DECK!r}"); sys.exit(1)
    cids = list(col.find_cards(f'"deck:{DECK}"'))
    live = [c for c in cids if col.get_card(c).queue != -1]
    reviewed = sum(1 for c in cids if col.get_card(c).reps > 0)
    print(f"{DECK!r}: {len(cids)} cards, {len(live)} unsuspended, {reviewed} ever reviewed")
    print(f"would suspend: {len(live)}")
    if not APPLY:
        print("\nDRY RUN — nothing written. Add --apply to commit."); sys.exit(0)
    if live:
        col.sched.suspend_cards(live)
    still = sum(1 for c in cids if col.get_card(c).queue != -1)
    print(f"\nVERIFY  unsuspended cards left in {DECK!r}: {still}  (want 0)")
finally:
    col.close()
