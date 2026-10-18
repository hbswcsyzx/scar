#!/bin/bash
source /home/zyf/miniconda3/etc/profile.d/conda.sh
conda activate lewm
PYTHONPATH=. python artifacts/experiments/b1_call_operands/model_resource_identity/composition/attempt001/smoke.py
