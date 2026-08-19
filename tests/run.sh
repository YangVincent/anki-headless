#!/usr/bin/env bash
# Run the test suite against a private copy of the collection.
#
# Read-only with respect to the real collection: the fixture copies it, redirects
# bot.COLLECTION_PATH at the copy, and checks the real file's size and mtime at exit.
# If a test ever touches it, the suite aborts with exit 9 rather than passing quietly.
#
# Takes about 20s: each test gets its own copy (0.37s) so a test that writes cannot
# affect the next one.
set -uo pipefail
cd /home/vincent/anki-headless
exec .venv/bin/python -m unittest discover -s tests -t . "$@"
