# Orca Scripts

This directory contains the Orca multi-agent orchestration scripts.

## Prerequisites

- `git` (worktree support)
- `tmux` (agent sessions)
- `bd` CLI (task queue and updates)
- `jq` (ready queue JSON parsing)
- `codex` CLI (default `AGENT_COMMAND`)

## Entrypoints

- Preferred: `./bb orca <command> [args]`
- Direct: `scripts/orca/orca.sh <command> [args]`

## Commands

- `start [count] [--runs N|--continuous]`
- `stop`
- `status`
- `setup-worktrees [count]`

## Files

- `orca.sh`: command dispatcher
- `setup-worktrees.sh`: creates and verifies persistent agent worktrees
- `start.sh`: launches tmux-backed agent loops
- `agent-loop.sh`: per-agent loop for claiming and processing beads tasks
- `status.sh`: displays sessions, worktrees, and recent activity
- `stop.sh`: stops active agent sessions
- `AGENT_PROMPT.md`: prompt template used by `agent-loop.sh`

## Runtime knobs

- `MAX_RUNS`: number of issue runs per loop (`0` means unbounded until queue empty)
- `READY_MAX_ATTEMPTS`: retries for `bd ready --json` polling (default: `5`)
- `READY_RETRY_SECONDS`: seconds between ready polling retries (default: `3`)

## TODO
In no particular order:
 - A/B testing prompts
 - Agent loop metrics in sqlite database
 - Figure out how to sync worktrees
 - Agent loop handoff
 - Sharing or storing lessons learned from run
 - Streamline loop prompt (likely tied to A/B testing)
