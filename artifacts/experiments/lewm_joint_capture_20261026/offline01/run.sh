#!/usr/bin/env bash
set -euo pipefail
source /home/zyf/miniconda3/etc/profile.d/conda.sh
conda activate lewm
for name in ${!SCAR_@}; do unset "$name"; done
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH=/home/zyf/AAA/scar-worktrees/structured-program-model
cd /home/zyf/AAA/scar-worktrees/structured-program-model
HERE=/home/zyf/AAA/scar-worktrees/structured-program-model/artifacts/experiments/lewm_joint_capture_20261026/offline01
exec /usr/bin/time -v -o "$HERE/gnu-time.txt" /usr/bin/timeout --signal=INT --kill-after=30s 960s \
  /home/zyf/miniconda3/envs/lewm/bin/python -u "$HERE/postflight.py"
