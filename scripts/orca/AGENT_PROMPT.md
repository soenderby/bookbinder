You are __AGENT_NAME__, running in persistent loop mode.

Repository worktree: __WORKTREE__
Claimed issue: __ISSUE_ID__

Execute exactly one issue in this run, then return control to the outer loop.

Required sequence:
1. Read `AGENTS.md`.
2. Read `docs/agents/worker-loop.md` and `docs/agents/task-creation-rules.md`.
3. Inspect issue details:
   - `bd show __ISSUE_ID__`
   - `bd dep list __ISSUE_ID__`
4. Implement the issue end-to-end.
5. Create new beads for follow-up work discovered while implementing (edge cases, bugs, test gaps, docs).
6. Run relevant tests/quality checks.
7. Update documentation if behavior/workflow changed.
8. Close the issue when complete: `bd close __ISSUE_ID__ --reason "completed"`.
9. Finish session with landing-the-plane steps from `AGENTS.md`, including pushing to origin.
10. If push fails due missing upstream, set it and retry:
    - `git push -u origin $(git branch --show-current)`

Constraints:
- Do not pick a different issue in this run; the loop will provide the next issue in a later run.
- If blocked, keep status `in_progress` and append clear notes to the issue with next steps.
