#!/usr/bin/env bash
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
SESSION_PREFIX="${SESSION_PREFIX:-bb-agent}"
ORCA_STATUS_RUN_AUDIT="${ORCA_STATUS_RUN_AUDIT:-0}"

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

echo
echo "== recent run summaries =="
if summary_list="$(ls -1t "${ROOT}"/agent-logs/*-summary.md 2>/dev/null)"; then
  printf '%s\n' "${summary_list}" | head -n 10 | sed "s#^${ROOT}/##"
else
  echo "(no summaries yet)"
fi

echo
echo "== latest metrics =="
if [[ -f "${ROOT}/agent-logs/metrics.jsonl" ]]; then
  if command -v jq >/dev/null 2>&1; then
    if ! tail -n 5 "${ROOT}/agent-logs/metrics.jsonl" | jq -r '
      . as $row
      | ($row.timestamp // "unknown-time")
        + " issue=" + ($row.issue_id // "unknown-issue")
        + " result=" + ($row.result // "unknown")
        + " reason=" + ($row.reason // "unknown")
        + " total_s=" + (($row.durations_seconds.iteration_total // 0) | tostring)
        + " tokens=" + (
            if $row.tokens_used == null then "n/a"
            else ($row.tokens_used | tostring) end
          )
    '; then
      echo "(metrics parse failed)"
    fi
  else
    tail -n 5 "${ROOT}/agent-logs/metrics.jsonl"
  fi
else
  echo "(no metrics yet)"
fi

echo
echo "== consistency audit =="
if [[ ! "${ORCA_STATUS_RUN_AUDIT}" =~ ^[01]$ ]]; then
  echo "(ORCA_STATUS_RUN_AUDIT must be 0 or 1; current: ${ORCA_STATUS_RUN_AUDIT})"
elif [[ "${ORCA_STATUS_RUN_AUDIT}" -eq 1 ]]; then
  if [[ -x "${ROOT}/scripts/orca/audit-consistency.sh" ]]; then
    if ! "${ROOT}/scripts/orca/audit-consistency.sh"; then
      echo "(consistency audit reported issues)" >&2
    fi
  else
    echo "(audit script not found)"
  fi
else
  echo "(skipped by default; run './bb orca audit-consistency' or set ORCA_STATUS_RUN_AUDIT=1)"
fi
