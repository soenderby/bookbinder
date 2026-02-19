#!/usr/bin/env bash
set -euo pipefail

COUNT="${1:-2}"
ROOT="$(git rev-parse --show-toplevel)"

mkdir -p "${ROOT}/worktrees"

for i in $(seq 1 "${COUNT}"); do
  name="agent-${i}"
  rel_path="worktrees/${name}"
  abs_path="${ROOT}/${rel_path}"
  branch="swarm/${name}"

  if git worktree list --porcelain | awk '/^worktree / {print $2}' | grep -Fxq "${abs_path}"; then
    echo "[setup] ${rel_path} already exists"
    continue
  fi

  echo "[setup] creating ${rel_path} (branch: ${branch})"
  bd worktree create "${rel_path}" --branch "${branch}"
done

echo "[setup] done"
