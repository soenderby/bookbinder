# Agent Swarm Operator Runbook

This guide is for a human operator running the persistent multi-worktree agent swarm.

## 1. Purpose

Use the swarm to drain ready unblocked beads tasks in parallel, or run bounded batches.

Each loop:
1. reads ready work from beads
2. skips ready parent issues that still have open child tasks
3. claims exactly one issue atomically
4. runs one autonomous agent pass for that issue
5. merges the worker branch into `main` using a global merge lock
6. closes the issue only after merge succeeds and all child tasks are closed
7. continues while work exists and exits when no ready tasks remain (or run limit is reached)

## 2. Prerequisites

From the machine running the swarm, ensure these commands work:

```bash
git --version
bd --version
tmux -V
jq --version
flock --version
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
./bb orca start 2 --continuous

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
./bb orca start 2 --continuous

# Verify health
./bb orca status
./bb orca audit-consistency
```

If sessions already exist, `./bb orca start` leaves them running.

To run a bounded batch and stop automatically:

```bash
./bb orca start 2 --runs 5
```

`--runs` applies per agent session (`--runs 5` with 2 agents allows up to 10 issue runs total).

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

# tail newest log file
tail -f "$(ls -1t agent-logs | head -n 1 | sed 's#^#agent-logs/#')"

# check compact run summaries
ls -1t agent-logs/*-summary.md | head

# check latest metrics rows
tail -n 10 agent-logs/metrics.jsonl
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
./bb orca start 3 --continuous
./bb orca status
```

To reduce active loops, stop all and restart with the desired count:

```bash
./bb orca stop
./bb orca start 2 --continuous
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
./bb orca start 2 --continuous
```

If a specific agent keeps failing:
1. inspect its log file in `agent-logs/`
2. attach to its tmux session
3. verify CLI auth and network
4. restart swarm

## 9. Common Failures and Fixes

1. `no ready beads; exiting loop` in logs:
- This is normal when the queue is empty.
- Start the swarm again after creating or un-blocking tasks in beads.

2. `could not claim <id>` in logs:
- Normal race condition between agents.
- Another loop claimed the issue first.

3. agent run fails after claim:
- Loop should set the issue back to `open` automatically, clear assignee, and append a failure note.
- Verify with:
```bash
bd show <id>
```

4. merge step fails (conflict/push failure):
- Loop returns the issue to `open` with a merge failure note and stops that worker loop.
- Resolve conflict on the source branch, push, then restart swarm:
```bash
./bb orca start 2 --continuous
```

5. push rejected from a worktree branch:
- Set upstream once in that worktree:
```bash
git push -u origin $(git branch --show-current)
```

6. agent CLI command fails immediately:
- Re-check `codex --version` and authentication.
- Confirm `AGENT_COMMAND` override is valid if used.

## 9.1 Minimal loop closeout policy

Per-issue runs in Orca are expected to use minimal closeout:
1. commit + push + issue notes/status updates
2. avoid `git pull --rebase`, `bd sync`, and `git remote prune origin` inside each run
3. let the outer loop handle sync/integration

Current behavior:
1. Orca logs warnings when these forbidden closeout commands are detected in run logs.
2. This is warning-only by default.

Planned future change (not active yet):
1. Switch to strict enforcement by setting `ORCA_ENFORCE_MINIMAL_LANDING=1`.
2. In strict mode, runs with forbidden closeout commands will be failed and the issue returned to `open`.

## 10. Operator Safety Rules

1. Do not manually edit files inside multiple worktrees at once unless intentional.
2. Prefer letting agents own changes in their assigned worktree.
3. Keep beads as the source of truth for task state and dependencies.
4. Do not run destructive git commands (`reset --hard`, force delete) during active swarm runs.

## 11. Useful Command Cheat Sheet

```bash
# setup/start/stop/status/audit
./bb orca setup-worktrees 2
./bb orca start 2 --continuous
./bb orca stop
./bb orca status
./bb orca audit-consistency

# tmux
tmux ls
tmux attach -t bb-agent-1

# beads
bd ready --limit 20
bd list --status in_progress --limit 50
bd list --status closed --sort closed --reverse --limit 20
```
