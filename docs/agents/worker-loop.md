# Parallel Agent Worker Loop

This document is the default operating procedure for any agent working in this repo.

## 1. Orientation (Always First)

Before claiming work, read:
1. `AGENTS.md`
2. `SPEC.md`
3. `sample-pdfs/expected_output/manifest.json`

Then pull recent project context from beads:

```bash
bd ready --limit 20
bd list --status closed --sort closed --reverse --limit 10
```

If there is a likely candidate task, inspect details:

```bash
bd show <id>
bd dep list <id>
```

## 2. Claim an Unblocked Task

Claim atomically (required for parallel execution safety):

```bash
bd update <id> --claim
```

If claim fails, pick another ready task. Do not work unclaimed issues.

Rules:
1. One active issue per agent.
2. Do not edit files outside your claimed issue scope.
3. If you discover a cross-issue dependency, create/update beads before coding further.

## 3. Implement the Task

Execution checklist:
1. Re-state acceptance criteria from `bd show <id>`.
2. Implement minimal change set that satisfies criteria.
3. Keep commits scoped to the claimed issue only.
4. Run relevant quality gates (tests/lint/build) for touched areas.

Minimum validation expectation:
1. Run targeted tests first.
2. Run broader checks if the change affects shared/core behavior.
3. Record exact commands and outcomes in your handoff note.

## 4. Capture Follow-on Work (Mandatory)

While implementing, create new beads for discovered work such as:
1. edge cases not handled in current scope
2. bugs uncovered but not fixed here
3. refactors needed to reduce risk
4. missing docs/tests/reviews

Create follow-up issue:

```bash
bd create "<title>" --type task --priority 2 --description "<what/why>" --deps discovered-from:<current-id>
```

If follow-up blocks your current issue, link dependency explicitly:

```bash
bd dep <new-id> --blocks <current-id>
```

## 5. Documentation Requirements

Add/update docs when behavior, interface, or workflow changes.

Typical doc targets:
1. `SPEC.md` for scope/acceptance updates
2. `docs/agents/*.md` for process changes
3. feature-specific notes if new operational steps are introduced

## 6. Close Out the Issue

When implementation and checks are complete:

```bash
bd close <id> --reason "completed"
```

When running under Orca persistent loop mode, follow the prompt override: do not close directly, because the outer loop closes only after merge to `main` succeeds.

If not complete, leave issue `in_progress` and append clear notes:

```bash
bd update <id> --append-notes "<status, blockers, next steps>"
```

## 7. Session End (Landing the Plane)

Follow `AGENTS.md` exactly. Minimum sequence:

```bash
git pull --rebase
bd sync
git push
git status
```

Work is not complete until push succeeds and status confirms sync with origin.
