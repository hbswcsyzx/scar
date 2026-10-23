#!/usr/bin/env bash
set -euo pipefail
source /home/zyf/miniconda3/etc/profile.d/conda.sh
conda activate lewm
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH=/home/zyf/AAA/scar-worktrees/structured-program-model
cd /home/zyf/AAA/scar-worktrees/structured-program-model
git rev-parse HEAD > artifacts/experiments/first_stage_bundle_storage_20261023/base.git.txt
/usr/bin/time -v -o artifacts/experiments/first_stage_bundle_storage_20261023/time.txt \
  python artifacts/experiments/first_stage_bundle_storage_20261023/run.py \
  > artifacts/experiments/first_stage_bundle_storage_20261023/stdout.txt \
  2> artifacts/experiments/first_stage_bundle_storage_20261023/stderr.txt
