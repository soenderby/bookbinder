#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  start.sh [count] [--runs N | --continuous] [--reasoning-level LEVEL]

Options:
  count         Number of worker sessions/worktrees to launch (default: 2)
  --runs N      Stop each agent loop after N completed issue runs
  --continuous  Keep each loop unbounded while ready work exists (default)
  --reasoning-level LEVEL
                Set `model_reasoning_effort` for default codex agent command
USAGE
}

COUNT=""
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SESSION_PREFIX="${SESSION_PREFIX:-bb-agent}"
AGENT_MODEL="${AGENT_MODEL:-gpt-5.3-codex}"
AGENT_REASONING_LEVEL="${AGENT_REASONING_LEVEL:-}"
AGENT_COMMAND_WAS_SET=0
if [[ -n "${AGENT_COMMAND+x}" ]]; then
  AGENT_COMMAND_WAS_SET=1
fi
AGENT_COMMAND="${AGENT_COMMAND:-codex exec --dangerously-bypass-approvals-and-sandbox --model ${AGENT_MODEL}}"
MAX_RUNS="${MAX_RUNS:-0}"

check_prerequisites() {
  local missing=()
  local cmd
  local agent_command_bin

  for cmd in git tmux bd jq; do
    if ! command -v "${cmd}" >/dev/null 2>&1; then
      missing+=("${cmd}")
    fi
  done

  agent_command_bin="${AGENT_COMMAND%% *}"
  if [[ -n "${agent_command_bin}" ]] && ! command -v "${agent_command_bin}" >/dev/null 2>&1; then
    missing+=("${agent_command_bin} (from AGENT_COMMAND)")
  fi

  if [[ "${#missing[@]}" -gt 0 ]]; then
    echo "[start] missing prerequisites: ${missing[*]}" >&2
    exit 1
  fi
}

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
    --reasoning-level)
      if [[ $# -lt 2 ]]; then
        echo "[start] --reasoning-level requires an argument" >&2
        exit 1
      fi
      AGENT_REASONING_LEVEL="$2"
      shift 2
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

check_prerequisites

ROOT="$(git rev-parse --show-toplevel)"
PROMPT_TEMPLATE="${PROMPT_TEMPLATE:-${ROOT}/scripts/orca/AGENT_PROMPT.md}"

if ! [[ "${COUNT}" =~ ^[1-9][0-9]*$ ]]; then
  echo "[start] count must be a positive integer: ${COUNT}" >&2
  exit 1
fi

if ! [[ "${MAX_RUNS}" =~ ^[0-9]+$ ]]; then
  echo "[start] runs must be a non-negative integer: ${MAX_RUNS}" >&2
  exit 1
fi

if [[ -n "${AGENT_REASONING_LEVEL}" && ! "${AGENT_REASONING_LEVEL}" =~ ^[A-Za-z0-9._-]+$ ]]; then
  echo "[start] reasoning level must contain only letters, digits, dot, underscore, or dash: ${AGENT_REASONING_LEVEL}" >&2
  exit 1
fi

if [[ -n "${AGENT_REASONING_LEVEL}" ]]; then
  if [[ "${AGENT_COMMAND_WAS_SET}" -eq 1 ]]; then
    echo "[start] AGENT_COMMAND override detected; --reasoning-level will not modify AGENT_COMMAND" >&2
  else
    AGENT_COMMAND="${AGENT_COMMAND} -c model_reasoning_effort=${AGENT_REASONING_LEVEL}"
  fi
fi

if [[ ! -f "${PROMPT_TEMPLATE}" ]]; then
  echo "[start] missing prompt template: ${PROMPT_TEMPLATE}" >&2
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
  session_id="${session}-$(date -u +%Y%m%dT%H%M%SZ)"
  worktree="${ROOT}/worktrees/agent-${i}"

  if tmux has-session -t "${session}" 2>/dev/null; then
    echo "[start] session ${session} already running"
    continue
  fi

  echo "[start] launching ${session} in ${worktree}"
  tmux_cmd="$(printf "cd %q && AGENT_NAME=%q AGENT_SESSION_ID=%q WORKTREE=%q AGENT_MODEL=%q AGENT_REASONING_LEVEL=%q AGENT_COMMAND=%q PROMPT_TEMPLATE=%q MAX_RUNS=%q %q" \
    "${ROOT}" \
    "agent-${i}" \
    "${session_id}" \
    "${worktree}" \
    "${AGENT_MODEL}" \
    "${AGENT_REASONING_LEVEL}" \
    "${AGENT_COMMAND}" \
    "${PROMPT_TEMPLATE}" \
    "${MAX_RUNS}" \
    "${SCRIPT_DIR}/agent-loop.sh")"
  tmux new-session -d -s "${session}" "${tmux_cmd}"
done

echo "[start] running sessions:"
tmux ls | grep "^${SESSION_PREFIX}-" || true
