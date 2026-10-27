#!/bin/bash
set -e
cd /tmp/scar-structured-model-280qf4mi
source /home/zyf/miniconda3/etc/profile.d/conda.sh
conda activate lewm
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH=.
export PYTEST_ADDOPTS='-p no:cacheprovider'
python scripts/run_gate.py gates/m1_content_validity.json --out artifacts/experiments/b1_call_operands/model_validity/component/final/report.json
