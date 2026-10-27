#!/usr/bin/env bash
set -euo pipefail
cd /tmp/scar-structured-model-280qf4mi
source /home/zyf/miniconda3/etc/profile.d/conda.sh
conda activate lewm
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH=/tmp/scar-structured-model-280qf4mi
output_dir=/tmp/scar-structured-model-280qf4mi/artifacts/experiments/first_stage_model_20261020
test ! -e "$output_dir/inventory.json.gz"
python --version > "$output_dir/python-version.txt"
git rev-parse HEAD > "$output_dir/source-revision.txt"
/usr/bin/time -v -o "$output_dir/inventory.time.txt" \
  python -m scar.cli inventory-program /home/zyf/AAA/le-wm/run_inference.py \
  --project-root /home/zyf/AAA/le-wm \
  --calls /home/zyf/AAA/scar/artifacts/experiments/b1_call_operands/windows_lewm/trace \
  --out "$output_dir/inventory.json.gz" \
  --max-files 256 --max-lowered-bodies 256 --max-operations 10000 \
  --max-call-trace-bytes 256000000 --max-call-trace-lines 300000 \
  --max-call-trace-events 250000 --max-call-references 2000000 \
  --max-call-report-bytes 256000000 \
  > "$output_dir/inventory.stdout.json" 2> "$output_dir/inventory.stderr.txt"
