#!/usr/bin/env bash
set -euo pipefail
source /home/zyf/miniconda3/etc/profile.d/conda.sh
conda activate lewm
for name in ${!SCAR_@}; do unset "$name"; done
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH=/home/zyf/AAA/scar-worktrees/structured-program-model
cd /home/zyf/AAA/scar-worktrees/structured-program-model
HERE=/home/zyf/AAA/scar-worktrees/structured-program-model/artifacts/experiments/lewm_joint_capture_20261026
# Provider owns its 3600s episode limit. This outer guard also permits archive
# and ordinary-reader finalization; it does not install a CUDA RLIMIT_AS.
exec /usr/bin/time -v -o "$HERE/gnu-time.txt" /usr/bin/timeout --signal=INT --kill-after=60s 4500s \
  /home/zyf/miniconda3/envs/lewm/bin/python -u "$HERE/gate.py"
