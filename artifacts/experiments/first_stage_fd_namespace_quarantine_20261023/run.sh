#!/usr/bin/env bash
set -euo pipefail
cd /home/zyf/AAA/scar-worktrees/structured-program-model
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH=/home/zyf/AAA/scar-worktrees/structured-program-model
scar_namespace_guard=artifacts/experiments/first_stage_fd_namespace_quarantine_20261023
/usr/bin/time -v -o "$scar_namespace_guard/run.time.txt" \
  /home/zyf/miniconda3/envs/lewm/bin/python "$scar_namespace_guard/run.py" \
  > "$scar_namespace_guard/run.stdout.jsonl" 2> "$scar_namespace_guard/run.stderr.txt"
