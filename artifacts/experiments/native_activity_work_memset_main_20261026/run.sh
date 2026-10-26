#!/usr/bin/env bash
set -euo pipefail
cd /home/zyf/AAA/scar-worktrees/structured-program-model
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH=/home/zyf/AAA/scar-worktrees/structured-program-model
/usr/bin/time -v -o artifacts/experiments/native_activity_work_memset_main_20261026/gnu-time.txt timeout --signal=TERM --kill-after=10s 660s /home/zyf/miniconda3/envs/lewm/bin/python -u artifacts/experiments/native_activity_work_memset_main_20261026/gate.py > artifacts/experiments/native_activity_work_memset_main_20261026/stdout.txt 2> artifacts/experiments/native_activity_work_memset_main_20261026/stderr.txt
