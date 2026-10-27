#!/usr/bin/env bash
set -o pipefail
source /home/zyf/miniconda3/etc/profile.d/conda.sh
conda activate lewm
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH=.
pytest -q tests/unit/test_program_protocol_records.py --junitxml=artifacts/experiments/b1_call_operands/model_protocol_implementation/attempts/attempt003/junit.xml
