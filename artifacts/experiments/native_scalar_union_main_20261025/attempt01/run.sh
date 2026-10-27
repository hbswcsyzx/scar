#!/usr/bin/env bash
set -euo pipefail
cd /home/zyf/AAA/scar-worktrees/structured-program-model
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH=/home/zyf/AAA/scar-worktrees/structured-program-model
export CUDA_VISIBLE_DEVICES=''
unset SCAR_TRACE_DIR SCAR_OPTIMIZE SCAR_COLLECTOR_EXECUTION_WITNESS SCAR_TRACE_CALL_EDGES SCAR_CALL_OPERANDS SCAR_EXECUTION_EVIDENCE
/usr/bin/time -v -o artifacts/experiments/native_scalar_union_main_20261025/attempt01/time.txt \
  timeout --signal=TERM 150s /home/zyf/miniconda3/envs/lewm/bin/python -B artifacts/experiments/native_scalar_union_main_20261025/attempt01/gate.py
