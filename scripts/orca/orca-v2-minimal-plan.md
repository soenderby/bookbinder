# Orca-v2 Minimal Plan

## Intent

Orca-v2 is a reset toward a thinner and more durable orchestration layer for autonomous development agents. The tool should provide reliable execution mechanics for multi-agent loops, but it should not embed workflow judgment that can be handled by increasingly capable models.

The practical goal is to keep operators productive while reducing script complexity and hidden policy. Orca should remain useful as an execution harness: start loops, isolate worktrees, persist logs, collect metrics, and expose safe coordination primitives.

In this model, agents own decisions and outcomes. They choose and claim work, decide issue state transitions, and perform merge operations themselves, while the script provides a shared lock primitive to prevent unsafe concurrent integration.

## Design Principles

1. Transport over cognition: script code handles plumbing and observability, not task policy.
2. Explicit primitives over implicit heuristics: expose capabilities such as locks and run metadata, avoid hardcoded behavioral rules.
3. Agent-owned lifecycle: issue open/close and merge responsibility live with the agent, not loop logic.
4. Operational clarity: preserve high-quality logs and metrics so failures and throughput remain visible without embedding policy in the framework.

## 1) Goals

1. Keep `orca` as transport/orchestration only.
2. Keep loop execution in scripts.
3. Keep logs and metrics.
4. Move merge responsibility to agents.
5. Move issue open/close responsibility fully to agents.
6. Keep a global lock primitive available for agents during merge/push to shared targets.
7. Let agents capture discoveries (bugs, improvements, tooling ideas) through beads tasks and lightweight discovery notes.

## 2) Non-Goals (v2)

1. No scripted policy for parent/child issue rules.
2. No scripted auto-reopen/auto-close issue behavior.
3. No scripted merge decision logic.
4. No scripted "forbidden command" policing.

## 3) Runtime Contract (v2)

1. Loop script launches one agent run per iteration with a generic prompt (no pre-selected issue ID).
2. Agent must choose/claim/execute/close (or leave open) a single issue per run.
3. Agent must perform merge itself and use lock helper around merge/push critical section.
4. Agent emits a small structured run summary (JSON) so loop can log metrics without interpreting policy.
5. Agent controls queue-empty behavior and can request loop shutdown with a structured reason message.
6. Agent may record discoveries during a run by:
   - creating follow-up beads linked to the current issue
   - appending short notes to a per-agent discovery file

## 4) Minimal Command Surface

1. Keep: `setup-worktrees`, `start`, `stop`, `status`.
2. Add: `with-lock` helper (transport primitive using `flock` on shared lock file).
3. Optional keep: `audit-consistency` as standalone report only (not part of loop control flow).

## 5) Implementation Phases

### Phase A: Introduce v2 primitives

1. Add `scripts/orca/with-lock.sh`.
2. Define lock file at git common dir (for all worktrees), e.g. `<git-common-dir>/orca-global.lock`.
3. Update docs with required agent merge pattern using `with-lock`.

### Phase B: Simplify loop engine

1. Replace `agent-loop.sh` behavior with a minimal loop:
   - run agent once
   - capture exit code + duration + summary
   - continue until `--runs` or agent-requested stop
2. Remove loop-owned claim/open/close/merge/reopen logic.

### Phase C: Prompt + summary contract

1. Rewrite `scripts/orca/AGENT_PROMPT.md`:
   - agent selects and claims work
   - agent owns issue transitions
   - agent owns merge and must use lock helper
   - agent captures discoveries as follow-up beads when appropriate
   - agent appends discovery notes to per-agent file
   - agent writes run summary JSON to provided path
2. Add summary schema (minimal):
   - `issue_id`
   - `result` (`completed|blocked|no_work|failed`)
   - `issue_status`
   - `merged`
   - `discovery_ids`
   - `discovery_count`
   - `loop_action` (`continue|stop`)
   - `loop_action_reason`
   - `notes`

### Phase D: Preserve observability

1. Keep session log + per-run log files.
2. Keep `agent-logs/metrics.jsonl`.
3. Add per-agent append-only discovery logs under `agent-logs/discoveries/<agent-name>.md`.
4. Metrics become transport-only:
   - timestamp
   - agent
   - run number
   - duration
   - exit code
   - parsed summary fields (if present)

### Phase E: Decommission v1 complexity

1. Remove/retire code paths for:
   - merge-after-run orchestration in loop
   - parent/child leaf filtering in loop
   - close-guard enforcement
   - minimal-landing detection/enforcement
   - sync retry policy branches tied to issue state mutation
2. Replace v1 immediately (no long-lived dual-mode maintenance).

## 6) Acceptance Criteria

1. Two-agent loop can run continuously with no scripted issue state changes.
2. Agents can safely merge concurrently by using shared lock helper.
3. Logs and metrics are still generated per run.
4. Loop remains stable even when agent run fails (records failure and continues/stops per run mode).
5. Code size and branch complexity of `agent-loop.sh` are substantially reduced.
6. Agent can stop loop intentionally with a machine-readable reason that is also visible in logs.
7. Discovery tasks can be created and linked by agents, and discovery notes are captured in per-agent append files.

## 7) Decisions Captured

1. Queue-empty detection is agent-level. Agent may return `result=no_work` and request `loop_action=stop` with `loop_action_reason`.
2. `with-lock` will support lock scopes plus sensible defaults:
   - default scope: `merge`
   - default timeout for lock acquisition
   - optional scope override for future coordination needs without adding new orchestration logic
3. v2 replaces v1 immediately.
4. Discovery support in v2 is lightweight:
   - include `discovery_ids` and `discovery_count` in summary JSON
   - use per-agent append discovery files (not shared markdown editing)
