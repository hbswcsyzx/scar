#!/usr/bin/env bash
set -euo pipefail
cd /home/zyf/AAA/scar-worktrees/structured-program-model
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH=/home/zyf/AAA/scar-worktrees/structured-program-model
scar_fd_projection_gate=artifacts/experiments/first_stage_os_fd_source_projection_20261023/gate-attempt01
/usr/bin/time -v -o "$scar_fd_projection_gate/run.time.txt" \
  /home/zyf/miniconda3/envs/lewm/bin/python "$scar_fd_projection_gate/run.py" \
  > "$scar_fd_projection_gate/run.stdout.jsonl" 2> "$scar_fd_projection_gate/run.stderr.txt"
