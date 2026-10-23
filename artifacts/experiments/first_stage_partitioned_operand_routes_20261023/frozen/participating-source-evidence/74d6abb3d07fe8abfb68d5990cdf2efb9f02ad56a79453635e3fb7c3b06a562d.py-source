#!/usr/bin/env bash
set -euo pipefail
cd /home/zyf/AAA/scar-worktrees/structured-program-model
source /home/zyf/miniconda3/etc/profile.d/conda.sh
conda activate lewm
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH=/home/zyf/AAA/scar-worktrees/structured-program-model
gate_dir=artifacts/experiments/first_stage_partitioned_operand_routes_20261023
test ! -e "$gate_dir/progress.jsonl"
test ! -e "$gate_dir/result"
python "$gate_dir/prepare.py" --phase frozen > "$gate_dir/frozen.stdout.json"
/usr/bin/time -v -o "$gate_dir/run.time.txt" python "$gate_dir/run.py" \
  > "$gate_dir/run.stdout.json" 2> "$gate_dir/run.stderr.txt"
