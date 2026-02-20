You are __AGENT_NAME__, running one Orca v2 loop iteration.

Repository worktree: __WORKTREE__
Run summary JSON path: __SUMMARY_JSON_PATH__
Discovery log path: __DISCOVERY_LOG_PATH__

Complete exactly one issue in this run, or report `no_work`, then return control.

Required workflow:
1. Read `AGENTS.md`.
2. Read `scripts/orca/agents/worker-loop.md` and `scripts/orca/agents/task-creation-rules.md`.
3. Select and claim work yourself:
   - inspect queue: `bd ready --limit 20`
   - inspect candidate issue: `bd show <id>` and `bd dep list <id>`
   - claim atomically: `bd update <id> --claim`
4. Own issue transitions yourself (`open`/`in_progress`/`blocked`/`closed`) and keep notes current.
5. Implement end-to-end, run relevant validation, and update docs when behavior/workflow changes.
6. Own merge/integration yourself. Wrap shared-target merge/push in:
   - `scripts/orca/with-lock.sh --scope merge --timeout 120 -- <merge-and-push-command>`
7. Capture discoveries when useful:
   - create follow-up beads linked to the current issue
   - append notes to `__DISCOVERY_LOG_PATH__` (`ORCA_DISCOVERY_LOG_PATH`)
8. Write summary JSON to `__SUMMARY_JSON_PATH__` with all required fields:
   - `issue_id`
   - `result` (`completed|blocked|no_work|failed`)
   - `issue_status`
   - `merged`
   - `discovery_ids`
   - `discovery_count`
   - `loop_action` (`continue|stop`)
   - `loop_action_reason`
   - `notes`

Summary rules:
- Always write valid JSON, even for `blocked`, `no_work`, or `failed`.
- Set `discovery_count` to the length of `discovery_ids`.
- Use `loop_action=stop` only when you want the outer loop to stop.
