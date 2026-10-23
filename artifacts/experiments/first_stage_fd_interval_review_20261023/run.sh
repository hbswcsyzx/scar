#!/usr/bin/env bash
set -euo pipefail
cd /home/zyf/AAA/scar-worktrees/structured-program-model
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH=/home/zyf/AAA/scar-worktrees/structured-program-model
scar_interval_review=artifacts/experiments/first_stage_fd_interval_review_20261023
/usr/bin/time -v -o "$scar_interval_review/run.time.txt" \
  /home/zyf/miniconda3/envs/lewm/bin/python "$scar_interval_review/review.py" \
  > "$scar_interval_review/run.stdout.jsonl" 2> "$scar_interval_review/run.stderr.txt"
