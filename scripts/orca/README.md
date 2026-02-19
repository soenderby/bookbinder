# Orca Scripts

This directory contains the Orca multi-agent orchestration scripts.

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
