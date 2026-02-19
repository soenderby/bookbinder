# Minimal Worktree Swarm Setup

This is a minimal starting point for running multiple persistent agent loops in parallel.

## What This Setup Provides

1. Persistent git worktrees (`worktrees/agent-1`, `worktrees/agent-2`, ...)
2. One loop process per worktree (inside tmux sessions)
3. Beads-based coordination (`bd ready` + atomic `bd update --claim`)
4. Basic operational scripts (setup/start/stop/status)

Scripts are in `scripts/swarm/`, with `./bb orca` as the preferred entrypoint.

## Quick Start

From repo root:

```bash
# 1) Create two persistent worktrees
./bb orca setup-worktrees 2

# 2) Start two agent loops
./bb orca start 2

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
5. repeats forever

Only one loop can claim a given issue, which prevents duplicate work.

If an agent run fails after claiming an issue, the loop automatically moves that issue back to `open`, clears assignee, and appends a failure note.

## Configuration Knobs

Environment variables:

1. `AGENT_MODEL` (default: `gpt-5`)
2. `AGENT_COMMAND` (default uses `codex exec --dangerously-bypass-approvals-and-sandbox`)
3. `POLL_SECONDS` (default: `20`)
4. `SESSION_PREFIX` (default: `bb-agent`)
5. `PROMPT_TEMPLATE` (default: `scripts/swarm/AGENT_PROMPT.md`)

Example:

```bash
AGENT_MODEL=gpt-5.1 SESSION_PREFIX=swarm ./bb orca start 3
```

`start.sh` explicitly passes these values into each tmux session, so operator-selected values are consistently used by workers.

## Notes

1. This is intentionally minimal and local-first.
2. Logs are written to `agent-logs/`.
3. Worktree directories and logs are gitignored.
4. First push from a new worktree branch may require upstream setup:
   - `git push -u origin $(git branch --show-current)`
5. Improve incrementally: retries/backoff policies, health checks, merge queue, coordinator dashboard.
