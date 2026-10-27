#!/usr/bin/env bash
set -euo pipefail
cd /tmp/scar-structured-model-280qf4mi
source /home/zyf/miniconda3/etc/profile.d/conda.sh
conda activate lewm
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH=/tmp/scar-structured-model-280qf4mi
output_dir=/tmp/scar-structured-model-280qf4mi/artifacts/experiments/first_stage_native_evidence_20261020
test ! -e "$output_dir/pytest.xml"
/usr/bin/time -v -o "$output_dir/pytest.time.txt" \
  python -m pytest -q \
  tests/integration/test_execution_evidence.py \
  tests/integration/test_call_operand_cli.py \
  tests/integration/test_call_operand_windows_cli.py \
  --junitxml="$output_dir/pytest.xml" \
  > "$output_dir/pytest.stdout.txt" 2> "$output_dir/pytest.stderr.txt"
