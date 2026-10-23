#!/usr/bin/env bash
set -euo pipefail
cd /home/zyf/AAA/scar-worktrees/structured-program-model
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH=/home/zyf/AAA/scar-worktrees/structured-program-model
scar_fd_projection=artifacts/experiments/first_stage_fd_table_projection_20261023
/usr/bin/time -v -o "$scar_fd_projection/run.time.txt" \
  /home/zyf/miniconda3/envs/lewm/bin/python "$scar_fd_projection/project.py" \
  > "$scar_fd_projection/run.stdout.jsonl" 2> "$scar_fd_projection/run.stderr.txt"
