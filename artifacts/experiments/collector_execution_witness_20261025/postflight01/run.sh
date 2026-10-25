#!/usr/bin/env bash
set -euo pipefail
cd /home/zyf/AAA/scar-worktrees/native-scalar-model
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH=/home/zyf/AAA/scar-worktrees/native-scalar-model
export CUDA_VISIBLE_DEVICES=''
unset SCAR_COLLECTOR_EXECUTION_WITNESS
/usr/bin/time -v -o artifacts/experiments/collector_execution_witness_20261025/postflight01/time.txt \
  /home/zyf/miniconda3/envs/lewm/bin/python -B artifacts/experiments/collector_execution_witness_20261025/postflight01/postflight.py
