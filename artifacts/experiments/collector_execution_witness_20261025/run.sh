#!/usr/bin/env bash
set -euo pipefail
cd /home/zyf/AAA/scar-worktrees/native-scalar-model
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH=/home/zyf/AAA/scar-worktrees/native-scalar-model
/home/zyf/miniconda3/envs/lewm/bin/python -B artifacts/experiments/collector_execution_witness_20261025/gate.py
