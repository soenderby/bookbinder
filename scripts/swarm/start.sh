#!/usr/bin/env bash
set -euo pipefail

COUNT="${1:-2}"
ROOT="$(git rev-parse --show-toplevel)"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SESSION_PREFIX="${SESSION_PREFIX:-bb-agent}"
AGENT_MODEL="${AGENT_MODEL:-gpt-5.3-codex}"
AGENT_COMMAND="${AGENT_COMMAND:-codex exec --dangerously-bypass-approvals-and-sandbox --model ${AGENT_MODEL}}"
PROMPT_TEMPLATE="${PROMPT_TEMPLATE:-${ROOT}/scripts/swarm/AGENT_PROMPT.md}"
POLL_SECONDS="${POLL_SECONDS:-20}"

"${SCRIPT_DIR}/setup-worktrees.sh" "${COUNT}"

for i in $(seq 1 "${COUNT}"); do
  session="${SESSION_PREFIX}-${i}"
  worktree="${ROOT}/worktrees/agent-${i}"

  if tmux has-session -t "${session}" 2>/dev/null; then
    echo "[start] session ${session} already running"
    continue
  fi

  echo "[start] launching ${session} in ${worktree}"
  tmux_cmd="$(printf "cd %q && AGENT_NAME=%q WORKTREE=%q AGENT_MODEL=%q AGENT_COMMAND=%q POLL_SECONDS=%q PROMPT_TEMPLATE=%q %q" \
    "${ROOT}" \
    "agent-${i}" \
    "${worktree}" \
    "${AGENT_MODEL}" \
    "${AGENT_COMMAND}" \
    "${POLL_SECONDS}" \
    "${PROMPT_TEMPLATE}" \
    "${SCRIPT_DIR}/agent-loop.sh")"
  tmux new-session -d -s "${session}" "${tmux_cmd}"
done

echo "[start] running sessions:"
tmux ls | grep "^${SESSION_PREFIX}-" || true
