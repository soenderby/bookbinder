#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ORCA_DIR="${ROOT_DIR}/scripts/swarm"

usage() {
  cat <<'USAGE'
Usage:
  ./bb orca <command> [args]

Orca commands:
  start [count]          Start tmux-backed agent loops (default count: 2)
  stop                   Stop running agent loop sessions
  status                 Show swarm/session/worktree status
  setup-worktrees [count]
                         Create persistent worktrees (default count: 2)

Examples:
  ./bb orca setup-worktrees 2
  ./bb orca start 2
  ./bb orca status
  ./bb orca stop
USAGE
}

orca_usage() {
  cat <<'USAGE'
Usage:
  ./bb orca <command> [args]

Commands:
  start [count]
  stop
  status
  setup-worktrees [count]
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
    subcommand="${1:-}"
    if [[ $# -gt 0 ]]; then
      shift
    fi

    case "${subcommand}" in
      start)
        exec "${ORCA_DIR}/start.sh" "$@"
        ;;
      stop)
        exec "${ORCA_DIR}/stop.sh" "$@"
        ;;
      status)
        exec "${ORCA_DIR}/status.sh" "$@"
        ;;
      setup-worktrees|setup)
        exec "${ORCA_DIR}/setup-worktrees.sh" "$@"
        ;;
      help|-h|--help|"")
        orca_usage
        ;;
      *)
        echo "Unknown orca command: ${subcommand}" >&2
        orca_usage >&2
        exit 1
        ;;
    esac
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
