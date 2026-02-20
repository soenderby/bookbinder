# Orca Scripts

This directory contains the Orca multi-agent orchestration scripts.

Orca-v2 is the active runtime. Loop orchestration is transport-focused, while agents own task policy and decisions.

## Entrypoints

- Preferred: `./bb orca <command> [args]`
- Direct: `scripts/orca/orca.sh <command> [args]`

## Commands

- `start [count] [--runs N|--continuous] [--reasoning-level LEVEL]`
- `stop`
- `status`
- `setup-worktrees [count]`
- `audit-consistency` (optional standalone consistency report)
- `with-lock [--scope NAME] [--timeout SECONDS] -- <command> [args...]`

Helper script (direct invocation):

- `scripts/orca/with-lock.sh [--scope NAME] [--timeout SECONDS] -- <command> [args...]`

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
3. `agent-loop.sh` runs one agent pass per iteration, writes per-run logs/metrics, and parses the agent summary JSON.
4. `AGENT_PROMPT.md` defines the v2 contract: the agent selects/claims work, owns issue transitions, and owns merge.
5. `with-lock.sh` provides the shared lock primitive for agent-owned merge/push critical sections.
6. `status.sh` gives a multi-signal health snapshot (sessions, worktrees, queue, logs).
7. `stop.sh` terminates active agent tmux sessions by prefix.

## File Roles

- `orca.sh`: command dispatcher
- `setup-worktrees.sh`: creates and verifies persistent agent worktrees
- `start.sh`: launches tmux-backed agent loops
- `agent-loop.sh`: per-agent run loop that executes the prompt, captures run artifacts, and records summary/metrics
- `with-lock.sh`: generic scoped lock wrapper for arbitrary commands that must serialize shared git integration operations
- `status.sh`: displays sessions, worktrees, and recent activity
- `audit-consistency.sh`: standalone optional report that validates parent/child status consistency in beads
- `stop.sh`: stops active agent sessions
- `AGENT_PROMPT.md`: v2 prompt contract used by `agent-loop.sh`

## Agent Merge Lock Pattern (`with-lock.sh`)

For agent-owned integration flows, the merge/push critical section must be wrapped in `with-lock.sh` so only one writer updates shared targets at a time.

Required pattern:

```bash
scripts/orca/with-lock.sh --scope merge --timeout 120 -- \
  bash -lc '
    git fetch origin main
    git checkout main
    git pull --ff-only origin main
    git merge --no-ff swarm/agent-1
    git push origin main
  '
```

Notes:

1. Default scope is `merge`.
2. Default lock file for `merge` scope is `<git-common-dir>/orca-global.lock`.
3. Non-default scopes use `<git-common-dir>/orca-global-<scope>.lock`.
4. Keep all shared-target write steps (`merge` + `push`) inside one `with-lock.sh` invocation.

## Agent Responsibilities (v2)

Per run, the agent is responsible for:

1. selecting and claiming one issue (`bd ready` + `bd update <id> --claim`)
2. owning issue transitions (`open`/`in_progress`/`blocked`/`closed`) and notes
3. implementing, validating, and documenting changes
4. performing merge/push itself with `scripts/orca/with-lock.sh`
5. capturing discoveries:
   - create follow-up beads when needed
   - append notes to `agent-logs/discoveries/<agent-name>.md` (injected as `ORCA_DISCOVERY_LOG_PATH`)
6. writing run summary JSON to the provided path

## Run Summary JSON Contract (v2)

The agent must write a JSON object to the path provided in the prompt (`__SUMMARY_JSON_PATH__` / `ORCA_RUN_SUMMARY_PATH`) with all fields below.

| Field | Type | Required | Allowed values / notes |
| --- | --- | --- | --- |
| `issue_id` | string | yes | Issue handled in this run. Use empty string when no issue was claimed. |
| `result` | string | yes | `completed`, `blocked`, `no_work`, `failed` |
| `issue_status` | string | yes | Current issue status after this run (for example `in_progress`, `blocked`, `closed`, `open`, or empty when `no_work`). |
| `merged` | boolean | yes | `true` only when merge/integration completed successfully in this run. |
| `discovery_ids` | array of strings | yes | IDs of follow-up beads created during this run. Use `[]` when none. |
| `discovery_count` | integer | yes | Must equal `discovery_ids` length. |
| `loop_action` | string | yes | `continue` or `stop` |
| `loop_action_reason` | string | yes | Reason for chosen `loop_action`; empty string allowed when not needed. |
| `notes` | string | yes | Short machine-readable run note/handoff. |

## Core Loop Logic (`agent-loop.sh`)

Each iteration follows this flow:

1. Start run artifacts (`*.log`, `*-summary.json`, optional compact summary markdown).
2. Render `AGENT_PROMPT.md` with runtime placeholders (agent name, worktree, summary path, discovery path).
3. Run the agent command once for this iteration.
4. Agent handles task policy: pick/claim issue, issue transitions, merge via `with-lock.sh`, and discovery capture.
5. Parse summary JSON when present and append metrics.
6. Continue until `MAX_RUNS` is reached, or stop when summary requests `loop_action=stop`.

## Validation and Safety Checks

### `start.sh`

Checks before launching sessions:

1. prerequisites must exist: `git`, `tmux`, `bd`, `jq`, `flock`, plus the binary in `AGENT_COMMAND`
2. `count` must be positive integer
3. `MAX_RUNS` must be non-negative integer (`0` means unbounded)
4. `RUN_SLEEP_SECONDS` must be non-negative integer
5. `ORCA_TIMING_METRICS` / `ORCA_COMPACT_SUMMARY` must be `0|1`
6. `ORCA_LOCK_SCOPE` must match `[A-Za-z0-9._-]+`
7. `ORCA_LOCK_TIMEOUT_SECONDS` must be a positive integer
8. `AGENT_REASONING_LEVEL` must match `[A-Za-z0-9._-]+`
9. `PROMPT_TEMPLATE` must exist

Behavior details:

1. default model is `gpt-5.3-codex`
2. if `--reasoning-level` is set and `AGENT_COMMAND` was not explicitly overridden, append `-c model_reasoning_effort=<level>`
3. if session already exists, it is left running (idempotent start)
4. invokes `setup-worktrees.sh` before launching tmux sessions
5. injects v2 runtime knobs into each loop session (`MAX_RUNS`, `RUN_SLEEP_SECONDS`, metrics toggles, lock scope/timeout)

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
3. `RUN_SLEEP_SECONDS` must be non-negative integer
4. `ORCA_TIMING_METRICS` / `ORCA_COMPACT_SUMMARY` must be `0|1`
5. `AGENT_REASONING_LEVEL` must match `[A-Za-z0-9._-]+` when set
6. `PROMPT_TEMPLATE` must exist

Signal and interruption handling:

1. traps `INT`, `TERM`, `EXIT`
2. logs shutdown signal and exits cleanly
3. avoids re-entrant cleanup with `cleanup_in_progress` guard

### `status.sh`

Observability behavior:

1. prints session list scoped by `SESSION_PREFIX`
2. prints `git worktree list`
3. prints current in-progress issues, recently closed issues, and ready queue
4. prints available log filenames under `agent-logs/`
5. prints recent summary files (`*-summary.md`)
6. prints latest metrics rows (`agent-logs/metrics.jsonl`)
7. skips consistency audit by default (can opt in with `ORCA_STATUS_RUN_AUDIT=1`)
8. uses `safe_run` wrappers so partial command failures do not crash status output

### `stop.sh`

Shutdown behavior:

1. finds tmux sessions by `SESSION_PREFIX`
2. kills each matching session
3. exits cleanly if none exist

## Error Handling Model

The v2 loop keeps workflow policy in the agent and treats script failures as transport/observability concerns:

1. Startup hard-stop failures: invalid env/config, invalid `WORKTREE`, or missing prompt template.
2. Run-level failures (loop continues by default): non-zero agent exit, missing/invalid summary JSON, or metrics append failure.
3. Controlled stop conditions: `MAX_RUNS` reached, or parsed summary requests `loop_action=stop`.

The loop does not claim/release/close issues in v2.

## Logs and Traceability

Session logs are written to:

`agent-logs/<agent-name>-<session-id>.log`

Per-run logs are written to:

`agent-logs/<agent-name>-<session-id>-run-<n>-<timestamp>.log`

Per-run summary JSON files are written to:

`agent-logs/<agent-name>-<session-id>-run-<n>-<timestamp>-summary.json`

Per-run compact summaries are written to:

`agent-logs/<agent-name>-<session-id>-run-<n>-<timestamp>-summary.md`

Per-run metrics are appended to:

`agent-logs/metrics.jsonl`

Per-agent discovery notes (agent-owned) should be appended to:

`agent-logs/discoveries/<agent-name>.md`

`agent-loop.sh` ensures this file exists before each run and exposes it to agents via:

- prompt placeholders: `__DISCOVERY_LOG_PATH__` (and alias `__AGENT_DISCOVERY_LOG_PATH__`)
- env vars: `ORCA_DISCOVERY_LOG_PATH` (and alias `ORCA_AGENT_DISCOVERY_LOG_PATH`)

Each run logs at least:

1. session id and worktree
2. agent command start/finish
3. run exit code and duration
4. summary parse status and parsed summary fields (when present)
5. stage timings and token usage parse status

This gives a full timeline for debugging queue behavior and git-state issues.

## Runtime Knobs

- `MAX_RUNS`: number of issue runs per loop (`0` means unbounded unless agent requests stop)
- `AGENT_MODEL`: default `gpt-5.3-codex` for default codex command
- `AGENT_REASONING_LEVEL`: value passed as `model_reasoning_effort` for default codex command
- `RUN_SLEEP_SECONDS`: sleep between iterations (default: `2`)
- `ORCA_TIMING_METRICS`: emit per-run timing/token metrics to `metrics.jsonl` (`1` default)
- `ORCA_COMPACT_SUMMARY`: emit per-run summary markdown and capture final agent message when possible (`1` default)
- `SESSION_PREFIX`: tmux session prefix (default: `bb-agent`)
- `PROMPT_TEMPLATE`: path to prompt template (default: `scripts/orca/AGENT_PROMPT.md`)
- `AGENT_COMMAND`: full command used for each agent pass (default: `codex exec ...`)
- `ORCA_LOCK_SCOPE`: default scope used by `with-lock.sh` (default: `merge`)
- `ORCA_LOCK_TIMEOUT_SECONDS`: default timeout used by `with-lock.sh` (default: `120`)
- `ORCA_STATUS_RUN_AUDIT`: include `audit-consistency` when running `status` (`0` default, `1` to enable)
