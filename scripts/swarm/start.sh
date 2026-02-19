#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  start.sh [count] [--runs N | --continuous]

Options:
  count         Number of worker sessions/worktrees to launch (default: 2)
  --runs N      Stop each agent loop after N completed issue runs
  --continuous  Keep each loop unbounded while ready work exists (default)
USAGE
}

COUNT=""
ROOT="$(git rev-parse --show-toplevel)"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SESSION_PREFIX="${SESSION_PREFIX:-bb-agent}"
AGENT_MODEL="${AGENT_MODEL:-gpt-5.3-codex}"
AGENT_COMMAND="${AGENT_COMMAND:-codex exec --dangerously-bypass-approvals-and-sandbox --model ${AGENT_MODEL}}"
PROMPT_TEMPLATE="${PROMPT_TEMPLATE:-${ROOT}/scripts/swarm/AGENT_PROMPT.md}"
MAX_RUNS="${MAX_RUNS:-0}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --runs)
      if [[ $# -lt 2 ]]; then
        echo "[start] --runs requires a numeric argument" >&2
        exit 1
      fi
      MAX_RUNS="$2"
      shift 2
      ;;
    --continuous)
      MAX_RUNS=0
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      if [[ -z "${COUNT}" ]]; then
        COUNT="$1"
        shift
      else
        echo "[start] unexpected argument: $1" >&2
        usage >&2
        exit 1
      fi
      ;;
  esac
done

COUNT="${COUNT:-2}"

if ! [[ "${COUNT}" =~ ^[1-9][0-9]*$ ]]; then
  echo "[start] count must be a positive integer: ${COUNT}" >&2
  exit 1
fi

if ! [[ "${MAX_RUNS}" =~ ^[0-9]+$ ]]; then
  echo "[start] runs must be a non-negative integer: ${MAX_RUNS}" >&2
  exit 1
fi

if [[ "${MAX_RUNS}" -eq 0 ]]; then
  mode_message="continuous until queue is empty"
else
  mode_message="${MAX_RUNS} runs per agent"
fi

echo "[start] run mode: ${mode_message}"

"${SCRIPT_DIR}/setup-worktrees.sh" "${COUNT}"

for i in $(seq 1 "${COUNT}"); do
  session="${SESSION_PREFIX}-${i}"
  worktree="${ROOT}/worktrees/agent-${i}"

  if tmux has-session -t "${session}" 2>/dev/null; then
    echo "[start] session ${session} already running"
    continue
  fi

  echo "[start] launching ${session} in ${worktree}"
  tmux_cmd="$(printf "cd %q && AGENT_NAME=%q WORKTREE=%q AGENT_MODEL=%q AGENT_COMMAND=%q PROMPT_TEMPLATE=%q MAX_RUNS=%q %q" \
    "${ROOT}" \
    "agent-${i}" \
    "${worktree}" \
    "${AGENT_MODEL}" \
    "${AGENT_COMMAND}" \
    "${PROMPT_TEMPLATE}" \
    "${MAX_RUNS}" \
    "${SCRIPT_DIR}/agent-loop.sh")"
  tmux new-session -d -s "${session}" "${tmux_cmd}"
done

echo "[start] running sessions:"
tmux ls | grep "^${SESSION_PREFIX}-" || true
