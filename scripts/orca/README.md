# Orca Scripts

This directory contains the Orca multi-agent orchestration scripts.

Orca uses transport-focused loop orchestration while agents own task policy and decisions.

## Documentation

Orca intentionally keeps documentation to three markdown files in this directory:

1. `README.md` (this file): technical reference and command/runtime details
2. `AGENT_PROMPT.md`: single consolidated instruction contract for loop agents
3. `OPERATOR_GUIDE.md`: human operator guide, including intent and design principles

## Entrypoints

- Preferred: `./bb orca <command> [args]`
- Direct: `scripts/orca/orca.sh <command> [args]`

## Commands

- `start [count] [--runs N|--continuous] [--reasoning-level LEVEL]`
- `stop`
- `status`
- `setup-worktrees [count]`
- `with-lock [--scope NAME] [--timeout SECONDS] -- <command> [args...]`
- `merge-primary-main [--repo PATH] [--source-branch NAME] [--target-branch NAME] [--remote NAME]`

Helper script (direct invocation):

- `scripts/orca/with-lock.sh [--scope NAME] [--timeout SECONDS] -- <command> [args...]`
- `scripts/orca/merge-primary-main.sh [--repo PATH] [--source-branch NAME] [--target-branch NAME] [--remote NAME]`

## TODO

In no particular order:

1. A/B testing prompts
2. Agent loop metrics in sqlite database
3. Agent loop handoff
4. Sharing or storing lessons learned from run
5. Streamline loop prompt (likely tied to A/B testing)

## Architecture Overview

Orca is a `tmux`-backed multi-agent loop with one persistent git worktree per agent:

1. `setup-worktrees.sh` ensures `worktrees/agent-N` and branch `swarm/agent-N` exist.
2. `start.sh` launches one tmux session per agent and injects runtime env.
3. `agent-loop.sh` runs one agent pass per iteration, writes per-run logs/metrics, and parses the agent summary JSON.
4. `AGENT_PROMPT.md` defines the agent contract for issue lifecycle, merge, discovery, and summary output.
5. `with-lock.sh` provides a shared lock primitive for agent-owned merge/push critical sections.
6. `status.sh` provides health and observability snapshots.
7. `stop.sh` terminates active sessions.

## File Roles

- `orca.sh`: command dispatcher
- `setup-worktrees.sh`: creates and verifies persistent agent worktrees
- `start.sh`: launches tmux-backed agent loops
- `agent-loop.sh`: per-agent run loop that executes the prompt, captures run artifacts, and records summary/metrics
- `with-lock.sh`: scoped lock wrapper for commands that must serialize shared git integration operations
- `merge-primary-main.sh`: deterministic preflight + merge/push helper for integrating source branch into primary repo target branch
- `status.sh`: displays sessions, worktrees, queue snapshots, logs, and metrics
- `stop.sh`: stops active agent sessions
- `AGENT_PROMPT.md`: agent instruction contract used by `agent-loop.sh`
- `OPERATOR_GUIDE.md`: human operator playbook and design rationale

## Lock Pattern (`with-lock.sh`)

For agent-owned integration flows, wrap merge/push critical sections in `with-lock.sh` so only one writer updates shared targets at a time.

```bash
scripts/orca/with-lock.sh --scope merge --timeout 120 -- \
  bash scripts/orca/merge-primary-main.sh
```

Notes:

1. default scope is `merge`
2. default lock file for `merge` scope is `<git-common-dir>/orca-global.lock`
3. non-default scopes use `<git-common-dir>/orca-global-<scope>.lock`
4. `merge-primary-main.sh` fails fast if `ORCA_PRIMARY_REPO` is dirty to avoid nondeterministic checkout/merge behavior
5. keep all shared-target write steps in one lock invocation

## Run Summary JSON Contract

Agents must write a JSON object to `ORCA_RUN_SUMMARY_PATH` (also provided in prompt placeholder `__SUMMARY_JSON_PATH__`) with these fields:

| Field | Type | Required | Allowed values / notes |
| --- | --- | --- | --- |
| `issue_id` | string | yes | Issue handled in this run. Use empty string when no issue was claimed. |
| `result` | string | yes | `completed`, `blocked`, `no_work`, `failed` |
| `issue_status` | string | yes | Issue status after this run, or empty for `no_work`. |
| `merged` | boolean | yes | `true` only when merge/integration completed in this run. |
| `discovery_ids` | array[string] | yes | Follow-up bead IDs created in this run. Use `[]` when none. |
| `discovery_count` | integer | yes | Must equal `discovery_ids` length. |
| `loop_action` | string | yes | `continue` or `stop` |
| `loop_action_reason` | string | yes | Reason for selected `loop_action`; empty string allowed. |
| `notes` | string | yes | Short run note/handoff summary. |

## Core Loop Logic (`agent-loop.sh`)

Each iteration:

1. creates run artifacts (`*.log`, `*-summary.json`, optional `*-summary.md`)
2. renders `AGENT_PROMPT.md` placeholders (agent/worktree/summary/discovery paths)
3. executes agent command once
4. parses summary JSON when present
5. appends metrics row to `agent-logs/metrics.jsonl`
6. continues until `MAX_RUNS` or agent requests stop via `loop_action=stop`

## Validation and Safety Checks

### `start.sh`

Startup checks:

1. required commands: `git`, `tmux`, `bd`, `jq`, `flock`, and `AGENT_COMMAND` binary
2. `count` positive integer
3. `MAX_RUNS` non-negative integer
4. `RUN_SLEEP_SECONDS` non-negative integer
5. `ORCA_TIMING_METRICS` and `ORCA_COMPACT_SUMMARY` are `0|1`
6. `ORCA_LOCK_SCOPE` matches `[A-Za-z0-9._-]+`
7. `ORCA_LOCK_TIMEOUT_SECONDS` positive integer
8. `AGENT_REASONING_LEVEL` (if set) matches `[A-Za-z0-9._-]+`
9. `PROMPT_TEMPLATE` exists

Behavior:

1. default model `gpt-5.3-codex`
2. optional reasoning level is appended to default command
3. idempotent start for existing sessions
4. invokes `setup-worktrees.sh` before launching sessions
5. injects runtime knobs into each session

### `agent-loop.sh`

Input/env validation:

1. `WORKTREE` required and must be a valid git worktree
2. `MAX_RUNS` non-negative integer
3. `RUN_SLEEP_SECONDS` non-negative integer
4. `ORCA_TIMING_METRICS` and `ORCA_COMPACT_SUMMARY` are `0|1`
5. `AGENT_REASONING_LEVEL` format validation when set
6. `PROMPT_TEMPLATE` exists

Signal handling:

1. traps `INT`, `TERM`, `EXIT`
2. logs shutdown signals
3. avoids re-entrant cleanup

### `status.sh`

1. prints tmux sessions for `SESSION_PREFIX`
2. prints git worktrees
3. prints queue snapshots (`in_progress`, `closed`, `ready`)
4. lists recent logs and summaries
5. prints latest metrics rows
6. does not run repository consistency checks (keeps status minimal)

## Error Handling Model

Orca handles transport/observability errors. Agents handle workflow policy.

1. startup hard-stop failures: invalid config/env/worktree/prompt path
2. run-level failures: non-zero agent exit, missing/invalid summary JSON, metrics append failure
3. controlled stop: run limit reached or agent summary requests stop

## Logs and Traceability

Session logs:

`agent-logs/<agent-name>-<session-id>.log`

Per-run logs:

`agent-logs/<agent-name>-<session-id>-run-<n>-<timestamp>.log`

Per-run summary JSON:

`agent-logs/<agent-name>-<session-id>-run-<n>-<timestamp>-summary.json`

Per-run compact summary markdown:

`agent-logs/<agent-name>-<session-id>-run-<n>-<timestamp>-summary.md`

Metrics stream:

`agent-logs/metrics.jsonl`

Per-agent discovery notes:

`agent-logs/discoveries/<agent-name>.md`

Discovery path is injected to agents as:

- prompt placeholders: `__DISCOVERY_LOG_PATH__`, `__AGENT_DISCOVERY_LOG_PATH__`
- env vars: `ORCA_DISCOVERY_LOG_PATH`, `ORCA_AGENT_DISCOVERY_LOG_PATH`

## Runtime Knobs

- `MAX_RUNS`: issue runs per loop (`0` means unbounded unless agent requests stop)
- `AGENT_MODEL`: default model for default command
- `AGENT_REASONING_LEVEL`: optional reasoning effort for default command
- `RUN_SLEEP_SECONDS`: sleep between iterations (default `2`)
- `ORCA_TIMING_METRICS`: emit metrics rows (`1` default)
- `ORCA_COMPACT_SUMMARY`: emit markdown summaries (`1` default)
- `SESSION_PREFIX`: tmux session prefix (`bb-agent` default)
- `PROMPT_TEMPLATE`: prompt template path (`scripts/orca/AGENT_PROMPT.md` default)
- `AGENT_COMMAND`: full command for each run
- `ORCA_LOCK_SCOPE`: default lock scope for `with-lock.sh` (`merge`)
- `ORCA_LOCK_TIMEOUT_SECONDS`: lock timeout seconds (default `120`)
