#!/usr/bin/env bash
set -euo pipefail
set -o noclobber
cd /home/zyf/AAA/scar-worktrees/native-scalar-model
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH=/home/zyf/AAA/scar-worktrees/native-scalar-model
batch_out=artifacts/experiments/native_capture_batch_attempt02_20261025
test ! -e "$batch_out/time.txt"
test ! -e "$batch_out/gate-started.json"
/usr/bin/time -v -o "$batch_out/time.txt" /home/zyf/miniconda3/envs/lewm/bin/python "$batch_out/gate.py" > "$batch_out/stdout.txt" 2> "$batch_out/stderr.txt"
