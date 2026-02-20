#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ORCA_DIR="${ROOT_DIR}/scripts/orca"

usage() {
  cat <<'USAGE'
Usage:
  ./bb orca <command> [args]

Orca commands:
  start [count] [--runs N|--continuous] [--reasoning-level LEVEL]
                         Start tmux-backed agent loops (default count: 2,
                         default mode: --continuous; agents can request stop)
  stop                   Stop running agent loop sessions
  status                 Show swarm/session/worktree status
  setup-worktrees [count]
                         Create persistent worktrees (default count: 2)
  with-lock ... -- cmd   Run a command under Orca's shared lock primitive
  check-closed-deps-merged <issue-id> [target-ref]
                         Verify closed blocking dependencies are merged to integration ref

Examples:
  ./bb orca setup-worktrees 2
  ./bb orca start 2
  ./bb orca start 2 --runs 5
  ./bb orca start 2 --reasoning-level high
  ./bb orca start --continuous
  ./bb orca status
  ./bb orca check-closed-deps-merged bookbinder-8dd.7
  ./bb orca with-lock --scope merge --timeout 120 -- git push origin main
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
