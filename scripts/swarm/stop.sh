#!/usr/bin/env bash
set -euo pipefail

SESSION_PREFIX="${SESSION_PREFIX:-bb-agent}"

sessions="$(tmux ls -F '#S' 2>/dev/null | grep "^${SESSION_PREFIX}-" || true)"

if [[ -z "${sessions}" ]]; then
  echo "[stop] no sessions with prefix ${SESSION_PREFIX}"
  exit 0
fi

while IFS= read -r s; do
  [[ -z "${s}" ]] && continue
  echo "[stop] killing ${s}"
  tmux kill-session -t "${s}"
done <<< "${sessions}"

echo "[stop] done"
