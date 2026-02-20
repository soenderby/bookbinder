#!/usr/bin/env bash
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
WORKTREE="${WORKTREE:-}"

if [[ -z "${WORKTREE}" ]]; then
  echo "WORKTREE is required"
  exit 1
fi

if ! git -C "${WORKTREE}" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "WORKTREE does not look like a git worktree: ${WORKTREE}"
  exit 1
fi

AGENT_NAME="${AGENT_NAME:-$(basename "${WORKTREE}")}"
AGENT_SESSION_ID="${AGENT_SESSION_ID:-${AGENT_NAME}-$(date -u +%Y%m%dT%H%M%SZ)}"
AGENT_MODEL="${AGENT_MODEL:-gpt-5.3-codex}"
AGENT_REASONING_LEVEL="${AGENT_REASONING_LEVEL:-}"
if [[ -n "${AGENT_COMMAND:-}" ]]; then
  AGENT_COMMAND="${AGENT_COMMAND}"
else
  AGENT_COMMAND="codex exec --dangerously-bypass-approvals-and-sandbox --model ${AGENT_MODEL}"
  if [[ -n "${AGENT_REASONING_LEVEL}" ]]; then
    AGENT_COMMAND="${AGENT_COMMAND} -c model_reasoning_effort=${AGENT_REASONING_LEVEL}"
  fi
fi
PROMPT_TEMPLATE="${PROMPT_TEMPLATE:-${ROOT}/scripts/orca/AGENT_PROMPT.md}"
MERGE_SCRIPT="${MERGE_SCRIPT:-${ROOT}/scripts/orca/merge-after-run.sh}"
MAX_RUNS="${MAX_RUNS:-0}"
READY_MAX_ATTEMPTS="${READY_MAX_ATTEMPTS:-5}"
READY_RETRY_SECONDS="${READY_RETRY_SECONDS:-3}"
ORCA_MERGE_REMOTE="${ORCA_MERGE_REMOTE:-origin}"
ORCA_MERGE_TARGET_BRANCH="${ORCA_MERGE_TARGET_BRANCH:-main}"
ORCA_MERGE_LOCK_TIMEOUT_SECONDS="${ORCA_MERGE_LOCK_TIMEOUT_SECONDS:-120}"
ORCA_MERGE_MAX_ATTEMPTS="${ORCA_MERGE_MAX_ATTEMPTS:-3}"

if ! [[ "${MAX_RUNS}" =~ ^[0-9]+$ ]]; then
  echo "MAX_RUNS must be a non-negative integer (0 means unbounded mode): ${MAX_RUNS}"
  exit 1
fi

if ! [[ "${READY_MAX_ATTEMPTS}" =~ ^[1-9][0-9]*$ ]]; then
  echo "READY_MAX_ATTEMPTS must be a positive integer: ${READY_MAX_ATTEMPTS}"
  exit 1
fi

if ! [[ "${READY_RETRY_SECONDS}" =~ ^[1-9][0-9]*$ ]]; then
  echo "READY_RETRY_SECONDS must be a positive integer: ${READY_RETRY_SECONDS}"
  exit 1
fi

if ! [[ "${ORCA_MERGE_LOCK_TIMEOUT_SECONDS}" =~ ^[1-9][0-9]*$ ]]; then
  echo "ORCA_MERGE_LOCK_TIMEOUT_SECONDS must be a positive integer: ${ORCA_MERGE_LOCK_TIMEOUT_SECONDS}"
  exit 1
fi

if ! [[ "${ORCA_MERGE_MAX_ATTEMPTS}" =~ ^[1-9][0-9]*$ ]]; then
  echo "ORCA_MERGE_MAX_ATTEMPTS must be a positive integer: ${ORCA_MERGE_MAX_ATTEMPTS}"
  exit 1
fi

if [[ -n "${AGENT_REASONING_LEVEL}" && ! "${AGENT_REASONING_LEVEL}" =~ ^[A-Za-z0-9._-]+$ ]]; then
  echo "AGENT_REASONING_LEVEL must contain only letters, digits, dot, underscore, or dash: ${AGENT_REASONING_LEVEL}"
  exit 1
fi

if [[ ! -x "${MERGE_SCRIPT}" ]]; then
  echo "MERGE_SCRIPT must be executable: ${MERGE_SCRIPT}"
  exit 1
fi

runs_completed=0
current_issue_id=""
current_issue_should_reopen=1
cleanup_in_progress=0
EXPECTED_BRANCH=""

mkdir -p "${ROOT}/agent-logs"
LOGFILE=""

log() {
  local line
  line="$(printf '[%s] [%s] %s\n' "$(date -Iseconds)" "${AGENT_NAME}" "$*")"
  if [[ -n "${LOGFILE}" ]]; then
    printf '%s\n' "${line}" | tee -a "${LOGFILE}"
  else
    printf '%s\n' "${line}" >&2
  fi
}

sanitize_for_filename() {
  printf '%s' "$1" | tr -c 'A-Za-z0-9._-' '_'
}

start_run_logfile() {
  local issue_id="$1"
  local run_number run_timestamp safe_issue_id

  run_number=$((runs_completed + 1))
  run_timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
  safe_issue_id="$(sanitize_for_filename "${issue_id}")"
  LOGFILE="${ROOT}/agent-logs/${AGENT_NAME}-${AGENT_SESSION_ID}-run-${run_number}-${safe_issue_id}-${run_timestamp}.log"
  : > "${LOGFILE}"

  log "starting run ${run_number} for ${issue_id}"
  log "session id: ${AGENT_SESSION_ID}"
  log "worktree: ${WORKTREE}"
  log "merge target: ${ORCA_MERGE_REMOTE}/${ORCA_MERGE_TARGET_BRANCH}"
}

release_claim_if_needed() {
  local reason="$1"
  if [[ -z "${current_issue_id}" ]]; then
    return
  fi

  if [[ "${current_issue_should_reopen}" -eq 0 ]]; then
    log "leaving ${current_issue_id} as-is during ${reason} (already merged)"
    current_issue_id=""
    current_issue_should_reopen=1
    return
  fi

  local failure_note
  failure_note="Agent loop interruption in ${AGENT_NAME} at $(date -Iseconds). Reason: ${reason}. Returning issue to open for retry."
  if update_issue_to_open_with_retry "${current_issue_id}" "${failure_note}" "${reason}"; then
    log "returned ${current_issue_id} to open (${reason})"
  else
    log "failed to return ${current_issue_id} to open (${reason}); manual intervention needed"
  fi

  current_issue_id=""
  current_issue_should_reopen=1
}

cleanup_on_signal() {
  local signal="$1"
  if [[ "${cleanup_in_progress}" -eq 1 ]]; then
    return
  fi

  cleanup_in_progress=1
  release_claim_if_needed "signal:${signal}"
}

cleanup_on_exit() {
  cleanup_on_signal "exit"
}

next_ready_issue_with_retry() {
  local attempts=1
  local ready_json
  local issue_id

  while [[ "${attempts}" -le "${READY_MAX_ATTEMPTS}" ]]; do
    if ready_json="$(bd ready --json 2>/dev/null)" && issue_id="$(jq -r '.[0].id // empty' <<<"${ready_json}" 2>/dev/null)"; then
      printf '%s\n' "${issue_id}"
      return 0
    fi

    log "failed to poll ready beads (attempt ${attempts}/${READY_MAX_ATTEMPTS}); retrying in ${READY_RETRY_SECONDS}s"
    sleep "${READY_RETRY_SECONDS}"
    attempts=$((attempts + 1))
  done

  return 1
}

log_git_status_lines() {
  while IFS= read -r status_line; do
    log "git status: ${status_line}"
  done < <(git status --short)
}

abort_rebase_if_needed() {
  if [[ -d ".git/rebase-apply" || -d ".git/rebase-merge" ]]; then
    if git rebase --abort >/dev/null 2>&1; then
      log "aborted in-progress rebase after git pull failure"
    else
      log "failed to abort in-progress rebase after git pull failure"
    fi
  fi
}

require_clean_worktree_or_exit() {
  local context="$1"
  if [[ -n "$(git status --porcelain)" ]]; then
    log "worktree is dirty during ${context}; refusing to continue"
    log_git_status_lines
    exit 1
  fi
}

require_expected_branch_or_exit() {
  local context="$1"
  local current_branch

  current_branch="$(git branch --show-current)"
  if [[ "${current_branch}" == "${EXPECTED_BRANCH}" ]]; then
    return
  fi

  log "branch drift during ${context}; expected ${EXPECTED_BRANCH}, found ${current_branch:-detached}"
  if git checkout "${EXPECTED_BRANCH}" >/dev/null 2>&1; then
    log "checked out expected branch ${EXPECTED_BRANCH}"
    return
  fi

  log "failed to checkout expected branch ${EXPECTED_BRANCH}; stopping loop"
  exit 1
}

guard_worktree_state_or_exit() {
  local context="$1"
  require_expected_branch_or_exit "${context}"
  require_clean_worktree_or_exit "${context}"
}

update_issue_to_open_with_retry() {
  local issue_id="$1"
  local note="$2"
  local reason="$3"
  local attempts=1
  local max_attempts=3

  while [[ "${attempts}" -le "${max_attempts}" ]]; do
    if bd update "${issue_id}" --status open --assignee "" --append-notes "${note}" >/dev/null 2>&1; then
      return 0
    fi

    log "failed to return ${issue_id} to open (${reason}); attempt ${attempts}/${max_attempts}"
    attempts=$((attempts + 1))
    sleep 2
  done

  return 1
}

issue_status_with_retry() {
  local issue_id="$1"
  local attempts=1
  local max_attempts=3
  local issue_json
  local status

  while [[ "${attempts}" -le "${max_attempts}" ]]; do
    if issue_json="$(bd show "${issue_id}" --json 2>/dev/null)" && status="$(jq -r '.[0].status // empty' <<<"${issue_json}" 2>/dev/null)" && [[ -n "${status}" ]]; then
      printf '%s\n' "${status}"
      return 0
    fi

    log "failed to read status for ${issue_id}; attempt ${attempts}/${max_attempts}"
    attempts=$((attempts + 1))
    sleep 2
  done

  return 1
}

close_issue_if_needed_with_retry() {
  local issue_id="$1"
  local status
  local attempts=1
  local max_attempts=3

  if ! status="$(issue_status_with_retry "${issue_id}")"; then
    log "unable to determine status for ${issue_id}; cannot close automatically"
    return 1
  fi

  if [[ "${status}" == "closed" ]]; then
    log "issue ${issue_id} already closed"
    return 0
  fi

  while [[ "${attempts}" -le "${max_attempts}" ]]; do
    if bd close "${issue_id}" --reason "completed" >/dev/null 2>&1; then
      return 0
    fi

    log "failed to close ${issue_id}; attempt ${attempts}/${max_attempts}"
    attempts=$((attempts + 1))
    sleep 2
  done

  return 1
}

append_issue_note_with_retry() {
  local issue_id="$1"
  local note="$2"
  local reason="$3"
  local attempts=1
  local max_attempts=3

  while [[ "${attempts}" -le "${max_attempts}" ]]; do
    if bd update "${issue_id}" --append-notes "${note}" >/dev/null 2>&1; then
      return 0
    fi

    log "failed to append notes to ${issue_id} (${reason}); attempt ${attempts}/${max_attempts}"
    attempts=$((attempts + 1))
    sleep 2
  done

  return 1
}

merge_issue_or_return_to_open() {
  local issue_id="$1"
  local source_commit
  local merge_failure_note
  local close_failure_note

  source_commit="$(git rev-parse HEAD)"
  log "starting merge for ${issue_id}: ${EXPECTED_BRANCH}@${source_commit} -> ${ORCA_MERGE_REMOTE}/${ORCA_MERGE_TARGET_BRANCH}"
  if ! "${MERGE_SCRIPT}" \
    --source-branch "${EXPECTED_BRANCH}" \
    --required-commit "${source_commit}" \
    --remote "${ORCA_MERGE_REMOTE}" \
    --target-branch "${ORCA_MERGE_TARGET_BRANCH}" \
    --lock-timeout "${ORCA_MERGE_LOCK_TIMEOUT_SECONDS}" \
    --max-attempts "${ORCA_MERGE_MAX_ATTEMPTS}" >>"${LOGFILE}" 2>&1; then
    merge_failure_note="Merge failed in ${AGENT_NAME} at $(date -Iseconds). Could not merge ${EXPECTED_BRANCH} into ${ORCA_MERGE_REMOTE}/${ORCA_MERGE_TARGET_BRANCH}. Returning issue to open for retry."
    if update_issue_to_open_with_retry "${issue_id}" "${merge_failure_note}" "merge-failure"; then
      log "merge failed; returned ${issue_id} to open"
    else
      log "merge failed and could not return ${issue_id} to open; manual intervention needed"
    fi
    current_issue_id=""
    current_issue_should_reopen=1
    return 1
  fi

  # Merge succeeded. Never auto-reopen this issue from signal/exit handlers now.
  current_issue_should_reopen=0
  log "merge succeeded for ${issue_id}"

  if close_issue_if_needed_with_retry "${issue_id}"; then
    log "issue ${issue_id} closed after successful merge"
    current_issue_id=""
    current_issue_should_reopen=1
    return 0
  fi

  close_failure_note="Work for ${issue_id} was merged into ${ORCA_MERGE_REMOTE}/${ORCA_MERGE_TARGET_BRANCH} at $(date -Iseconds), but automatic issue close failed. Manual close required."
  if append_issue_note_with_retry "${issue_id}" "${close_failure_note}" "close-after-merge-failure"; then
    log "merge completed for ${issue_id}, but issue close failed; note appended"
  else
    log "merge completed for ${issue_id}, but issue close failed and note append failed; manual intervention needed"
  fi
  current_issue_id=""
  current_issue_should_reopen=1
  return 1
}

sync_with_remote_or_exit() {
  local context="$1"

  guard_worktree_state_or_exit "${context}:pre-sync"

  if ! git pull --rebase --autostash >/dev/null 2>&1; then
    log "git pull --rebase --autostash failed during ${context}; stopping loop"
    abort_rebase_if_needed
    exit 1
  fi

  if ! bd sync >/dev/null 2>&1; then
    log "bd sync failed during ${context}; stopping loop"
    exit 1
  fi

  guard_worktree_state_or_exit "${context}:post-sync"
}

trap cleanup_on_exit EXIT
trap 'cleanup_on_signal INT; exit 130' INT
trap 'cleanup_on_signal TERM; exit 143' TERM

cd "${WORKTREE}"
EXPECTED_BRANCH="${EXPECTED_BRANCH:-$(git branch --show-current)}"
if [[ -z "${EXPECTED_BRANCH}" ]]; then
  echo "Unable to determine expected branch for ${WORKTREE}" >&2
  exit 1
fi

log "starting loop in ${WORKTREE}"
log "session id: ${AGENT_SESSION_ID}"
log "expected branch: ${EXPECTED_BRANCH}"
if [[ "${MAX_RUNS}" -eq 0 ]]; then
  log "run mode: continuous until queue is empty"
else
  log "run mode: stop after ${MAX_RUNS} runs"
fi

while true; do
  stop_after_iteration=0

  if [[ "${MAX_RUNS}" -gt 0 && "${runs_completed}" -ge "${MAX_RUNS}" ]]; then
    log "max runs reached (${runs_completed}/${MAX_RUNS}); exiting loop"
    break
  fi

  sync_with_remote_or_exit "iteration-start"

  if ! issue_id="$(next_ready_issue_with_retry)"; then
    log "ready queue polling failed after ${READY_MAX_ATTEMPTS} attempts; continuing loop after backoff"
    sleep "${READY_RETRY_SECONDS}"
    continue
  fi

  if [[ -z "${issue_id}" ]]; then
    log "no ready beads; exiting loop"
    break
  fi

  if ! bd update "${issue_id}" --claim >/dev/null 2>&1; then
    log "could not claim ${issue_id}; likely claimed by another agent"
    sleep 3
    continue
  fi

  log "claimed ${issue_id}"
  current_issue_id="${issue_id}"
  current_issue_should_reopen=1
  start_run_logfile "${issue_id}"

  prompt_text="$(cat "${PROMPT_TEMPLATE}")"
  prompt_text="${prompt_text//__AGENT_NAME__/${AGENT_NAME}}"
  prompt_text="${prompt_text//__ISSUE_ID__/${issue_id}}"
  prompt_text="${prompt_text//__WORKTREE__/${WORKTREE}}"

  tmp_prompt="$(mktemp)"
  printf '%s\n' "${prompt_text}" > "${tmp_prompt}"

  log "running agent command for ${issue_id}"
  if bash -lc "${AGENT_COMMAND}" < "${tmp_prompt}" >>"${LOGFILE}" 2>&1; then
    log "agent command finished for ${issue_id}"
    guard_worktree_state_or_exit "post-agent:${issue_id}"
    if ! merge_issue_or_return_to_open "${issue_id}"; then
      stop_after_iteration=1
    fi
  else
    log "agent command failed for ${issue_id}; returning issue to open"
    failure_note="Agent loop failure in ${AGENT_NAME} at $(date -Iseconds). Command: ${AGENT_COMMAND}. Returning issue to open for retry."
    if update_issue_to_open_with_retry "${issue_id}" "${failure_note}" "agent-command-failure"; then
      log "returned ${issue_id} to open"
    else
      log "failed to return ${issue_id} to open; manual intervention needed"
    fi
    current_issue_id=""
    current_issue_should_reopen=1
  fi

  rm -f "${tmp_prompt}"

  sync_with_remote_or_exit "iteration-end"

  runs_completed=$((runs_completed + 1))
  if [[ "${MAX_RUNS}" -eq 0 ]]; then
    log "completed run ${runs_completed}"
  else
    log "completed run ${runs_completed}/${MAX_RUNS}"
  fi

  if [[ "${stop_after_iteration}" -eq 1 ]]; then
    log "stopping loop after run ${runs_completed} due to merge/finalization failure"
    LOGFILE=""
    break
  fi

  LOGFILE=""
  sleep 2
done

log "loop stopped"
