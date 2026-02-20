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
SYNC_MAX_ATTEMPTS="${SYNC_MAX_ATTEMPTS:-3}"
SYNC_RETRY_SECONDS="${SYNC_RETRY_SECONDS:-5}"
ORCA_MINIMAL_LANDING="${ORCA_MINIMAL_LANDING:-1}"
ORCA_ENFORCE_MINIMAL_LANDING="${ORCA_ENFORCE_MINIMAL_LANDING:-0}"
ORCA_TIMING_METRICS="${ORCA_TIMING_METRICS:-1}"
ORCA_COMPACT_SUMMARY="${ORCA_COMPACT_SUMMARY:-1}"
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

if ! [[ "${SYNC_MAX_ATTEMPTS}" =~ ^[1-9][0-9]*$ ]]; then
  echo "SYNC_MAX_ATTEMPTS must be a positive integer: ${SYNC_MAX_ATTEMPTS}"
  exit 1
fi

if ! [[ "${SYNC_RETRY_SECONDS}" =~ ^[1-9][0-9]*$ ]]; then
  echo "SYNC_RETRY_SECONDS must be a positive integer: ${SYNC_RETRY_SECONDS}"
  exit 1
fi

if ! [[ "${ORCA_MINIMAL_LANDING}" =~ ^[01]$ ]]; then
  echo "ORCA_MINIMAL_LANDING must be 0 or 1: ${ORCA_MINIMAL_LANDING}"
  exit 1
fi

if ! [[ "${ORCA_ENFORCE_MINIMAL_LANDING}" =~ ^[01]$ ]]; then
  echo "ORCA_ENFORCE_MINIMAL_LANDING must be 0 or 1: ${ORCA_ENFORCE_MINIMAL_LANDING}"
  exit 1
fi

if ! [[ "${ORCA_TIMING_METRICS}" =~ ^[01]$ ]]; then
  echo "ORCA_TIMING_METRICS must be 0 or 1: ${ORCA_TIMING_METRICS}"
  exit 1
fi

if ! [[ "${ORCA_COMPACT_SUMMARY}" =~ ^[01]$ ]]; then
  echo "ORCA_COMPACT_SUMMARY must be 0 or 1: ${ORCA_COMPACT_SUMMARY}"
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
SESSION_LOGFILE="${ROOT}/agent-logs/${AGENT_NAME}-${AGENT_SESSION_ID}.log"
SUMMARY_FILE=""
LAST_MESSAGE_FILE=""
METRICS_FILE="${ROOT}/agent-logs/metrics.jsonl"
: > "${SESSION_LOGFILE}"
touch "${METRICS_FILE}"

RUN_NUMBER=0
RUN_ISSUE_ID=""
RUN_ISSUE_SAFE_ID=""
RUN_TIMESTAMP=""
RUN_BASE=""
RUN_SOURCE_COMMIT=""
RUN_AGENT_STATUS="not_run"
RUN_MERGE_STATUS="not_run"
RUN_CLOSE_STATUS="not_run"
RUN_RESULT_STATUS="unknown"
RUN_RESULT_REASON="not-set"
RUN_SYNC_START_STATUS="not_run"
RUN_SYNC_END_STATUS="not_run"
RUN_SYNC_START_DURATION_SECONDS=0
RUN_QUEUE_CLAIM_DURATION_SECONDS=0
RUN_AGENT_DURATION_SECONDS=0
RUN_MERGE_DURATION_SECONDS=0
RUN_CLOSE_DURATION_SECONDS=0
RUN_SYNC_END_DURATION_SECONDS=0
RUN_ITERATION_TOTAL_SECONDS=0
RUN_TOKENS_USED=""
RUN_TOKENS_PARSE_STATUS="missing"
RUN_FORBIDDEN_COMMANDS=""

log() {
  local line
  line="$(printf '[%s] [%s] %s\n' "$(date -Iseconds)" "${AGENT_NAME}" "$*")"
  printf '%s\n' "${line}" >> "${SESSION_LOGFILE}"
  if [[ -n "${LOGFILE}" ]]; then
    printf '%s\n' "${line}" | tee -a "${LOGFILE}" >&2
  else
    printf '%s\n' "${line}" >&2
  fi
}

sanitize_for_filename() {
  printf '%s' "$1" | tr -c 'A-Za-z0-9._-' '_'
}

start_run_logfile() {
  local issue_id="$1"
  RUN_NUMBER=$((runs_completed + 1))
  RUN_ISSUE_ID="${issue_id}"
  RUN_ISSUE_SAFE_ID="$(sanitize_for_filename "${issue_id}")"
  RUN_TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
  RUN_BASE="${ROOT}/agent-logs/${AGENT_NAME}-${AGENT_SESSION_ID}-run-${RUN_NUMBER}-${RUN_ISSUE_SAFE_ID}-${RUN_TIMESTAMP}"
  LOGFILE="${RUN_BASE}.log"
  SUMMARY_FILE="${RUN_BASE}-summary.md"
  LAST_MESSAGE_FILE="${RUN_BASE}-last-message.md"
  : > "${LOGFILE}"

  RUN_SOURCE_COMMIT=""
  RUN_AGENT_STATUS="not_run"
  RUN_MERGE_STATUS="not_run"
  RUN_CLOSE_STATUS="not_run"
  RUN_RESULT_STATUS="unknown"
  RUN_RESULT_REASON="not-set"
  RUN_SYNC_START_STATUS="not_run"
  RUN_SYNC_END_STATUS="not_run"
  RUN_SYNC_START_DURATION_SECONDS=0
  RUN_QUEUE_CLAIM_DURATION_SECONDS=0
  RUN_AGENT_DURATION_SECONDS=0
  RUN_MERGE_DURATION_SECONDS=0
  RUN_CLOSE_DURATION_SECONDS=0
  RUN_SYNC_END_DURATION_SECONDS=0
  RUN_ITERATION_TOTAL_SECONDS=0
  RUN_TOKENS_USED=""
  RUN_TOKENS_PARSE_STATUS="missing"
  RUN_FORBIDDEN_COMMANDS=""

  log "starting run ${RUN_NUMBER} for ${issue_id}"
  log "session id: ${AGENT_SESSION_ID}"
  log "worktree: ${WORKTREE}"
  log "merge target: ${ORCA_MERGE_REMOTE}/${ORCA_MERGE_TARGET_BRANCH}"
}

now_epoch() {
  date +%s
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
  local open_children_count
  local -a ready_ids=()

  while [[ "${attempts}" -le "${READY_MAX_ATTEMPTS}" ]]; do
    if ready_json="$(bd ready --json 2>/dev/null)" \
      && mapfile -t ready_ids < <(jq -r '.[].id // empty' <<<"${ready_json}" 2>/dev/null); then
      if [[ "${#ready_ids[@]}" -eq 0 ]]; then
        printf '\n'
        return 0
      fi

      for issue_id in "${ready_ids[@]}"; do
        if open_children_count="$(open_child_count_with_retry "${issue_id}")"; then
          if [[ "${open_children_count}" -gt 0 ]]; then
            log "skipping ready issue ${issue_id}; ${open_children_count} child issues are still open"
            continue
          fi
        else
          log "failed to inspect child status for ${issue_id}; treating it as claimable"
        fi

        printf '%s\n' "${issue_id}"
        return 0
      done

      log "ready queue has no claimable leaf issues; exiting this loop pass"
      printf '\n'
      return 0
    fi

    log "failed to poll ready beads (attempt ${attempts}/${READY_MAX_ATTEMPTS}); retrying in ${READY_RETRY_SECONDS}s"
    sleep "${READY_RETRY_SECONDS}"
    attempts=$((attempts + 1))
  done

  return 1
}

open_child_count_with_retry() {
  local issue_id="$1"
  local attempts=1
  local max_attempts=3
  local children_json
  local open_count

  while [[ "${attempts}" -le "${max_attempts}" ]]; do
    if children_json="$(bd children "${issue_id}" --json 2>/dev/null)" \
      && open_count="$(jq -r '[.[] | select(.status != "closed")] | length' <<<"${children_json}" 2>/dev/null)" \
      && [[ "${open_count}" =~ ^[0-9]+$ ]]; then
      printf '%s\n' "${open_count}"
      return 0
    fi

    log "failed to inspect child status for ${issue_id}; attempt ${attempts}/${max_attempts}"
    attempts=$((attempts + 1))
    sleep 2
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

log_multiline_output() {
  local prefix="$1"
  local output="$2"
  local line
  while IFS= read -r line; do
    [[ -z "${line}" ]] && continue
    log "${prefix}: ${line}"
  done <<< "${output}"
}

build_agent_command_for_run() {
  RUN_AGENT_COMMAND="${AGENT_COMMAND}"

  if [[ "${ORCA_COMPACT_SUMMARY}" -ne 1 ]]; then
    return
  fi

  if [[ "${RUN_AGENT_COMMAND}" != *"codex exec"* ]]; then
    return
  fi

  if [[ "${RUN_AGENT_COMMAND}" == *"--output-last-message"* ]]; then
    return
  fi

  RUN_AGENT_COMMAND="${RUN_AGENT_COMMAND} --output-last-message $(printf '%q' "${LAST_MESSAGE_FILE}")"
}

detect_forbidden_landing_commands() {
  local found=()

  [[ -f "${LOGFILE}" ]] || return 1

  if grep -Fq -- "-lc 'git pull --rebase" "${LOGFILE}"; then
    found+=("git pull --rebase")
  fi
  if grep -Fq -- "-lc 'bd sync" "${LOGFILE}"; then
    found+=("bd sync")
  fi
  if grep -Fq -- "-lc 'git remote prune origin" "${LOGFILE}"; then
    found+=("git remote prune origin")
  fi

  if [[ "${#found[@]}" -eq 0 ]]; then
    RUN_FORBIDDEN_COMMANDS=""
    return 1
  fi

  RUN_FORBIDDEN_COMMANDS="$(IFS=,; printf '%s' "${found[*]}")"
  return 0
}

extract_tokens_used_from_run_log() {
  local raw
  RUN_TOKENS_USED=""
  RUN_TOKENS_PARSE_STATUS="missing"

  [[ -f "${LOGFILE}" ]] || return

  raw="$(awk '/^tokens used$/ {getline; print; exit}' "${LOGFILE}" | tr -d '\r')"
  if [[ -z "${raw}" ]]; then
    return
  fi

  raw="$(printf '%s' "${raw}" | tr -d ' ,')"
  if [[ "${raw}" =~ ^[0-9]+$ ]]; then
    RUN_TOKENS_USED="${raw}"
    RUN_TOKENS_PARSE_STATUS="ok"
    return
  fi

  RUN_TOKENS_PARSE_STATUS="parse_error"
}

append_metrics_jsonl() {
  local tokens_json
  local commands_csv="$1"

  if [[ -n "${RUN_TOKENS_USED}" ]]; then
    tokens_json="${RUN_TOKENS_USED}"
  else
    tokens_json="null"
  fi

  jq -nc \
    --arg ts "$(date -Iseconds)" \
    --arg agent "${AGENT_NAME}" \
    --arg session "${AGENT_SESSION_ID}" \
    --arg issue "${RUN_ISSUE_ID}" \
    --arg branch "${EXPECTED_BRANCH}" \
    --arg commit "${RUN_SOURCE_COMMIT}" \
    --arg result "${RUN_RESULT_STATUS}" \
    --arg reason "${RUN_RESULT_REASON}" \
    --arg agent_status "${RUN_AGENT_STATUS}" \
    --arg merge_status "${RUN_MERGE_STATUS}" \
    --arg close_status "${RUN_CLOSE_STATUS}" \
    --arg sync_start_status "${RUN_SYNC_START_STATUS}" \
    --arg sync_end_status "${RUN_SYNC_END_STATUS}" \
    --arg tokens_parse_status "${RUN_TOKENS_PARSE_STATUS}" \
    --arg commands_csv "${commands_csv}" \
    --arg summary_file "${SUMMARY_FILE}" \
    --arg logfile "${LOGFILE}" \
    --arg last_message_file "${LAST_MESSAGE_FILE}" \
    --argjson run_number "${RUN_NUMBER}" \
    --argjson tokens_used "${tokens_json}" \
    --argjson sync_start_seconds "${RUN_SYNC_START_DURATION_SECONDS}" \
    --argjson queue_claim_seconds "${RUN_QUEUE_CLAIM_DURATION_SECONDS}" \
    --argjson agent_seconds "${RUN_AGENT_DURATION_SECONDS}" \
    --argjson merge_seconds "${RUN_MERGE_DURATION_SECONDS}" \
    --argjson close_seconds "${RUN_CLOSE_DURATION_SECONDS}" \
    --argjson sync_end_seconds "${RUN_SYNC_END_DURATION_SECONDS}" \
    --argjson total_seconds "${RUN_ITERATION_TOTAL_SECONDS}" \
    '{
      timestamp: $ts,
      agent_name: $agent,
      session_id: $session,
      run_number: $run_number,
      issue_id: $issue,
      branch: $branch,
      source_commit: $commit,
      result: $result,
      reason: $reason,
      statuses: {
        agent: $agent_status,
        merge: $merge_status,
        close: $close_status,
        sync_start: $sync_start_status,
        sync_end: $sync_end_status
      },
      durations_seconds: {
        sync_start: $sync_start_seconds,
        queue_claim: $queue_claim_seconds,
        agent_run: $agent_seconds,
        merge: $merge_seconds,
        close: $close_seconds,
        sync_end: $sync_end_seconds,
        iteration_total: $total_seconds
      },
      tokens_used: $tokens_used,
      tokens_parse_status: $tokens_parse_status,
      minimal_landing_forbidden_commands: (
        if ($commands_csv | length) > 0 then ($commands_csv | split(","))
        else [] end
      ),
      files: {
        summary: $summary_file,
        run_log: $logfile,
        agent_last_message: $last_message_file
      }
    }' >> "${METRICS_FILE}"
}

write_run_summary() {
  local commands_csv="$1"
  local tokens_display="$2"
  local final_message_note="(not captured)"

  if [[ -f "${LAST_MESSAGE_FILE}" ]]; then
    final_message_note="${LAST_MESSAGE_FILE}"
  fi

  {
    echo "# Orca Run Summary"
    echo
    echo "- Timestamp: $(date -Iseconds)"
    echo "- Agent: ${AGENT_NAME}"
    echo "- Session: ${AGENT_SESSION_ID}"
    echo "- Run: ${RUN_NUMBER}"
    echo "- Issue: ${RUN_ISSUE_ID}"
    echo "- Branch: ${EXPECTED_BRANCH}"
    echo "- Source Commit: ${RUN_SOURCE_COMMIT:-unknown}"
    echo "- Result: ${RUN_RESULT_STATUS} (${RUN_RESULT_REASON})"
    echo "- Statuses: agent=${RUN_AGENT_STATUS}, merge=${RUN_MERGE_STATUS}, close=${RUN_CLOSE_STATUS}, sync_start=${RUN_SYNC_START_STATUS}, sync_end=${RUN_SYNC_END_STATUS}"
    echo "- Tokens Used: ${tokens_display} (${RUN_TOKENS_PARSE_STATUS})"
    if [[ -n "${commands_csv}" ]]; then
      echo "- Minimal Landing Warnings: ${commands_csv}"
    else
      echo "- Minimal Landing Warnings: none"
    fi
    echo
    echo "## Timings (seconds)"
    echo "- sync_start: ${RUN_SYNC_START_DURATION_SECONDS}"
    echo "- queue_claim: ${RUN_QUEUE_CLAIM_DURATION_SECONDS}"
    echo "- agent_run: ${RUN_AGENT_DURATION_SECONDS}"
    echo "- merge: ${RUN_MERGE_DURATION_SECONDS}"
    echo "- close: ${RUN_CLOSE_DURATION_SECONDS}"
    echo "- sync_end: ${RUN_SYNC_END_DURATION_SECONDS}"
    echo "- iteration_total: ${RUN_ITERATION_TOTAL_SECONDS}"
    echo
    echo "## Artifacts"
    echo "- Run Log: ${LOGFILE}"
    echo "- Agent Final Message: ${final_message_note}"
  } > "${SUMMARY_FILE}"

  if [[ -f "${LAST_MESSAGE_FILE}" ]]; then
    {
      echo
      echo "## Agent Final Message (first 120 lines)"
      echo
      sed -n '1,120p' "${LAST_MESSAGE_FILE}"
    } >> "${SUMMARY_FILE}"
  fi
}

finalize_run_artifacts() {
  local commands_csv=""
  local tokens_display="n/a"

  if [[ "${ORCA_MINIMAL_LANDING}" -eq 1 ]] && detect_forbidden_landing_commands; then
    commands_csv="${RUN_FORBIDDEN_COMMANDS}"
    log "minimal landing warning: detected forbidden closeout commands in run log: ${commands_csv}"
  fi

  extract_tokens_used_from_run_log
  if [[ -n "${RUN_TOKENS_USED}" ]]; then
    tokens_display="${RUN_TOKENS_USED}"
  fi

  if [[ "${ORCA_TIMING_METRICS}" -eq 1 ]]; then
    log "timing metrics (s): sync_start=${RUN_SYNC_START_DURATION_SECONDS} queue_claim=${RUN_QUEUE_CLAIM_DURATION_SECONDS} agent=${RUN_AGENT_DURATION_SECONDS} merge=${RUN_MERGE_DURATION_SECONDS} close=${RUN_CLOSE_DURATION_SECONDS} sync_end=${RUN_SYNC_END_DURATION_SECONDS} total=${RUN_ITERATION_TOTAL_SECONDS}"
    log "token metrics: used=${tokens_display} parse_status=${RUN_TOKENS_PARSE_STATUS}"
    if ! append_metrics_jsonl "${commands_csv}"; then
      log "failed to append metrics row for ${RUN_ISSUE_ID}"
    fi
  fi

  if [[ "${ORCA_COMPACT_SUMMARY}" -eq 1 ]]; then
    if write_run_summary "${commands_csv}" "${tokens_display}"; then
      log "wrote run summary: ${SUMMARY_FILE}"
    else
      log "failed to write run summary for ${RUN_ISSUE_ID}"
    fi
  fi
}

recover_missing_upstream_branch_if_needed() {
  local pull_output="$1"
  local remote_name
  local push_output

  if [[ "${pull_output}" != *"no such ref was fetched"* ]]; then
    return 1
  fi

  remote_name="$(git config --get "branch.${EXPECTED_BRANCH}.remote" || true)"
  remote_name="${remote_name:-origin}"
  log "upstream ref missing for ${EXPECTED_BRANCH}; attempting to recreate via git push -u ${remote_name} ${EXPECTED_BRANCH}"

  if push_output="$(git push -u "${remote_name}" "${EXPECTED_BRANCH}" 2>&1)"; then
    log "recreated upstream branch for ${EXPECTED_BRANCH} on ${remote_name}"
    return 0
  fi

  log "failed to recreate upstream branch for ${EXPECTED_BRANCH}"
  log_multiline_output "git push -u" "${push_output}"
  return 1
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
  local open_children_count
  local close_guard_note
  local merge_started_epoch
  local close_started_epoch

  merge_started_epoch="$(now_epoch)"
  source_commit="$(git rev-parse HEAD)"
  RUN_SOURCE_COMMIT="${source_commit}"
  log "starting merge for ${issue_id}: ${EXPECTED_BRANCH}@${source_commit} -> ${ORCA_MERGE_REMOTE}/${ORCA_MERGE_TARGET_BRANCH}"
  if ! "${MERGE_SCRIPT}" \
    --source-branch "${EXPECTED_BRANCH}" \
    --required-commit "${source_commit}" \
    --remote "${ORCA_MERGE_REMOTE}" \
    --target-branch "${ORCA_MERGE_TARGET_BRANCH}" \
    --lock-timeout "${ORCA_MERGE_LOCK_TIMEOUT_SECONDS}" \
    --max-attempts "${ORCA_MERGE_MAX_ATTEMPTS}" >>"${LOGFILE}" 2>&1; then
    RUN_MERGE_DURATION_SECONDS=$(( $(now_epoch) - merge_started_epoch ))
    RUN_MERGE_STATUS="failed"
    RUN_CLOSE_STATUS="skipped"
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
  RUN_MERGE_DURATION_SECONDS=$(( $(now_epoch) - merge_started_epoch ))
  RUN_MERGE_STATUS="success"
  log "merge succeeded for ${issue_id}"

  if open_children_count="$(open_child_count_with_retry "${issue_id}")" \
    && [[ "${open_children_count}" -gt 0 ]]; then
    close_guard_note="Work for ${issue_id} was merged into ${ORCA_MERGE_REMOTE}/${ORCA_MERGE_TARGET_BRANCH} at $(date -Iseconds), but the issue has ${open_children_count} open child issues. Keeping parent issue open until child tasks are closed."
    close_started_epoch="$(now_epoch)"
    RUN_CLOSE_DURATION_SECONDS=0
    if update_issue_to_open_with_retry "${issue_id}" "${close_guard_note}" "close-guard-open-children"; then
      RUN_CLOSE_DURATION_SECONDS=$(( $(now_epoch) - close_started_epoch ))
      RUN_CLOSE_STATUS="skipped_open_children"
      log "merge completed for ${issue_id}; left issue open because ${open_children_count} child issues remain open"
      current_issue_id=""
      current_issue_should_reopen=1
      return 0
    fi

    RUN_CLOSE_DURATION_SECONDS=$(( $(now_epoch) - close_started_epoch ))
    RUN_CLOSE_STATUS="failed"
    log "merge completed for ${issue_id}, but failed to keep issue open while child issues remain; manual intervention needed"
    current_issue_id=""
    current_issue_should_reopen=1
    return 1
  fi

  close_started_epoch="$(now_epoch)"
  if close_issue_if_needed_with_retry "${issue_id}"; then
    RUN_CLOSE_DURATION_SECONDS=$(( $(now_epoch) - close_started_epoch ))
    RUN_CLOSE_STATUS="success"
    log "issue ${issue_id} closed after successful merge"
    current_issue_id=""
    current_issue_should_reopen=1
    return 0
  fi

  close_failure_note="Work for ${issue_id} was merged into ${ORCA_MERGE_REMOTE}/${ORCA_MERGE_TARGET_BRANCH} at $(date -Iseconds), but automatic issue close failed. Manual close required."
  RUN_CLOSE_DURATION_SECONDS=$(( $(now_epoch) - close_started_epoch ))
  RUN_CLOSE_STATUS="failed"
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
  local attempts=1
  local pull_output
  local sync_output

  while [[ "${attempts}" -le "${SYNC_MAX_ATTEMPTS}" ]]; do
    guard_worktree_state_or_exit "${context}:pre-sync"

    if ! pull_output="$(git pull --rebase --autostash 2>&1)"; then
      log "git pull --rebase --autostash failed during ${context}; attempt ${attempts}/${SYNC_MAX_ATTEMPTS}"
      log_multiline_output "git pull" "${pull_output}"
      abort_rebase_if_needed
      if recover_missing_upstream_branch_if_needed "${pull_output}"; then
        attempts=$((attempts + 1))
        continue
      fi
      if [[ "${attempts}" -lt "${SYNC_MAX_ATTEMPTS}" ]]; then
        sleep "${SYNC_RETRY_SECONDS}"
        attempts=$((attempts + 1))
        continue
      fi
      return 1
    fi

    if ! sync_output="$(bd sync 2>&1)"; then
      log "bd sync failed during ${context}; attempt ${attempts}/${SYNC_MAX_ATTEMPTS}"
      log_multiline_output "bd sync" "${sync_output}"
      if [[ "${attempts}" -lt "${SYNC_MAX_ATTEMPTS}" ]]; then
        sleep "${SYNC_RETRY_SECONDS}"
        attempts=$((attempts + 1))
        continue
      fi
      return 1
    fi

    guard_worktree_state_or_exit "${context}:post-sync"
    return 0
  done

  return 1
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
  iteration_started_epoch="$(now_epoch)"

  if [[ "${MAX_RUNS}" -gt 0 && "${runs_completed}" -ge "${MAX_RUNS}" ]]; then
    log "max runs reached (${runs_completed}/${MAX_RUNS}); exiting loop"
    break
  fi

  sync_start_stage_started_epoch="$(now_epoch)"
  if ! sync_with_remote_or_exit "iteration-start"; then
    log "sync failed during iteration-start after ${SYNC_MAX_ATTEMPTS} attempts; continuing loop after ${SYNC_RETRY_SECONDS}s"
    sleep "${SYNC_RETRY_SECONDS}"
    continue
  fi

  queue_claim_stage_started_epoch="$(now_epoch)"
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
  RUN_SYNC_START_STATUS="success"
  RUN_SYNC_START_DURATION_SECONDS=$(( $(now_epoch) - sync_start_stage_started_epoch ))
  RUN_QUEUE_CLAIM_DURATION_SECONDS=$(( $(now_epoch) - queue_claim_stage_started_epoch ))

  prompt_text="$(cat "${PROMPT_TEMPLATE}")"
  prompt_text="${prompt_text//__AGENT_NAME__/${AGENT_NAME}}"
  prompt_text="${prompt_text//__ISSUE_ID__/${issue_id}}"
  prompt_text="${prompt_text//__WORKTREE__/${WORKTREE}}"

  tmp_prompt="$(mktemp)"
  printf '%s\n' "${prompt_text}" > "${tmp_prompt}"

  build_agent_command_for_run
  log "running agent command for ${issue_id}"
  agent_stage_started_epoch="$(now_epoch)"
  if bash -lc "${RUN_AGENT_COMMAND}" < "${tmp_prompt}" >>"${LOGFILE}" 2>&1; then
    RUN_AGENT_DURATION_SECONDS=$(( $(now_epoch) - agent_stage_started_epoch ))
    RUN_AGENT_STATUS="success"
    log "agent command finished for ${issue_id}"
    guard_worktree_state_or_exit "post-agent:${issue_id}"

    RUN_SOURCE_COMMIT="$(git rev-parse HEAD)"

    if [[ "${ORCA_MINIMAL_LANDING}" -eq 1 ]] && detect_forbidden_landing_commands; then
      if [[ "${ORCA_ENFORCE_MINIMAL_LANDING}" -eq 1 ]]; then
        enforcement_note="Detected forbidden closeout commands in ${AGENT_NAME} at $(date -Iseconds): ${RUN_FORBIDDEN_COMMANDS}. Returning issue to open for retry."
        if update_issue_to_open_with_retry "${issue_id}" "${enforcement_note}" "minimal-landing-enforced"; then
          log "minimal landing enforcement: returned ${issue_id} to open"
        else
          log "minimal landing enforcement failed to return ${issue_id} to open; manual intervention needed"
        fi
        RUN_MERGE_STATUS="skipped"
        RUN_CLOSE_STATUS="skipped"
        RUN_RESULT_STATUS="failed"
        RUN_RESULT_REASON="minimal-landing-enforced"
        current_issue_id=""
        current_issue_should_reopen=1
        stop_after_iteration=1
      fi
    fi

    if [[ "${stop_after_iteration}" -eq 0 ]]; then
      if merge_issue_or_return_to_open "${issue_id}"; then
        RUN_RESULT_STATUS="success"
        if [[ "${RUN_CLOSE_STATUS}" == "skipped_open_children" ]]; then
          RUN_RESULT_REASON="merged-parent-left-open"
        else
          RUN_RESULT_REASON="merged-and-closed"
        fi
      else
        if [[ "${RUN_MERGE_STATUS}" == "failed" ]]; then
          RUN_RESULT_STATUS="failed"
          RUN_RESULT_REASON="merge-failure"
        elif [[ "${RUN_CLOSE_STATUS}" == "failed" ]]; then
          RUN_RESULT_STATUS="failed"
          RUN_RESULT_REASON="close-after-merge-failure"
        else
          RUN_RESULT_STATUS="failed"
          RUN_RESULT_REASON="merge-or-finalization-failure"
        fi
        stop_after_iteration=1
      fi
    fi
  else
    RUN_AGENT_DURATION_SECONDS=$(( $(now_epoch) - agent_stage_started_epoch ))
    RUN_AGENT_STATUS="failed"
    RUN_MERGE_STATUS="skipped"
    RUN_CLOSE_STATUS="skipped"
    RUN_RESULT_STATUS="failed"
    RUN_RESULT_REASON="agent-command-failure"
    log "agent command failed for ${issue_id}; returning issue to open"
    failure_note="Agent loop failure in ${AGENT_NAME} at $(date -Iseconds). Command: ${RUN_AGENT_COMMAND}. Returning issue to open for retry."
    if update_issue_to_open_with_retry "${issue_id}" "${failure_note}" "agent-command-failure"; then
      log "returned ${issue_id} to open"
    else
      log "failed to return ${issue_id} to open; manual intervention needed"
    fi
    current_issue_id=""
    current_issue_should_reopen=1
  fi

  rm -f "${tmp_prompt}"

  sync_end_stage_started_epoch="$(now_epoch)"
  if ! sync_with_remote_or_exit "iteration-end"; then
    RUN_SYNC_END_STATUS="failed"
    RUN_SYNC_END_DURATION_SECONDS=$(( $(now_epoch) - sync_end_stage_started_epoch ))
    log "sync failed during iteration-end after ${SYNC_MAX_ATTEMPTS} attempts; continuing loop after ${SYNC_RETRY_SECONDS}s"
    sleep "${SYNC_RETRY_SECONDS}"
  else
    RUN_SYNC_END_STATUS="success"
    RUN_SYNC_END_DURATION_SECONDS=$(( $(now_epoch) - sync_end_stage_started_epoch ))
  fi

  RUN_ITERATION_TOTAL_SECONDS=$(( $(now_epoch) - iteration_started_epoch ))
  finalize_run_artifacts

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
