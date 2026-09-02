#!/bin/sh
# The whole pipe, in order, the same three commands the cloud runs at 22:00
# UTC (.github/workflows/nightly.yml). For a manual run on this Mac.
set -e
cd "$(dirname "$0")"
python3 pool.py
python3 judge.py
python3 results.py
