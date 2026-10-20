#!/usr/bin/env bash
set -euo pipefail
cd /tmp/scar-structured-model-280qf4mi
source /home/zyf/miniconda3/etc/profile.d/conda.sh
conda activate lewm
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH=/tmp/scar-structured-model-280qf4mi
python -m pytest tests/unit/test_ir_v2.py tests/unit/test_ir_v2_codec_validation.py \
  tests/unit/test_ir_v2_graph_validation.py tests/unit/test_ir_v2_boundary_validation.py \
  tests/unit/test_trace_normalize_v2.py -q -p no:cacheprovider \
  --junitxml=artifacts/experiments/first_stage_native_import_20261020/schema-regression.junit.xml
