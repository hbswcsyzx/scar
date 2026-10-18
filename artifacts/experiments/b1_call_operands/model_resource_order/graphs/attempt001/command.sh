#!/bin/bash
set -o pipefail
source /home/zyf/miniconda3/etc/profile.d/conda.sh
conda activate lewm
PYTHONPATH=. python -m pytest tests/unit/test_execution_order_graphs.py -q --junitxml=artifacts/experiments/b1_call_operands/model_resource_order/graphs/attempt001/junit.xml 2>&1 | tee artifacts/experiments/b1_call_operands/model_resource_order/graphs/attempt001/output.log
