#!/bin/bash
source /home/zyf/miniconda3/etc/profile.d/conda.sh
conda activate lewm
PYTHONPATH=. python -m pytest tests/unit/test_execution_resources_graph.py -q --junitxml=artifacts/experiments/b1_call_operands/model_resource_identity/composition/attempt003/junit.xml
