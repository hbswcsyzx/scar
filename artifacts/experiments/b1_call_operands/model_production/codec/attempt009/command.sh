#!/usr/bin/env bash
set -euo pipefail
source /home/zyf/miniconda3/etc/profile.d/conda.sh
conda activate lewm
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH=.
python -m pytest -q \
  tests/unit/test_execution_production_codec.py \
  tests/unit/test_execution_codec.py \
  tests/unit/test_execution_work_codec.py \
  tests/unit/test_execution_order_codec.py \
  tests/unit/test_execution_content_codec.py \
  --junitxml=artifacts/experiments/b1_call_operands/model_production/codec/attempt009/junit.xml
