#!/usr/bin/env bash
set -euo pipefail
cd /home/zyf/AAA/scar-worktrees/structured-program-model
source /home/zyf/miniconda3/etc/profile.d/conda.sh
conda activate lewm
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH=/home/zyf/AAA/scar-worktrees/structured-program-model
result_dir=artifacts/experiments/first_stage_native_memory_20261022
test ! -e "$result_dir/result"
test ! -e "$result_dir/run.time.txt"
git rev-parse HEAD > "$result_dir/base.git.txt"
/usr/bin/time -v -o "$result_dir/run.time.txt" \
  python -m scar.cli import-native \
  --execution-trace artifacts/experiments/first_stage_lewm_capture_20261020_bpf/trace/execution-trace.452006.72a7a04c0c2fe234c810ff8060ffaeb7.json.gz \
  --kineto artifacts/experiments/first_stage_lewm_capture_20261020_bpf/trace/kineto.452006.72a7a04c0c2fe234c810ff8060ffaeb7.json.gz \
  --provider-revision cf30153c4c131c8164ee7798e5022d810682e2cb \
  --out "$result_dir/result" \
  > "$result_dir/run.stdout.json" 2> "$result_dir/run.stderr.txt"
