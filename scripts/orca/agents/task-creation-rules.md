# Beads Task Creation and Triage Rules

Use this when creating new beads during implementation.

## 1. Create the Right Issue Type

1. `bug`: incorrect behavior, crashes, regressions
2. `task`: implementation work with clear scope
3. `chore`: maintenance/tooling/housekeeping
4. `feature`: net-new user-facing capability
5. `decision`: architecture/process decision record needed

## 2. Priority Guide

1. `P0`: release-blocking, data loss, broken core flow
2. `P1`: major behavior gap, high user impact
3. `P2`: normal planned work (default)
4. `P3`: improvement or low urgency
5. `P4`: backlog/idea parking

## 3. Required Fields

Every new bead must include:
1. clear title (outcome-oriented)
2. short description with context and expected behavior
3. dependency link to parent/source issue when discovered during work
4. acceptance criteria (bullet list, testable)

Example:

```bash
bd create "Handle encrypted PDF upload errors" \
  --type bug \
  --priority 1 \
  --description "Encrypted PDFs currently fail without actionable error messaging in upload flow." \
  --acceptance "Returns clear user-facing error; includes recovery hint; adds regression test." \
  --deps discovered-from:bd-123
```

## 4. Dependency Rules

1. If issue B must finish before issue A can complete, set `B blocks A`.
2. If issue is merely related but not blocking, use `discovered-from` dependency.
3. Avoid hidden dependencies. Model them explicitly in beads.

Commands:

```bash
bd dep <blocker-id> --blocks <blocked-id>
bd dep list <id>
```

## 5. Parallel Safety Rules

1. Prefer tasks with minimal file overlap.
2. If overlap is unavoidable, split work into explicit subtasks with dependencies.
3. Do not silently continue if another agent has already claimed overlapping scope.

## 6. Definition of Ready (for new tasks)

A task is ready when:
1. scope is clear and bounded
2. dependencies are satisfied or explicitly modeled
3. acceptance criteria are testable
4. owner can run without additional clarification
