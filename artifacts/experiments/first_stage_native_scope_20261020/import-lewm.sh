#!/usr/bin/env bash
set -euo pipefail
cd /tmp/scar-structured-model-280qf4mi
source /home/zyf/miniconda3/etc/profile.d/conda.sh
conda activate lewm
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH=/tmp/scar-structured-model-280qf4mi
capture_root=artifacts/experiments/first_stage_lewm_capture_20261020_bpf/trace
result_root=artifacts/experiments/first_stage_native_scope_20261020
eto_files=("$capture_root"/execution-trace.*.json.gz)
kineto_files=("$capture_root"/kineto.*.json.gz)
test "${#eto_files[@]}" -eq 1
test "${#kineto_files[@]}" -eq 1
git rev-parse HEAD > "$result_root/import-revision.txt"
/usr/bin/time -v -o "$result_root/import.time.txt" python -m scar.cli import-native \
  --execution-trace "${eto_files[0]}" --kineto "${kineto_files[0]}" \
  --provider-revision cf30153c4c131c8164ee7798e5022d810682e2cb \
  --out "$result_root/lewm-native"
