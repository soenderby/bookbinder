#!/usr/bin/env bash
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
SESSION_PREFIX="${SESSION_PREFIX:-bb-agent}"

echo "== tmux sessions =="
tmux ls 2>/dev/null | grep "^${SESSION_PREFIX}-" || echo "(none)"

echo
echo "== worktrees =="
git worktree list

echo
echo "== beads ready =="
bd ready --limit 20 || true

echo
echo "== recent logs =="
ls -1 "${ROOT}/agent-logs" 2>/dev/null || echo "(no logs yet)"
