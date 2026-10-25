#!/usr/bin/env bash
set -euo pipefail
cd /home/zyf/AAA/scar-worktrees/native-scalar-model
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH=/home/zyf/AAA/scar-worktrees/native-scalar-model
export CUDA_VISIBLE_DEVICES=''
unset SCAR_COLLECTOR_EXECUTION_WITNESS
/home/zyf/miniconda3/envs/lewm/bin/python -B analysis/native_correlation_identity_review_20261025/tiny_check.py
