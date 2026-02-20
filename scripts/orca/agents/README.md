# Agent Playbooks

Use these documents when running multi-agent parallel delivery in this repository.

## Files

1. `scripts/orca/agents/coordinator-loop.md`
- For the lead/coordinator assigning and monitoring parallel work.

2. `scripts/orca/agents/worker-loop.md`
- Default workflow for each implementation agent.

3. `scripts/orca/agents/task-creation-rules.md`
- Rules for creating follow-up beads and dependency links.

4. `scripts/orca/agents/handoff-template.md`
- Required handoff format at end of each worker session.

5. `scripts/orca/agents/minimal-worktree-swarm.md`
- Minimal scripts-first setup for persistent multi-worktree loops.

6. `scripts/orca/agents/swarm-operator-runbook.md`
- Human operator guide for start, monitor, scale, and stop procedures.

## Recommended Operating Model

1. Coordinator prepares and assigns unblocked work.
2. Each worker claims exactly one issue via `bd update <id> --claim`.
3. Workers execute `worker-loop.md` and create follow-up beads as needed.
4. Workers/agents merge completed work into `main` and close issues when complete.
5. Workers submit handoff using `handoff-template.md`.
6. Coordinator closes session per `AGENTS.md`.
