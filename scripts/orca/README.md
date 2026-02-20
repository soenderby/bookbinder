# Orca Scripts

This directory contains the Orca multi-agent orchestration scripts.

## Entrypoints

- Preferred: `./bb orca <command> [args]`
- Direct: `scripts/orca/orca.sh <command> [args]`

## Commands

- `start [count] [--runs N|--continuous] [--reasoning-level LEVEL]`
- `stop`
- `status`
- `setup-worktrees [count]`
- `audit-consistency`

## TODO
In no particular order:
 - A/B testing prompts
 - Agent loop metrics in sqlite database
 - Agent loop handoff
 - Sharing or storing lessons learned from run
 - Streamline loop prompt (likely tied to A/B testing)

## Architecture Overview

Orca is a `tmux`-backed multi-agent loop with one persistent git worktree per agent:

1. `setup-worktrees.sh` ensures `worktrees/agent-N` and branch `swarm/agent-N` exist.
2. `start.sh` launches one tmux session per agent and injects runtime env.
3. `agent-loop.sh` runs inside each session, polling `bd ready`, claiming one issue, running the agent command, then repeating.
4. `merge-after-run.sh` serializes integration from `swarm/agent-N` branches into `main` using a global `flock` lock.
5. `status.sh` gives a multi-signal health snapshot (sessions, worktrees, queue, logs).
6. `stop.sh` terminates active agent tmux sessions by prefix.

## File Roles

- `orca.sh`: command dispatcher
- `setup-worktrees.sh`: creates and verifies persistent agent worktrees
- `start.sh`: launches tmux-backed agent loops
- `agent-loop.sh`: per-agent loop for claiming and processing beads tasks
- `merge-after-run.sh`: lock-protected integration step to merge completed agent branch work into target branch
- `status.sh`: displays sessions, worktrees, and recent activity
- `audit-consistency.sh`: validates parent/child status consistency in beads
- `stop.sh`: stops active agent sessions
- `AGENT_PROMPT.md`: prompt template used by `agent-loop.sh`

## Core Loop Logic (`agent-loop.sh`)

Each iteration follows this flow:

1. Pre-sync guardrail: verify expected branch and clean worktree (`git status --porcelain` empty).
2. Sync: run `git pull --rebase --autostash` then `bd sync`; retry bounded times on failure and continue loop with backoff if sync is still unavailable.
   - if pull fails because upstream ref is missing, the loop tries `git push -u` to restore the worker branch upstream.
3. Poll queue: call `bd ready --json` with bounded retries and backoff, then prefer claimable leaf issues.
   - ready parent issues with open child tasks are skipped automatically.
4. Claim work: attempt atomic claim via `bd update <id> --claim`; if claim race is lost, retry later.
5. Run agent: render `AGENT_PROMPT.md` placeholders and run `AGENT_COMMAND`, logging to a per-run file.
6. Post-agent handling: on success, re-check branch/cleanliness, apply minimal-closeout policy checks, and run `merge-after-run.sh`; on failure, return issue to `open` with notes.
   - merge step requires the agent run HEAD commit to be present on `origin/swarm/agent-N` before integration.
7. Close issue after merge: close the bead only if merge succeeded and the issue has no open child tasks.
   - if child tasks are still open, the parent issue is explicitly kept open with an audit note.
8. Post-sync guardrail: re-run the same fail-fast sync path as step 2.
9. Exit conditions: no ready issues, `MAX_RUNS` reached, or hard guard/merge-finalization failure.

## Validation and Safety Checks

### `start.sh`

Checks before launching sessions:

1. prerequisites must exist: `git`, `tmux`, `bd`, `jq`, `flock`, plus the binary in `AGENT_COMMAND`
2. `count` must be positive integer
3. `MAX_RUNS` must be non-negative integer (`0` means unbounded)
4. `AGENT_REASONING_LEVEL` must match `[A-Za-z0-9._-]+`
5. `PROMPT_TEMPLATE` must exist

Behavior details:

1. default model is `gpt-5.3-codex`
2. if `--reasoning-level` is set and `AGENT_COMMAND` was not explicitly overridden, append `-c model_reasoning_effort=<level>`
3. if session already exists, it is left running (idempotent start)
4. invokes `setup-worktrees.sh` before launching tmux sessions

### `setup-worktrees.sh`

Worktree/upstream behavior:

1. ensures `worktrees/` directory exists
2. for each `agent-N`, creates worktree/branch only if missing (idempotent)
3. ensures branch upstream by first trying `git branch --set-upstream-to origin/<branch>`, then falling back to `git push -u origin <branch>` if needed
4. if `origin` remote is missing, logs warning and skips upstream setup

### `agent-loop.sh`

Input/env validation before loop:

1. `WORKTREE` is required and must be a valid git worktree
2. `MAX_RUNS` must be non-negative integer
3. `READY_MAX_ATTEMPTS` / `READY_RETRY_SECONDS` must be positive integers
4. `SYNC_MAX_ATTEMPTS` / `SYNC_RETRY_SECONDS` must be positive integers
5. `ORCA_MINIMAL_LANDING` / `ORCA_ENFORCE_MINIMAL_LANDING` must be `0|1`
6. `ORCA_TIMING_METRICS` / `ORCA_COMPACT_SUMMARY` must be `0|1`
7. `AGENT_REASONING_LEVEL` must match `[A-Za-z0-9._-]+`
8. `MERGE_SCRIPT` must exist and be executable
9. `ORCA_MERGE_LOCK_TIMEOUT_SECONDS` / `ORCA_MERGE_MAX_ATTEMPTS` must be positive integers
10. expected branch is captured at startup and must remain stable

Signal and interruption handling:

1. traps `INT`, `TERM`, `EXIT`
2. if an issue is currently claimed, tries to return it to `open` with retries and note
3. avoids re-entrant cleanup with `cleanup_in_progress` guard

### `status.sh`

Observability behavior:

1. prints session list scoped by `SESSION_PREFIX`
2. prints `git worktree list`
3. prints current in-progress issues, recently closed issues, and ready queue
4. prints available log filenames under `agent-logs/`
5. prints recent summary files (`*-summary.md`)
6. prints latest metrics rows (`agent-logs/metrics.jsonl`)
7. runs `scripts/orca/audit-consistency.sh` to surface tracker drift
8. uses `safe_run` wrappers so partial command failures do not crash status output

### `stop.sh`

Shutdown behavior:

1. finds tmux sessions by `SESSION_PREFIX`
2. kills each matching session
3. exits cleanly if none exist

## Error Handling Model

The scripts intentionally split failures into two categories:

1. Hard-stop failures (loop exits): dirty worktree at guard checkpoints, unfixable branch drift, merge conflict/failure, or close-after-merge failure.
2. Recoverable/transient failures (loop continues): transient `bd ready --json` failure (bounded retries), sync failures (`git pull`/`bd sync`) after bounded retries, claim race on `--claim`, minimal-closeout violations in warning mode, or temporary failure returning issue to open (retries, then manual-intervention warning).

Minimal-closeout policy:
1. In loop mode, agents should avoid `git pull --rebase`, `bd sync`, and `git remote prune origin` during each issue run.
2. Current default is warning mode (`ORCA_ENFORCE_MINIMAL_LANDING=0`): violations are logged and surfaced in metrics/summaries.
3. Planned future change (not active yet): set `ORCA_ENFORCE_MINIMAL_LANDING=1` to fail the run and return the issue to `open` on violation.

Issue release retry policy:

1. when agent run fails or loop is interrupted while holding a claim, Orca retries `bd update ... --status open` up to 3 times
2. all retries append timestamped notes for auditability
3. persistent failure is logged as manual-intervention-needed

## Logs and Traceability

Session logs are written to:

`agent-logs/<agent-name>-<session-id>.log`

Per-run logs are written to:

`agent-logs/<agent-name>-<session-id>-run-<n>-<issue-id>-<timestamp>.log`

Per-run compact summaries are written to:

`agent-logs/<agent-name>-<session-id>-run-<n>-<issue-id>-<timestamp>-summary.md`

Per-run metrics are appended to:

`agent-logs/metrics.jsonl`

Each run logs at least:

1. session id and worktree
2. claimed issue id
3. agent command start/finish
4. sync/guard failures
5. claim-release failures/retries
6. stage timings and token usage parse status

This gives a full timeline for debugging queue behavior and git-state issues.

## Runtime Knobs

- `MAX_RUNS`: number of issue runs per loop (`0` means unbounded until queue empty)
- `AGENT_MODEL`: default `gpt-5.3-codex` for default codex command
- `AGENT_REASONING_LEVEL`: value passed as `model_reasoning_effort` for default codex command
- `READY_MAX_ATTEMPTS`: retries for `bd ready --json` polling (default: `5`)
- `READY_RETRY_SECONDS`: seconds between ready polling retries (default: `3`)
- `SYNC_MAX_ATTEMPTS`: retries for sync stage (`git pull` + `bd sync`) before loop backoff (default: `3`)
- `SYNC_RETRY_SECONDS`: seconds between sync retries/backoff (default: `5`)
- `ORCA_MINIMAL_LANDING`: enable minimal-closeout policy checks (`1` default)
- `ORCA_ENFORCE_MINIMAL_LANDING`: enforce minimal-closeout policy as hard-fail (`0` default; future strict mode switch)
- `ORCA_TIMING_METRICS`: emit per-run timing/token metrics to `metrics.jsonl` (`1` default)
- `ORCA_COMPACT_SUMMARY`: emit per-run summary markdown and capture final agent message when possible (`1` default)
- `SESSION_PREFIX`: tmux session prefix (default: `bb-agent`)
- `PROMPT_TEMPLATE`: path to prompt template (default: `scripts/orca/AGENT_PROMPT.md`)
- `AGENT_COMMAND`: full command used for each agent pass (default: `codex exec ...`)
- `ORCA_MERGE_REMOTE`: remote used for integration (default: `origin`)
- `ORCA_MERGE_TARGET_BRANCH`: branch integrated after each successful run (default: `main`)
- `ORCA_MERGE_LOCK_TIMEOUT_SECONDS`: wait time for global merge lock (default: `120`)
- `ORCA_MERGE_MAX_ATTEMPTS`: retries for transient merge fetch/push failures (default: `3`)
