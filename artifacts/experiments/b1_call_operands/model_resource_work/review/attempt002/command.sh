#!/usr/bin/env bash
source /home/zyf/miniconda3/etc/profile.d/conda.sh
conda activate lewm
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH=.
date -u '+started_at=%Y-%m-%dT%H:%M:%SZ'
sha256sum scar/ir/execution/work_validation.py scar/ir/execution/resource_validation.py scar/ir/execution/validation.py tests/fixtures/execution_work_graphs.py
python artifacts/experiments/b1_call_operands/model_resource_work/review/attempt002/foreign_reference_probe.py
status=$?
printf 'probe_exit=%s\n' "$status"
sha256sum scar/ir/execution/work_validation.py scar/ir/execution/resource_validation.py scar/ir/execution/validation.py tests/fixtures/execution_work_graphs.py
exit "$status"
