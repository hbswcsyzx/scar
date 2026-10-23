#!/usr/bin/env bash
set -euo pipefail
cd /home/zyf/AAA/scar-worktrees/structured-program-model
source /home/zyf/miniconda3/etc/profile.d/conda.sh
conda activate lewm
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH=/home/zyf/AAA/scar-worktrees/structured-program-model
result_dir=artifacts/experiments/first_stage_full_inventory_restored_20261023
test ! -e "$result_dir/result"
test ! -e "$result_dir/progress.jsonl"
git rev-parse HEAD > "$result_dir/base.git.txt"
/usr/bin/time -v -o "$result_dir/run.time.txt" \
  python "$result_dir/run_partitioned.py" inventory-program \
  /home/zyf/AAA/le-wm/run_inference.py \
  --project-root /home/zyf/AAA/le-wm --body-profile environment \
  --calls artifacts/experiments/first_stage_lewm_dispatch_20261023/trace \
  --out "$result_dir/result" \
  --max-files 256 --max-lowered-bodies 4096 --max-operations 100000 \
  --max-call-trace-bytes 256000000 --max-call-trace-lines 300000 \
  --max-call-trace-events 250000 --max-call-references 2000000 \
  --max-call-report-bytes 256000000 \
  > "$result_dir/run.stdout.json" 2> "$result_dir/run.stderr.txt"
