#!/usr/bin/env bash
source /home/zyf/miniconda3/etc/profile.d/conda.sh
conda activate lewm
cd /tmp/scar-structured-model-280qf4mi
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. python -m pytest -q tests/unit/test_execution_source_connections.py > artifacts/experiments/b1_call_operands/model_production/source/attempt003/stdout.txt 2> artifacts/experiments/b1_call_operands/model_production/source/attempt003/stderr.txt
result=$?
printf '%s\n' "$result" > artifacts/experiments/b1_call_operands/model_production/source/attempt003/exit-code.txt
exit "$result"
