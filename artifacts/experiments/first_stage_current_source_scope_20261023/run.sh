#!/usr/bin/env bash
set -euo pipefail
cd /home/zyf/AAA/scar-worktrees/structured-program-model
result_dir=artifacts/experiments/first_stage_current_source_scope_20261023
test ! -e "$result_dir/result.json"
PYTHONDONTWRITEBYTECODE=1 /usr/bin/time -v -o "$result_dir/run.time.txt" \
  /usr/bin/python3 "$result_dir/analyze.py" > "$result_dir/run.stdout.json" 2> "$result_dir/run.stderr.txt"
