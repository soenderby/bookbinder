# Parallel Agent Coordinator Loop

Use this when one lead agent/operator is coordinating multiple worker agents.

## 1. Prepare the Queue

1. Sync local state and review ready work:

```bash
bd ready --limit 50
bd list --status closed --sort closed --reverse --limit 20
```

2. Identify tasks that can run in parallel with low file overlap.
3. Split oversized tasks into smaller beads when needed.

## 2. Assign Work Safely

For each worker assignment:
1. Choose one unblocked issue.
2. Ensure no critical file overlap with already-assigned issues.
3. Have worker claim atomically:

```bash
bd update <id> --claim
```

4. Record assignment map (`issue -> agent`) in coordinator notes.

## 3. Monitor Progress

1. Check active in-progress work:

```bash
bd list --status in_progress --limit 100
```

2. If a worker finds new blocking work, require immediate bead creation + dependency link.
3. Rebalance workload when an issue gets blocked.

## 4. Enforce Handoffs

Each worker handoff must include:
1. issue status (`closed` or `in_progress`)
2. files changed
3. validation commands + outcomes
4. newly created follow-up beads
5. remaining risks

Use `scripts/orca/agents/handoff-template.md`.

## 5. Session Close

Before session ends:
1. Confirm all completed work has closed beads.
2. Confirm completed work was merged into `main` by the worker/agent flow.
3. Confirm all discovered follow-up work has beads.
4. Confirm all local commits are pushed.
5. Confirm `git status` is up to date with origin.

Reference: `AGENTS.md` landing-the-plane checklist is mandatory.
