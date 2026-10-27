#!/usr/bin/env bash
set -euo pipefail
source /home/zyf/miniconda3/etc/profile.d/conda.sh
conda activate lewm
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH=/home/zyf/AAA/scar-worktrees/structured-program-model
cd /home/zyf/AAA/scar-worktrees/structured-program-model
result_dir=artifacts/experiments/first_stage_source_attachments_20261023
test ! -e "$result_dir/producer.json"
test ! -e "$result_dir/progress.jsonl"
test ! -e "$result_dir/bindings"
test ! -e "$result_dir/dispatch"
git rev-parse HEAD > "$result_dir/revision.txt"
/usr/bin/time -v -o "$result_dir/run.time.txt" python "$result_dir/run.py" \
  > "$result_dir/run.stdout.jsonl" 2> "$result_dir/run.stderr.txt"
