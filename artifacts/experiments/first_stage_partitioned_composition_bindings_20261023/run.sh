#!/usr/bin/env bash
set -euo pipefail
cd /home/zyf/AAA/scar-worktrees/structured-program-model
source /home/zyf/miniconda3/etc/profile.d/conda.sh
conda activate lewm
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH=/home/zyf/AAA/scar-worktrees/structured-program-model
result_dir=artifacts/experiments/first_stage_partitioned_composition_bindings_20261023
test ! -e "$result_dir/progress.jsonl"
test ! -e "$result_dir/composition"
test ! -e "$result_dir/bindings"
git rev-parse HEAD > "$result_dir/base.git.txt"
git diff --binary -- scar/analysis/program_composition.py scar/analysis/source_invocations.py > "$result_dir/implementation.patch"
/usr/bin/time -v -o "$result_dir/run.time.txt" python "$result_dir/run.py" \
  > "$result_dir/run.stdout.json" 2> "$result_dir/run.stderr.txt"
