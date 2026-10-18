#!/usr/bin/env bash
source /home/zyf/miniconda3/etc/profile.d/conda.sh
conda activate lewm
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH=.
date -u '+started_at=%Y-%m-%dT%H:%M:%SZ'
sha256sum scar/ir/execution/ids.py scar/ir/execution/order.py scar/ir/execution/model.py tests/unit/test_execution_order_records.py
python -m pytest -q tests/unit/test_execution_order_records.py
status=$?
printf 'pytest_exit=%s\n' "$status"
sha256sum scar/ir/execution/ids.py scar/ir/execution/order.py scar/ir/execution/model.py tests/unit/test_execution_order_records.py
exit "$status"
