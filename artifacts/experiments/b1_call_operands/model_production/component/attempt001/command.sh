#!/usr/bin/env bash
source /home/zyf/miniconda3/etc/profile.d/conda.sh
conda activate lewm
cd /tmp/scar-structured-model-280qf4mi
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. python scripts/run_gate.py gates/m1_production_connections.json --out artifacts/experiments/b1_call_operands/model_production/component/attempt001/report.json > artifacts/experiments/b1_call_operands/model_production/component/attempt001/stdout.txt 2> artifacts/experiments/b1_call_operands/model_production/component/attempt001/stderr.txt
result=$?
printf '%s\n' "$result" > artifacts/experiments/b1_call_operands/model_production/component/attempt001/exit-code.txt
exit "$result"
