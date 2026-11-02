#!/bin/bash
# Rebuilds data/ready_stock.csv from the newest Accurate snapshot on Drive and pushes it if it changed.
# Run by the Claude desktop scheduled task "refresh-ready-stock" (10:20 and 15:20), since launchd jobs can't read ~/Documents or Drive.
# A run with no new snapshot does nothing.
set -euo pipefail
cd "$(dirname "$0")/.."
echo "== $(date '+%Y-%m-%d %H:%M')"
/usr/bin/python3 scripts/ready_stock.py
if git diff --quiet -- data/ready_stock.csv; then echo 'no change'; exit 0; fi
as_of=$(sed -n '2p' data/ready_stock.csv | awk -F, '{print $NF}')
git commit -q -m "Ready stock $as_of" -- data/ready_stock.csv
git pull -q --rebase --autostash
git push -q
echo "pushed ready stock as of $as_of"
