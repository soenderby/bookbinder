# Agent Swarm Operator Runbook

This guide is for a human operator running the persistent multi-worktree agent swarm.

## 1. Purpose

Use the swarm to continuously pick and execute unblocked beads tasks in parallel.

Each loop:
1. reads ready work from beads
2. claims exactly one issue atomically
3. runs one autonomous agent pass for that issue
4. repeats forever

## 2. Prerequisites

From the machine running the swarm, ensure these commands work:

```bash
git --version
bd --version
tmux -V
jq --version
codex --version
```

Also ensure:
1. You are logged into the coding agent CLI (`codex login` if needed).
2. The repo has push access to origin.
3. There are open, unblocked beads tasks (`bd ready`).

## 3. First-Time Setup

From repo root:

```bash
# Create persistent worktrees for 2 agents
./bb orca setup-worktrees 2

# Start the loops in tmux sessions
./bb orca start 2

# Inspect status
./bb orca status
```

Expected tmux session names:
1. `bb-agent-1`
2. `bb-agent-2`

## 4. Daily Start Procedure

Run this at the start of an operator session:

```bash
# Update main checkout first
git pull --rebase
bd sync

# Start or resume loops
./bb orca start 2

# Verify health
./bb orca status
```

If sessions already exist, `./bb orca start` leaves them running.

## 5. Live Operations

## 5.1 Watch queue and activity

```bash
bd ready --limit 20
bd list --status in_progress --limit 50
bd list --status closed --sort closed --reverse --limit 20
```

## 5.2 Check loop logs

```bash
ls -lt agent-logs

# tail one agent
tail -f agent-logs/agent-1.log
```

## 5.3 Attach to a running tmux session

```bash
tmux attach -t bb-agent-1
# detach with: Ctrl+b then d
```

## 5.4 Inspect worktrees

```bash
git worktree list
```

## 6. Scaling Up or Down

To run 3 agents instead of 2:

```bash
./bb orca start 3
./bb orca status
```

To reduce active loops, stop all and restart with the desired count:

```bash
./bb orca stop
./bb orca start 2
```

Worktrees remain persistent unless explicitly removed.

## 7. Stop Procedure

For controlled shutdown:

```bash
./bb orca stop
./bb orca status
```

Before ending the day, verify no required manual intervention remains:
1. blocked/in-progress issues have clear notes
2. no critical failing loops in logs
3. repo state is pushed and up to date (if you made manual changes)

## 8. Restart and Recovery

If loops wedge or misbehave:

```bash
./bb orca stop
./bb orca start 2
```

If a specific agent keeps failing:
1. inspect its log file in `agent-logs/`
2. attach to its tmux session
3. verify CLI auth and network
4. restart swarm

## 9. Common Failures and Fixes

1. `no ready beads` repeated in logs:
- This is normal when queue is empty.
- Create or un-block tasks in beads.

2. `could not claim <id>` in logs:
- Normal race condition between agents.
- Another loop claimed the issue first.

3. agent run fails after claim:
- Loop should set the issue back to `open` automatically, clear assignee, and append a failure note.
- Verify with:
```bash
bd show <id>
```

4. push rejected from a worktree branch:
- Set upstream once in that worktree:
```bash
git push -u origin $(git branch --show-current)
```

5. agent CLI command fails immediately:
- Re-check `codex --version` and authentication.
- Confirm `AGENT_COMMAND` override is valid if used.

## 10. Operator Safety Rules

1. Do not manually edit files inside multiple worktrees at once unless intentional.
2. Prefer letting agents own changes in their assigned worktree.
3. Keep beads as the source of truth for task state and dependencies.
4. Do not run destructive git commands (`reset --hard`, force delete) during active swarm runs.

## 11. Useful Command Cheat Sheet

```bash
# setup/start/stop/status
./bb orca setup-worktrees 2
./bb orca start 2
./bb orca stop
./bb orca status

# tmux
tmux ls
tmux attach -t bb-agent-1

# beads
bd ready --limit 20
bd list --status in_progress --limit 50
bd list --status closed --sort closed --reverse --limit 20
```
