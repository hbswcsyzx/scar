#!/usr/bin/env bash
set -o pipefail
source /home/zyf/miniconda3/etc/profile.d/conda.sh
conda activate lewm
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH=.
pytest -q tests/unit/test_execution_coordinates_records.py > artifacts/experiments/b1_call_operands/model_resource_identity/coordinates/attempt001/stdout.txt 2>&1
status=$?
cat artifacts/experiments/b1_call_operands/model_resource_identity/coordinates/attempt001/stdout.txt
printf 'exit_code=%s\n' "$status" > artifacts/experiments/b1_call_operands/model_resource_identity/coordinates/attempt001/exit.txt
exit "$status"
