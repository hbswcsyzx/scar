#!/usr/bin/env bash
set -euo pipefail
cd /home/zyf/AAA/scar-worktrees/structured-program-model
source /home/zyf/miniconda3/etc/profile.d/conda.sh
conda activate lewm
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH=/home/zyf/AAA/scar-worktrees/structured-program-model
gate_dir=artifacts/experiments/first_stage_source_publication_current_attempt02_20261023
test -f "$gate_dir/frozen/producer.json"
test ! -e "$gate_dir/result"
test ! -e "$gate_dir/progress.jsonl"
/usr/bin/time -v -o "$gate_dir/run.time.txt" python "$gate_dir/run.py" \
  > "$gate_dir/run.stdout.jsonl" 2> "$gate_dir/run.stderr.txt"
