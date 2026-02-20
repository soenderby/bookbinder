#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  merge-primary-main.sh [--repo PATH] [--source-branch NAME] [--target-branch NAME] [--remote NAME]

Environment defaults:
  ORCA_PRIMARY_REPO        Primary checkout path used for mainline integration.
  ORCA_SOURCE_BRANCH       Source branch to merge into target branch.
  ORCA_TARGET_BRANCH       Target branch to receive merge (default: main).
  ORCA_REMOTE              Remote name (default: origin).
USAGE
}

repo="${ORCA_PRIMARY_REPO:-}"
source_branch="${ORCA_SOURCE_BRANCH:-}"
target_branch="${ORCA_TARGET_BRANCH:-main}"
remote_name="${ORCA_REMOTE:-origin}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo)
      if [[ $# -lt 2 ]]; then
        echo "[merge-primary-main] --repo requires a path" >&2
        exit 1
      fi
      repo="$2"
      shift 2
      ;;
    --source-branch)
      if [[ $# -lt 2 ]]; then
        echo "[merge-primary-main] --source-branch requires a value" >&2
        exit 1
      fi
      source_branch="$2"
      shift 2
      ;;
    --target-branch)
      if [[ $# -lt 2 ]]; then
        echo "[merge-primary-main] --target-branch requires a value" >&2
        exit 1
      fi
      target_branch="$2"
      shift 2
      ;;
    --remote)
      if [[ $# -lt 2 ]]; then
        echo "[merge-primary-main] --remote requires a value" >&2
        exit 1
      fi
      remote_name="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "[merge-primary-main] unknown argument: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

if [[ -z "${repo}" ]]; then
  repo="$(git rev-parse --show-toplevel)"
fi
repo="$(cd "${repo}" && pwd)"

if [[ -z "${source_branch}" ]]; then
  source_branch="$(git branch --show-current)"
fi

if [[ -z "${source_branch}" ]]; then
  echo "[merge-primary-main] source branch could not be resolved" >&2
  exit 1
fi

if [[ "${source_branch}" == "${target_branch}" ]]; then
  echo "[merge-primary-main] source and target branches are both '${source_branch}'" >&2
  exit 1
fi

if ! git -C "${repo}" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "[merge-primary-main] repo is not a git worktree: ${repo}" >&2
  exit 1
fi

if [[ -n "$(git -C "${repo}" status --porcelain --untracked-files=normal)" ]]; then
  echo "[merge-primary-main] primary repo has local changes; aborting deterministic merge preflight" >&2
  echo "[merge-primary-main] repo: ${repo}" >&2
  echo "[merge-primary-main] clean the repo (commit/stash/discard), then retry under lock" >&2
  exit 1
fi

git -C "${repo}" fetch "${remote_name}" "${target_branch}" "${source_branch}"
git -C "${repo}" checkout "${target_branch}"
git -C "${repo}" pull --ff-only "${remote_name}" "${target_branch}"
git -C "${repo}" merge --no-ff "${source_branch}"
git -C "${repo}" push "${remote_name}" "${target_branch}"
