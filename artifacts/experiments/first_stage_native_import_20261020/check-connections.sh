#!/usr/bin/env bash
set -euo pipefail
cd /tmp/scar-structured-model-280qf4mi
source /home/zyf/miniconda3/etc/profile.d/conda.sh
conda activate lewm
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH=/tmp/scar-structured-model-280qf4mi
python -m pytest tests/unit/test_native_import.py tests/unit/test_regions_v2.py \
  tests/unit/test_execution_production_records.py tests/unit/test_execution_production_codec.py \
  -q -p no:cacheprovider \
  --junitxml=artifacts/experiments/first_stage_native_import_20261020/connections.junit.xml
