#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  merge-after-run.sh --source-branch <branch> [options]

Options:
  --source-branch <branch>   Required source branch to merge (for example: swarm/agent-1)
  --required-commit <sha>    Optional commit that must be present on remote source branch
  --remote <name>            Git remote name (default: origin)
  --target-branch <branch>   Integration target branch (default: main)
  --lock-timeout <seconds>   Wait time for global merge lock (default: 120)
  --max-attempts <count>     Retries for transient fetch/push failures (default: 3)
USAGE
}

SOURCE_BRANCH=""
REQUIRED_COMMIT=""
REMOTE="${ORCA_MERGE_REMOTE:-origin}"
TARGET_BRANCH="${ORCA_MERGE_TARGET_BRANCH:-main}"
LOCK_TIMEOUT_SECONDS="${ORCA_MERGE_LOCK_TIMEOUT_SECONDS:-120}"
MAX_ATTEMPTS="${ORCA_MERGE_MAX_ATTEMPTS:-3}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --source-branch)
      if [[ $# -lt 2 ]]; then
        echo "[merge] --source-branch requires an argument" >&2
        exit 1
      fi
      SOURCE_BRANCH="$2"
      shift 2
      ;;
    --required-commit)
      if [[ $# -lt 2 ]]; then
        echo "[merge] --required-commit requires an argument" >&2
        exit 1
      fi
      REQUIRED_COMMIT="$2"
      shift 2
      ;;
    --remote)
      if [[ $# -lt 2 ]]; then
        echo "[merge] --remote requires an argument" >&2
        exit 1
      fi
      REMOTE="$2"
      shift 2
      ;;
    --target-branch)
      if [[ $# -lt 2 ]]; then
        echo "[merge] --target-branch requires an argument" >&2
        exit 1
      fi
      TARGET_BRANCH="$2"
      shift 2
      ;;
    --lock-timeout)
      if [[ $# -lt 2 ]]; then
        echo "[merge] --lock-timeout requires an argument" >&2
        exit 1
      fi
      LOCK_TIMEOUT_SECONDS="$2"
      shift 2
      ;;
    --max-attempts)
      if [[ $# -lt 2 ]]; then
        echo "[merge] --max-attempts requires an argument" >&2
        exit 1
      fi
      MAX_ATTEMPTS="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "[merge] unknown argument: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

if [[ -z "${SOURCE_BRANCH}" ]]; then
  echo "[merge] --source-branch is required" >&2
  usage >&2
  exit 1
fi

if ! [[ "${LOCK_TIMEOUT_SECONDS}" =~ ^[1-9][0-9]*$ ]]; then
  echo "[merge] lock timeout must be a positive integer: ${LOCK_TIMEOUT_SECONDS}" >&2
  exit 1
fi

if ! [[ "${MAX_ATTEMPTS}" =~ ^[1-9][0-9]*$ ]]; then
  echo "[merge] max attempts must be a positive integer: ${MAX_ATTEMPTS}" >&2
  exit 1
fi

if [[ -n "${REQUIRED_COMMIT}" ]] && ! git rev-parse --verify --quiet "${REQUIRED_COMMIT}^{commit}" >/dev/null; then
  echo "[merge] required commit is not a valid commit object: ${REQUIRED_COMMIT}" >&2
  exit 1
fi

COMMON_GIT_DIR="$(git rev-parse --git-common-dir)"
COMMON_GIT_DIR="$(cd "${COMMON_GIT_DIR}" && pwd)"
ROOT="$(cd "${COMMON_GIT_DIR}/.." && pwd)"
LOCK_FILE="${COMMON_GIT_DIR}/orca-merge.lock"
WORKTREE_ROOT="${ROOT}/worktrees"
TMP_WORKTREE=""

log() {
  printf '[merge] %s\n' "$*"
}

cleanup_tmp_worktree() {
  if [[ -z "${TMP_WORKTREE}" ]]; then
    return
  fi

  git worktree remove --force "${TMP_WORKTREE}" >/dev/null 2>&1 || true
  rm -rf "${TMP_WORKTREE}" >/dev/null 2>&1 || true
  TMP_WORKTREE=""
}

cleanup() {
  cleanup_tmp_worktree
}

trap cleanup EXIT

mkdir -p "${WORKTREE_ROOT}"

exec 9>"${LOCK_FILE}"
if ! flock -w "${LOCK_TIMEOUT_SECONDS}" 9; then
  log "timed out waiting for merge lock after ${LOCK_TIMEOUT_SECONDS}s"
  exit 1
fi

source_ref="${REMOTE}/${SOURCE_BRANCH}"
target_ref="${REMOTE}/${TARGET_BRANCH}"

attempt=1
while [[ "${attempt}" -le "${MAX_ATTEMPTS}" ]]; do
  log "attempt ${attempt}/${MAX_ATTEMPTS}: syncing ${source_ref} -> ${target_ref}"

  if ! git fetch "${REMOTE}" "${TARGET_BRANCH}" "${SOURCE_BRANCH}" >/dev/null 2>&1; then
    log "git fetch failed for ${REMOTE}; retrying"
    attempt=$((attempt + 1))
    sleep 2
    continue
  fi

  if ! git rev-parse --verify --quiet "${source_ref}" >/dev/null; then
    log "source ref does not exist on remote: ${source_ref}"
    exit 1
  fi

  if ! git rev-parse --verify --quiet "${target_ref}" >/dev/null; then
    log "target ref does not exist on remote: ${target_ref}"
    exit 1
  fi

  if [[ -n "${REQUIRED_COMMIT}" ]] && ! git merge-base --is-ancestor "${REQUIRED_COMMIT}" "${source_ref}" >/dev/null 2>&1; then
    log "required commit is not present on ${source_ref}: ${REQUIRED_COMMIT}"
    exit 1
  fi

  safe_source="$(printf '%s' "${SOURCE_BRANCH}" | tr '/:@' '___')"
  TMP_WORKTREE="${WORKTREE_ROOT}/.orca-merge-${safe_source}-$(date -u +%Y%m%dT%H%M%SZ)-$$-${attempt}"

  if ! git worktree add --detach "${TMP_WORKTREE}" "${target_ref}" >/dev/null 2>&1; then
    log "failed to create temporary merge worktree"
    cleanup_tmp_worktree
    attempt=$((attempt + 1))
    sleep 2
    continue
  fi

  if ! git -C "${TMP_WORKTREE}" merge --no-ff --no-edit "${source_ref}" >/dev/null 2>&1; then
    log "merge conflict or merge failure while integrating ${source_ref} into ${target_ref}"
    git -C "${TMP_WORKTREE}" merge --abort >/dev/null 2>&1 || true
    cleanup_tmp_worktree
    exit 1
  fi

  if git -C "${TMP_WORKTREE}" push "${REMOTE}" "HEAD:${TARGET_BRANCH}" >/dev/null 2>&1; then
    log "merged ${source_ref} into ${target_ref}"
    cleanup_tmp_worktree
    exit 0
  fi

  log "push failed while updating ${target_ref}; retrying"
  cleanup_tmp_worktree
  attempt=$((attempt + 1))
  sleep 2
done

log "failed to merge ${source_ref} into ${target_ref} after ${MAX_ATTEMPTS} attempts"
exit 1
