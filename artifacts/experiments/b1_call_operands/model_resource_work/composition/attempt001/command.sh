#!/bin/bash
set -o pipefail
source /home/zyf/miniconda3/etc/profile.d/conda.sh
conda activate lewm
PYTHONPATH=. python -m pytest tests/unit/test_execution_work_graph.py -q --junitxml=artifacts/experiments/b1_call_operands/model_resource_work/composition/attempt001/junit.xml 2>&1 | tee artifacts/experiments/b1_call_operands/model_resource_work/composition/attempt001/output.log
