# Agent Swarm Operator Runbook

This guide is for a human operator running the persistent multi-worktree Orca-v2 swarm.

## 1. Purpose

Use the swarm to drain ready unblocked beads tasks in parallel, or run bounded batches.

In Orca-v2, each loop is transport-only:
1. launch one agent run per iteration
2. capture logs/metrics/summary artifacts
3. continue until `--runs` limit or agent-requested stop

Task policy is agent-owned:
1. choose and claim work
2. perform issue transitions
3. merge/push (with `scripts/orca/with-lock.sh` around shared integration writes)
4. close or leave issues open

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

# Optional standalone consistency report
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

1. Loop exits after a run with summary `loop_action=stop`:
- Expected in v2 when the agent intentionally requests stop (for example `result=no_work`).
- Review the latest `*-summary.json` and `*-summary.md` for the reason, then restart when ready.

2. `could not claim <id>` appears in run logs:
- Normal race condition between agents.
- Agent should pick another ready issue in the next run.

3. Agent run fails after claim:
- Orca does not mutate issue state in v2.
- Inspect run logs and `bd show <id>`, then either resume agent work or update issue status manually.

4. Merge step fails (conflict/push failure):
- Merge/retry decisions are agent-owned in v2.
- Resolve branch state, add issue notes, and restart the swarm if needed.

5. Push rejected from a worktree branch:
- Set upstream once in that worktree:
```bash
git push -u origin $(git branch --show-current)
```

6. Agent CLI command fails immediately:
- Re-check `codex --version` and authentication.
- Confirm `AGENT_COMMAND` override is valid if used.

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
