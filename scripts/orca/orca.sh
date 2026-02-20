#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
USAGE_PREFIX="${ORCA_USAGE_PREFIX:-${SCRIPT_DIR}/orca.sh}"

usage() {
  cat <<USAGE
Usage:
  ${USAGE_PREFIX} <command> [args]

Commands:
  start [count] [--runs N|--continuous] [--reasoning-level LEVEL]
  stop
  status
  setup-worktrees [count]
  with-lock [--scope NAME] [--timeout SECONDS] -- <command> [args...]
  merge-primary-main [--repo PATH] [--source-branch NAME] [--target-branch NAME] [--remote NAME]
USAGE
}

subcommand="${1:-}"
if [[ $# -gt 0 ]]; then
  shift
fi

case "${subcommand}" in
  start)
    exec "${SCRIPT_DIR}/start.sh" "$@"
    ;;
  stop)
    exec "${SCRIPT_DIR}/stop.sh" "$@"
    ;;
  status)
    exec "${SCRIPT_DIR}/status.sh" "$@"
    ;;
  setup-worktrees|setup)
    exec "${SCRIPT_DIR}/setup-worktrees.sh" "$@"
    ;;
  with-lock|lock)
    exec "${SCRIPT_DIR}/with-lock.sh" "$@"
    ;;
  merge-primary-main)
    exec "${SCRIPT_DIR}/merge-primary-main.sh" "$@"
    ;;
  help|-h|--help|"")
    usage
    ;;
  *)
    echo "Unknown orca command: ${subcommand}" >&2
    usage >&2
    exit 1
    ;;
esac
