#!/usr/bin/env bash
source /home/zyf/miniconda3/etc/profile.d/conda.sh
conda activate lewm
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH=.
date -u '+started_at=%Y-%m-%dT%H:%M:%SZ'
sha256sum scar/ir/execution/work.py tests/unit/test_execution_work_records.py
python -m pytest -q tests/unit/test_execution_work_records.py --junitxml=artifacts/experiments/b1_call_operands/model_resource_work/records/attempt003/junit.xml
status=$?
printf 'pytest_exit=%s\n' "$status"
exit "$status"
