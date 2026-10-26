#!/usr/bin/env bash
set -euo pipefail
source /home/zyf/miniconda3/etc/profile.d/conda.sh
conda activate lewm
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH=/home/zyf/AAA/scar-worktrees/structured-program-model
exec timeout --signal=TERM --kill-after=15s 180s python -B /home/zyf/AAA/scar-worktrees/structured-program-model/artifacts/experiments/project_dependency_publication_gate_20261025/capture.py
