#!/usr/bin/env bash
set -euo pipefail
cd /tmp/scar-structured-model-280qf4mi
source /home/zyf/miniconda3/etc/profile.d/conda.sh
conda activate lewm
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH=.
python artifacts/experiments/b1_call_operands/model_production/codec/attempt002/finalize_proof.py \
  artifacts/experiments/b1_call_operands/model_production/codec/attempt002 \
  tests/fixtures/execution_v4_frozen.json
sha256sum tests/fixtures/execution_v4_frozen.json tests/fixtures/execution_v4_frozen.json.proof.json
