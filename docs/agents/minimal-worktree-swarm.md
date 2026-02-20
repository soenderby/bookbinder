# Minimal Worktree Swarm Setup

This is a minimal starting point for running multiple agent loops in parallel.

## What This Setup Provides

1. Persistent git worktrees (`worktrees/agent-1`, `worktrees/agent-2`, ...)
2. One loop process per worktree (inside tmux sessions)
3. Beads-based coordination (`bd ready` + atomic `bd update --claim`)
4. Basic operational scripts (setup/start/stop/status)

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

# 4) Stop all loops
./bb orca stop
```

## How Loop Coordination Works

Each loop:
1. syncs git/beads
2. asks for unblocked work (`bd ready --json`)
3. attempts atomic claim (`bd update <id> --claim`)
4. runs one autonomous agent pass for that issue
5. serializes merge into `main` after a successful run
6. closes the issue only after merge succeeds
7. continues while work exists; exits when queue is empty (or run limit is reached)

Only one loop can claim a given issue, which prevents duplicate work.

If an agent run fails after claiming an issue, the loop automatically moves that issue back to `open`, clears assignee, and appends a failure note.
If merge fails, the loop reopens the issue for retry and stops that worker loop for manual intervention.

## Configuration Knobs

Environment variables:

1. `AGENT_MODEL` (default: `gpt-5.3-codex`)
2. `AGENT_COMMAND` (default uses `codex exec --dangerously-bypass-approvals-and-sandbox`)
3. `AGENT_REASONING_LEVEL` (sets `model_reasoning_effort` for default codex command)
4. `SESSION_PREFIX` (default: `bb-agent`)
5. `PROMPT_TEMPLATE` (default: `scripts/orca/AGENT_PROMPT.md`)
6. `MAX_RUNS` (default: `0`, where `0` means unbounded runs until queue empty)
7. `ORCA_MERGE_REMOTE` (default: `origin`)
8. `ORCA_MERGE_TARGET_BRANCH` (default: `main`)
9. `ORCA_MERGE_LOCK_TIMEOUT_SECONDS` (default: `120`)
10. `ORCA_MERGE_MAX_ATTEMPTS` (default: `3`)

Example:

```bash
AGENT_MODEL=gpt-5.1 SESSION_PREFIX=swarm ./bb orca start 3 --runs 10

# Set reasoning effort for the default codex command
AGENT_REASONING_LEVEL=high ./bb orca start 2 --continuous
```

`start.sh` explicitly passes these values into each tmux session, so operator-selected values are consistently used by workers.

## Notes

1. This is intentionally minimal and local-first.
2. Logs are written to `agent-logs/`.
3. Worktree directories and logs are gitignored.
4. First push from a new worktree branch may require upstream setup:
   - `git push -u origin $(git branch --show-current)`
5. Merge integration is serialized by a global lock, so only one worker merges at a time.
