#!/usr/bin/env bash
# Daily: release cloze cards for newly-matured Vocab words. Runs via the safe wrapper.
cd /home/vincent/anki-headless || exit 1
bash freq_data/anki_op.sh cloze-gate freq_data/cloze_gate.py --apply >> /home/vincent/.anki_cloze_gate.log 2>&1
