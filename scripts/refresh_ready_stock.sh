#!/bin/bash
# Rebuilds the pre-order list from Drive (team sheet, publisher files, Booky Scout) and pushes it if it changed.
# Ready stock moved to GitHub (scripts/ready_stock.py --drive), which reads the shared Accurate folder itself.
# Run by the Claude desktop scheduled task "refresh-ready-stock" (10:20 and 15:20), since launchd jobs can't read ~/Documents or Drive.
# A run where nothing changed does nothing.
# The commit is made in a throwaway worktree on origin/main, so work sitting unpushed on local main never goes out with it.
set -euo pipefail
cd "$(dirname "$0")/.."
echo "== $(date '+%Y-%m-%d %H:%M')"
git fetch -q origin
# ready_stock.csv is built on GitHub now (04:00, 12:00, 15:00) from the shared Drive folder; this Mac keeps the pre-order list
/usr/bin/python3 scripts/preorder.py
files="data/preorder.csv"
if git diff --quiet origin/main -- $files; then echo 'no change'; exit 0; fi
wt=$(mktemp -d)
trap 'git worktree remove --force "$wt" 2>/dev/null || true' EXIT
git worktree add -q --detach "$wt" origin/main
for f in $files; do cp "$f" "$wt/$f"; done
git -C "$wt" commit -q -m "Pre-order list from Drive $(date +%F)" -- $files
git -C "$wt" push -q origin HEAD:main
git pull -q --rebase --autostash || echo 'pushed; local main not updated (run git pull --rebase by hand)'
echo "pushed pre-order list"
