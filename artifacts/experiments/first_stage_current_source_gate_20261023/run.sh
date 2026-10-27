#!/usr/bin/env bash
set -euo pipefail
cd /home/zyf/AAA/scar-worktrees/structured-program-model
source /home/zyf/miniconda3/etc/profile.d/conda.sh
conda activate lewm
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH=/home/zyf/AAA/scar-worktrees/structured-program-model
result_dir=artifacts/experiments/first_stage_current_source_gate_20261023
test -e "$result_dir/frozen/producer.json"
test ! -e "$result_dir/result"
test ! -e "$result_dir/progress.jsonl"
/usr/bin/time -v -o "$result_dir/run.time.txt" python "$result_dir/run.py" \
    > "$result_dir/run.stdout.jsonl" 2> "$result_dir/run.stderr.txt"
