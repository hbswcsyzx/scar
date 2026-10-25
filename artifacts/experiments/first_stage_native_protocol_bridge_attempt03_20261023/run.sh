#!/usr/bin/env bash
set -euo pipefail
cd /home/zyf/AAA/scar-worktrees/structured-program-model
source /home/zyf/miniconda3/etc/profile.d/conda.sh
conda activate lewm
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH="$PWD"
/usr/bin/time -v -o artifacts/experiments/first_stage_native_protocol_bridge_attempt03_20261023/time.txt python artifacts/experiments/first_stage_native_protocol_bridge_attempt03_20261023/gate.py > artifacts/experiments/first_stage_native_protocol_bridge_attempt03_20261023/stdout.txt 2> artifacts/experiments/first_stage_native_protocol_bridge_attempt03_20261023/stderr.txt
