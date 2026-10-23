#!/usr/bin/env bash
set -euo pipefail
cd /home/zyf/AAA/scar-worktrees/structured-program-model
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH=/home/zyf/AAA/scar-worktrees/structured-program-model
scar_os_launch_gate=artifacts/experiments/first_stage_owned_os_capture_20261023/gate-attempt01
/usr/bin/time -v -o "$scar_os_launch_gate/run.time.txt" \
  /home/zyf/miniconda3/envs/lewm/bin/python "$scar_os_launch_gate/run.py" \
  > "$scar_os_launch_gate/run.stdout.jsonl" 2> "$scar_os_launch_gate/run.stderr.txt"
