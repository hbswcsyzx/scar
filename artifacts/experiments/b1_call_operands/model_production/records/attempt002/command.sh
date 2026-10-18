#!/usr/bin/env bash
set -u
cd /tmp/scar-structured-model-280qf4mi
source /home/zyf/miniconda3/etc/profile.d/conda.sh
conda activate lewm
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH=.
python -m pytest -q tests/unit/test_execution_production_records.py --junitxml=artifacts/experiments/b1_call_operands/model_production/records/attempt002/junit.xml
status=$?
printf 'exit_code=%s\n' "$status" > artifacts/experiments/b1_call_operands/model_production/records/attempt002/exit.txt
exit "$status"
