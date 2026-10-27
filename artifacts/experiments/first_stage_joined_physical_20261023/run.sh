#!/usr/bin/env bash
set -euo pipefail
source /home/zyf/miniconda3/etc/profile.d/conda.sh
conda activate lewm
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH=/home/zyf/AAA/scar-worktrees/structured-program-model
cd /home/zyf/AAA/scar-worktrees/structured-program-model
git rev-parse HEAD > artifacts/experiments/first_stage_joined_physical_20261023/base.git.txt
sha256sum scar/cli.py scar/trace/capture_import.py scar/trace/capture_coordinates.py \
  scar/trace/native_import.py scar/trace/dispatch_import.py scar/trace/tensor_physical_import.py \
  scar/trace/native_schema.py scar/store/bundle_partitions.py \
  > artifacts/experiments/first_stage_joined_physical_20261023/modules.sha256
git diff -- scar/cli.py scar/trace/capture_import.py \
  > artifacts/experiments/first_stage_joined_physical_20261023/integration.patch
/usr/bin/time -v -o artifacts/experiments/first_stage_joined_physical_20261023/time.txt \
  python -m scar.cli import-capture \
  artifacts/experiments/first_stage_lewm_physical_20261023 \
  --max-bytes 2000000000 --max-lines 2000000 --schema-contracts --bundle-partitions \
  --out artifacts/experiments/first_stage_joined_physical_20261023/result \
  > artifacts/experiments/first_stage_joined_physical_20261023/stdout.txt \
  2> artifacts/experiments/first_stage_joined_physical_20261023/stderr.txt
