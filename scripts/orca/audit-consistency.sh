#!/usr/bin/env bash
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "${ROOT}"

if ! command -v bd >/dev/null 2>&1; then
  echo "[audit] bd is required but not installed" >&2
  exit 2
fi

if ! command -v jq >/dev/null 2>&1; then
  echo "[audit] jq is required but not installed" >&2
  exit 2
fi

issues_json="$(bd list --all --limit 0 --json)"

declare -a closed_with_open_children=()
declare -a open_with_all_children_closed=()

analysis_json="$(
  jq '
    . as $issues
    | [
        $issues[] as $parent
        | $parent.id as $parent_id
        | [
            $issues[]
            | select(any((.dependencies // [])[]?; .type == "parent-child" and .depends_on_id == $parent_id))
            | { id, title, status }
          ] as $children
        | ($children | map(select(.status != "closed"))) as $open_children
        | select(($children | length) > 0)
        | {
            id: $parent_id,
            title: $parent.title,
            status: $parent.status,
            child_count: ($children | length),
            open_child_count: ($open_children | length),
            open_child_ids: ($open_children | map(.id))
          }
      ]
  ' <<<"${issues_json}"
)"

while IFS= read -r row; do
  [[ -z "${row}" ]] && continue
  closed_with_open_children+=("${row}")
done < <(
  jq -r '
    .[]
    | select(.status == "closed" and .open_child_count > 0)
    | "\(.id)|\(.title)|\(.open_child_count)|\(.open_child_ids | join(","))"
  ' <<<"${analysis_json}"
)

while IFS= read -r row; do
  [[ -z "${row}" ]] && continue
  open_with_all_children_closed+=("${row}")
done < <(
  jq -r '
    .[]
    | select(.status != "closed" and .open_child_count == 0)
    | "\(.id)|\(.title)|\(.child_count)"
  ' <<<"${analysis_json}"
)

echo "== Orca/Beads Consistency Audit =="
echo "repo: ${ROOT}"
echo

if [[ "${#closed_with_open_children[@]}" -eq 0 ]]; then
  echo "[ok] No closed issues with open child tasks."
else
  echo "[fail] Closed issues with open child tasks:"
  for row in "${closed_with_open_children[@]}"; do
    IFS='|' read -r issue_id title open_child_count open_child_ids <<<"${row}"
    echo "  - ${issue_id} (${open_child_count} open children: ${open_child_ids})"
    echo "    title: ${title}"
  done
fi

echo
if [[ "${#open_with_all_children_closed[@]}" -eq 0 ]]; then
  echo "[ok] No open issues where all child tasks are already closed."
else
  echo "[warn] Open issues whose child tasks are all closed (close or update status):"
  for row in "${open_with_all_children_closed[@]}"; do
    IFS='|' read -r issue_id title child_count <<<"${row}"
    echo "  - ${issue_id} (${child_count} children, all closed)"
    echo "    title: ${title}"
  done
fi

echo
if [[ "${#closed_with_open_children[@]}" -gt 0 || "${#open_with_all_children_closed[@]}" -gt 0 ]]; then
  echo "[audit] inconsistencies found"
  exit 1
fi

echo "[audit] consistent"
