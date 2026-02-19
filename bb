#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ORCA_DIR="${ROOT_DIR}/scripts/swarm"

usage() {
  cat <<'USAGE'
Usage:
  ./bb orca <command> [args]

Orca commands:
  start [count] [--runs N|--continuous]
                         Start tmux-backed agent loops (default count: 2,
                         default mode: --continuous, and loops stop when
                         no ready tasks remain)
  stop                   Stop running agent loop sessions
  status                 Show swarm/session/worktree status
  setup-worktrees [count]
                         Create persistent worktrees (default count: 2)

Examples:
  ./bb orca setup-worktrees 2
  ./bb orca start 2
  ./bb orca start 2 --runs 5
  ./bb orca start --continuous
  ./bb orca status
  ./bb orca stop
USAGE
}

if [[ $# -lt 1 ]]; then
  usage
  exit 1
fi

command="$1"
shift

case "${command}" in
  orca)
    exec env ORCA_USAGE_PREFIX="./bb orca" "${ORCA_DIR}/orca.sh" "$@"
    ;;
  help|-h|--help)
    usage
    ;;
  *)
    echo "Unknown command: ${command}" >&2
    usage >&2
    exit 1
    ;;
esac
