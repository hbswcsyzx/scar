#!/usr/bin/env bash
set -euo pipefail
cd /home/zyf/AAA/scar-worktrees/structured-program-model
source /home/zyf/miniconda3/etc/profile.d/conda.sh
conda activate lewm
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH=/home/zyf/AAA/scar-worktrees/structured-program-model
result_dir=artifacts/experiments/first_stage_structured_inventory_20261022
test -s "$result_dir/inventory.json.gz"
test ! -e "$result_dir/replay.time.txt"
git rev-parse HEAD > "$result_dir/replay-implementation.git.txt"
/usr/bin/time -v -o "$result_dir/replay.time.txt" \
  python -m scar.cli check-inventory "$result_dir/inventory.json.gz" \
  --max-files 256 --max-lowered-bodies 256 --max-operations 10000 \
  --max-call-trace-bytes 256000000 --max-call-trace-lines 300000 \
  --max-call-trace-events 250000 --max-call-references 2000000 \
  --max-call-report-bytes 256000000 \
  > "$result_dir/replay.stdout.json" 2> "$result_dir/replay.stderr.txt"
