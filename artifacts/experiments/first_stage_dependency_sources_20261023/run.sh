#!/usr/bin/env bash
set -euo pipefail
cd /home/zyf/AAA/scar-worktrees/structured-program-model
source /home/zyf/miniconda3/etc/profile.d/conda.sh
conda activate lewm
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH=/home/zyf/AAA/scar-worktrees/structured-program-model
result_dir=artifacts/experiments/first_stage_dependency_sources_20261023
test ! -e "$result_dir/run.time.txt"
test ! -e "$result_dir/result"
test ! -e "$result_dir/progress.jsonl"
git rev-parse HEAD > "$result_dir/revision.txt"
sha256sum scar/analysis/dependency_sources.py > "$result_dir/module.sha256.txt"
cp scar/analysis/dependency_sources.py "$result_dir/dependency_sources.snapshot.py"
python --version > "$result_dir/python-version.txt"
/usr/bin/time -v -o "$result_dir/run.time.txt" \
  python "$result_dir/run.py" \
  > "$result_dir/run.stdout.json" 2> "$result_dir/run.stderr.txt"
