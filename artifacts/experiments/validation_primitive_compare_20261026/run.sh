#!/usr/bin/env bash
set -euo pipefail
TASK_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
TASK_TREE="$(cd -- "$TASK_DIR/../../.." && pwd)"
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH="$TASK_TREE"
cd "$TASK_TREE"
exec /usr/bin/time -v -o "$TASK_DIR/gnu-time.txt" timeout --signal=TERM --kill-after=10s 540s /home/zyf/miniconda3/envs/lewm/bin/python "$TASK_DIR/run.py"
