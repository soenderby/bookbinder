#!/usr/bin/env bash
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
SESSION_PREFIX="${SESSION_PREFIX:-bb-agent}"

safe_run() {
  local context="$1"
  shift
  if "$@"; then
    return 0
  fi

  echo "(${context} failed)" >&2
  return 1
}

echo "== tmux sessions =="
if command -v tmux >/dev/null 2>&1; then
  tmux_sessions="$(tmux ls 2>/dev/null | grep "^${SESSION_PREFIX}-" || true)"
  if [[ -n "${tmux_sessions}" ]]; then
    printf '%s\n' "${tmux_sessions}"
  else
    echo "(none)"
  fi
else
  echo "(tmux not installed)"
fi

echo
echo "== worktrees =="
safe_run "git worktree list" git worktree list || true

echo
echo "== currently claimed beads =="
if command -v bd >/dev/null 2>&1; then
  if claimed_beads_output="$(
    bd list --status in_progress --sort updated --reverse --limit 20 2>&1
  )"; then
    if [[ -n "${claimed_beads_output}" ]]; then
      printf '%s\n' "${claimed_beads_output}"
    else
      echo "(none)"
    fi
  else
    printf '%s\n' "${claimed_beads_output}" >&2
    echo "(bd list --status in_progress failed)" >&2
  fi
else
  echo "(bd not installed)"
fi

echo
echo "== Recently closed beads"
if command -v bd >/dev/null 2>&1; then
  safe_run "bd list" bd list --status closed --limit 10 || true
else
  echo "(bd not installed)"
fi

echo
echo "== beads ready =="
if command -v bd >/dev/null 2>&1; then
  safe_run "bd ready" bd ready --limit 10 || true
else
  echo "(bd not installed)"
fi

echo
echo "== recent logs =="
ls -1 "${ROOT}/agent-logs" 2>/dev/null || echo "(no logs yet)"
