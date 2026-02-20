# Minimal Worktree Swarm Setup

This is the current Orca-v2 setup for running multiple agent loops in parallel.

## What This Setup Provides

1. Persistent git worktrees (`worktrees/agent-1`, `worktrees/agent-2`, ...)
2. One loop process per worktree (inside tmux sessions)
3. Agent-owned task lifecycle (`bd ready`, `bd update --claim`, issue transitions, merge/push, close decisions)
4. Basic operational scripts (`setup-worktrees`, `start`, `stop`, `status`) plus optional `audit-consistency`

Scripts are in `scripts/orca/`, with `./bb orca` as the preferred entrypoint.

## Quick Start

From repo root:

```bash
# 1) Create two persistent worktrees
./bb orca setup-worktrees 2

# 2) Start two continuous agent loops
./bb orca start 2 --continuous

# Optional: run a bounded batch (each loop exits after 5 issue runs)
./bb orca start 2 --runs 5

# 3) Check swarm status
./bb orca status

# Optional: run explicit tracker consistency audit report
./bb orca audit-consistency

# 4) Stop all loops
./bb orca stop
```

## How Loop Coordination Works (v2)

Each loop:
1. runs one autonomous agent pass per iteration
2. gives the agent prompt context, run artifact paths, and discovery log path
3. lets the agent select and claim work directly in beads
4. lets the agent own issue state changes and merge/push (using `scripts/orca/with-lock.sh` for shared integration writes)
5. parses run summary JSON and appends transport/observability metrics
6. continues until `MAX_RUNS` is reached or the agent summary requests `loop_action=stop`

The loop does not do parent/child filtering, loop-owned merge orchestration, loop-owned close guards, or issue-state retry/reopen policy.

## Configuration Knobs

Environment variables:

1. `AGENT_MODEL` (default: `gpt-5.3-codex`)
2. `AGENT_COMMAND` (default uses `codex exec --dangerously-bypass-approvals-and-sandbox`)
3. `AGENT_REASONING_LEVEL` (sets `model_reasoning_effort` for default codex command)
4. `SESSION_PREFIX` (default: `bb-agent`)
5. `PROMPT_TEMPLATE` (default: `scripts/orca/AGENT_PROMPT.md`)
6. `MAX_RUNS` (default: `0`, unbounded until agent requests stop)
7. `RUN_SLEEP_SECONDS` (default: `2`)
8. `ORCA_TIMING_METRICS` (default: `1`, writes `agent-logs/metrics.jsonl`)
9. `ORCA_COMPACT_SUMMARY` (default: `1`, writes `*-summary.md` files)
10. `ORCA_LOCK_SCOPE` (default: `merge`)
11. `ORCA_LOCK_TIMEOUT_SECONDS` (default: `120`)

Example:

```bash
AGENT_MODEL=gpt-5.1 SESSION_PREFIX=swarm ./bb orca start 3 --runs 10

# Set reasoning effort for the default codex command
AGENT_REASONING_LEVEL=high ./bb orca start 2 --continuous
```

`start.sh` explicitly injects these values into each tmux worker session.

## Notes

1. Orca-v2 is the active path.
2. Logs are written to `agent-logs/`.
3. Worktree directories and logs are gitignored.
4. First push from a new worktree branch may require upstream setup:
   - `git push -u origin $(git branch --show-current)`
5. `audit-consistency` remains available as a standalone optional report command.
