#!/bin/bash
# Rebuilds the two reseller lists that come from Drive and pushes them if they changed:
# data/ready_stock.csv (newest Accurate snapshot for the centre, Jubelio for online and the Jakarta stores) and data/preorder.csv (team sheet, publisher files, Booky Scout).
# Run by the Claude desktop scheduled task "refresh-ready-stock" (10:20 and 15:20), since launchd jobs can't read ~/Documents or Drive.
# A run where nothing changed does nothing.
# The commit is made in a throwaway worktree on origin/main, so work sitting unpushed on local main never goes out with it.
set -euo pipefail
cd "$(dirname "$0")/.."
echo "== $(date '+%Y-%m-%d %H:%M')"
git fetch -q origin
# online and Jakarta store stock come from Jubelio: use the catalog the 04:00 sync pushed, not this Mac's copy
cat=$(mktemp); git show origin/main:data/catalog.csv > "$cat"
CATALOG="$cat" /usr/bin/python3 scripts/ready_stock.py
rm -f "$cat"
/usr/bin/python3 scripts/preorder.py
files="data/ready_stock.csv data/preorder.csv"
if git diff --quiet origin/main -- $files; then echo 'no change'; exit 0; fi
as_of=$(sed -n '2p' data/ready_stock.csv | awk -F, '{print $NF}')
wt=$(mktemp -d)
trap 'git worktree remove --force "$wt" 2>/dev/null || true' EXIT
git worktree add -q --detach "$wt" origin/main
for f in $files; do cp "$f" "$wt/$f"; done
git -C "$wt" commit -q -m "Reseller lists from Drive: ready stock $as_of, pre-order $(date +%F)" -- $files
git -C "$wt" push -q origin HEAD:main
git pull -q --rebase --autostash || echo 'pushed; local main not updated (run git pull --rebase by hand)'
echo "pushed reseller lists (ready stock as of $as_of)"
