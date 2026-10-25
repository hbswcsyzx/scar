#!/usr/bin/env bash
set -euo pipefail
source /home/zyf/miniconda3/etc/profile.d/conda.sh
conda activate lewm
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH=/home/zyf/AAA/scar-worktrees/structured-program-model
cd /home/zyf/AAA/scar-worktrees/structured-program-model
python -B artifacts/experiments/source_native_context_gate_20261025/run_gate.py "$@"
