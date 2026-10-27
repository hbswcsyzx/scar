#!/usr/bin/env bash
set -euo pipefail
cd /home/zyf/AAA/scar-worktrees/structured-program-model
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH=/home/zyf/AAA/scar-worktrees/structured-program-model
scar_os_lookup=artifacts/experiments/first_stage_os_source_lookup_review_20261023
/usr/bin/time -v -o "$scar_os_lookup/run.time.txt" \
  /home/zyf/miniconda3/envs/lewm/bin/python "$scar_os_lookup/probe.py" \
  > "$scar_os_lookup/run.stdout.jsonl" 2> "$scar_os_lookup/run.stderr.txt"
