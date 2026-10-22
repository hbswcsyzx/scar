#!/usr/bin/env bash
set -euo pipefail
cd /home/zyf/AAA/scar-worktrees/structured-program-model
source /home/zyf/miniconda3/etc/profile.d/conda.sh
conda activate lewm
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH=/home/zyf/AAA/scar-worktrees/structured-program-model
result_dir=artifacts/experiments/first_stage_source_context_20261022
test ! -e "$result_dir/result"
test ! -e "$result_dir/run.time.txt"
git rev-parse HEAD > "$result_dir/implementation.git.txt"
python --version > "$result_dir/python-version.txt"
/usr/bin/time -v -o "$result_dir/run.time.txt" \
  python "$result_dir/run_contexts.py" \
  --inventory artifacts/experiments/first_stage_model_20261020/inventory.json.gz \
  --out "$result_dir/result" \
  > "$result_dir/run.stdout.jsonl" 2> "$result_dir/run.stderr.txt"
