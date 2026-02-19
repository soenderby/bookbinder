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
AGENT_MODEL="${AGENT_MODEL:-gpt-5}"
AGENT_COMMAND="${AGENT_COMMAND:-codex exec --dangerously-bypass-approvals-and-sandbox --model ${AGENT_MODEL}}"
PROMPT_TEMPLATE="${PROMPT_TEMPLATE:-${ROOT}/scripts/swarm/AGENT_PROMPT.md}"
POLL_SECONDS="${POLL_SECONDS:-20}"

mkdir -p "${ROOT}/agent-logs"
LOGFILE="${ROOT}/agent-logs/${AGENT_NAME}.log"

log() {
  printf '[%s] [%s] %s\n' "$(date -Iseconds)" "${AGENT_NAME}" "$*" | tee -a "${LOGFILE}"
}

cd "${WORKTREE}"
log "starting loop in ${WORKTREE}"

while true; do
  git pull --rebase --autostash >/dev/null 2>&1 || true
  bd sync >/dev/null 2>&1 || true

  issue_id="$(bd ready --json | jq -r '.[0].id // empty')"

  if [[ -z "${issue_id}" ]]; then
    log "no ready beads; sleeping ${POLL_SECONDS}s"
    sleep "${POLL_SECONDS}"
    continue
  fi

  if ! bd update "${issue_id}" --claim >/dev/null 2>&1; then
    log "could not claim ${issue_id}; likely claimed by another agent"
    sleep 3
    continue
  fi

  log "claimed ${issue_id}"

  prompt_text="$(cat "${PROMPT_TEMPLATE}")"
  prompt_text="${prompt_text//__AGENT_NAME__/${AGENT_NAME}}"
  prompt_text="${prompt_text//__ISSUE_ID__/${issue_id}}"
  prompt_text="${prompt_text//__WORKTREE__/${WORKTREE}}"

  tmp_prompt="$(mktemp)"
  printf '%s\n' "${prompt_text}" > "${tmp_prompt}"

  log "running agent command for ${issue_id}"
  if bash -lc "${AGENT_COMMAND}" < "${tmp_prompt}" >>"${LOGFILE}" 2>&1; then
    log "agent command finished for ${issue_id}"
  else
    log "agent command failed for ${issue_id}; returning issue to open"
    failure_note="Agent loop failure in ${AGENT_NAME} at $(date -Iseconds). Command: ${AGENT_COMMAND}. Returning issue to open for retry."
    if bd update "${issue_id}" --status open --assignee "" --append-notes "${failure_note}" >/dev/null 2>&1; then
      log "returned ${issue_id} to open"
    else
      log "failed to return ${issue_id} to open; manual intervention needed"
    fi
  fi

  rm -f "${tmp_prompt}"

  git pull --rebase --autostash >/dev/null 2>&1 || true
  bd sync >/dev/null 2>&1 || true
  sleep 2
done
