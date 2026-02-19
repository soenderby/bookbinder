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
AGENT_MODEL="${AGENT_MODEL:-gpt-5}"
AGENT_COMMAND="${AGENT_COMMAND:-codex exec --dangerously-bypass-approvals-and-sandbox --model ${AGENT_MODEL}}"
PROMPT_TEMPLATE="${PROMPT_TEMPLATE:-${ROOT}/scripts/orca/AGENT_PROMPT.md}"
MAX_RUNS="${MAX_RUNS:-0}"
READY_MAX_ATTEMPTS="${READY_MAX_ATTEMPTS:-5}"
READY_RETRY_SECONDS="${READY_RETRY_SECONDS:-3}"

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

runs_completed=0
current_issue_id=""
cleanup_in_progress=0

mkdir -p "${ROOT}/agent-logs"
LOGFILE="${ROOT}/agent-logs/${AGENT_NAME}-${AGENT_SESSION_ID}.log"

log() {
  printf '[%s] [%s] %s\n' "$(date -Iseconds)" "${AGENT_NAME}" "$*" | tee -a "${LOGFILE}"
}

release_claim_if_needed() {
  local reason="$1"
  if [[ -z "${current_issue_id}" ]]; then
    return
  fi

  local failure_note
  failure_note="Agent loop interruption in ${AGENT_NAME} at $(date -Iseconds). Reason: ${reason}. Returning issue to open for retry."
  if bd update "${current_issue_id}" --status open --assignee "" --append-notes "${failure_note}" >/dev/null 2>&1; then
    log "returned ${current_issue_id} to open (${reason})"
  else
    log "failed to return ${current_issue_id} to open (${reason}); manual intervention needed"
  fi

  current_issue_id=""
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

trap cleanup_on_exit EXIT
trap 'cleanup_on_signal INT; exit 130' INT
trap 'cleanup_on_signal TERM; exit 143' TERM

cd "${WORKTREE}"
log "starting loop in ${WORKTREE}"
log "session id: ${AGENT_SESSION_ID}"
if [[ "${MAX_RUNS}" -eq 0 ]]; then
  log "run mode: continuous until queue is empty"
else
  log "run mode: stop after ${MAX_RUNS} runs"
fi

while true; do
  if [[ "${MAX_RUNS}" -gt 0 && "${runs_completed}" -ge "${MAX_RUNS}" ]]; then
    log "max runs reached (${runs_completed}/${MAX_RUNS}); exiting loop"
    break
  fi

  git pull --rebase --autostash >/dev/null 2>&1 || true
  bd sync >/dev/null 2>&1 || true

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

  prompt_text="$(cat "${PROMPT_TEMPLATE}")"
  prompt_text="${prompt_text//__AGENT_NAME__/${AGENT_NAME}}"
  prompt_text="${prompt_text//__ISSUE_ID__/${issue_id}}"
  prompt_text="${prompt_text//__WORKTREE__/${WORKTREE}}"

  tmp_prompt="$(mktemp)"
  printf '%s\n' "${prompt_text}" > "${tmp_prompt}"

  log "running agent command for ${issue_id}"
  if bash -lc "${AGENT_COMMAND}" < "${tmp_prompt}" >>"${LOGFILE}" 2>&1; then
    log "agent command finished for ${issue_id}"
    current_issue_id=""
  else
    log "agent command failed for ${issue_id}; returning issue to open"
    failure_note="Agent loop failure in ${AGENT_NAME} at $(date -Iseconds). Command: ${AGENT_COMMAND}. Returning issue to open for retry."
    if bd update "${issue_id}" --status open --assignee "" --append-notes "${failure_note}" >/dev/null 2>&1; then
      log "returned ${issue_id} to open"
    else
      log "failed to return ${issue_id} to open; manual intervention needed"
    fi
    current_issue_id=""
  fi

  rm -f "${tmp_prompt}"

  git pull --rebase --autostash >/dev/null 2>&1 || true
  bd sync >/dev/null 2>&1 || true

  runs_completed=$((runs_completed + 1))
  if [[ "${MAX_RUNS}" -eq 0 ]]; then
    log "completed run ${runs_completed}"
  else
    log "completed run ${runs_completed}/${MAX_RUNS}"
  fi

  sleep 2
done

log "loop stopped"
