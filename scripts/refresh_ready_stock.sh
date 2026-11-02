#!/bin/bash
# Rebuilds the two reseller lists that come from Drive and pushes them if they changed:
# data/ready_stock.csv (newest Accurate snapshot) and data/preorder.csv (team sheet, publisher files, Booky Scout).
# Run by the Claude desktop scheduled task "refresh-ready-stock" (10:20 and 15:20), since launchd jobs can't read ~/Documents or Drive.
# A run where nothing changed does nothing.
set -euo pipefail
cd "$(dirname "$0")/.."
echo "== $(date '+%Y-%m-%d %H:%M')"
/usr/bin/python3 scripts/ready_stock.py
/usr/bin/python3 scripts/preorder.py
files="data/ready_stock.csv data/preorder.csv"
if git diff --quiet -- $files; then echo 'no change'; exit 0; fi
as_of=$(sed -n '2p' data/ready_stock.csv | awk -F, '{print $NF}')
git commit -q -m "Reseller lists from Drive: ready stock $as_of, pre-order $(date +%F)" -- $files
git pull -q --rebase --autostash
git push -q
echo "pushed reseller lists (ready stock as of $as_of)"
