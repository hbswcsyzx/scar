#!/usr/bin/env bash
set -euo pipefail
cd /home/zyf/AAA/scar-worktrees/structured-program-model
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH=/home/zyf/AAA/scar-worktrees/structured-program-model
scar_all_handles=artifacts/experiments/first_stage_all_os_handle_review_20261023
/usr/bin/time -v -o "$scar_all_handles/run.time.txt" \
  /home/zyf/miniconda3/envs/lewm/bin/python "$scar_all_handles/catalog.py" \
  > "$scar_all_handles/run.stdout.jsonl" 2> "$scar_all_handles/run.stderr.txt"
