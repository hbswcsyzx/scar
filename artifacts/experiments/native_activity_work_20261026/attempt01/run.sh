#!/usr/bin/env bash
set -euo pipefail
cd /home/zyf/AAA/scar-worktrees/frame-entry-routing
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH=/home/zyf/AAA/scar-worktrees/frame-entry-routing
/usr/bin/time -v -o artifacts/experiments/native_activity_work_20261026/attempt01/gnu-time.txt timeout --signal=TERM --kill-after=10s 660s /home/zyf/miniconda3/envs/lewm/bin/python -u artifacts/experiments/native_activity_work_20261026/attempt01/gate.py > artifacts/experiments/native_activity_work_20261026/attempt01/stdout.txt 2> artifacts/experiments/native_activity_work_20261026/attempt01/stderr.txt
