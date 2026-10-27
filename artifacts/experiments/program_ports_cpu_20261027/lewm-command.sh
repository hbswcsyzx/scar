#!/usr/bin/env bash
# Prepared command only. No LeWM episode was run for this delivery.
set -euo pipefail
source /home/zyf/miniconda3/etc/profile.d/conda.sh
conda activate lewm
for name in ${!SCAR_@}; do unset "$name"; done
CAPTURE_TREE=/home/zyf/AAA/scar-worktrees/program-ports-capture
RUN_ROOT=/home/zyf/AAA/scar-worktrees/structured-program-model/artifacts/experiments/lewm_program_ports_20261027
test ! -e "$RUN_ROOT"
mkdir -m 700 "$RUN_ROOT"
export PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$CAPTURE_TREE"
export SCAR_COLLECTOR_EXECUTION_WITNESS=1 SCAR_PROCESS_IMAGE_RECEIPTS=1
export SCAR_NATIVE_TENSOR_INPUTS=1 SCAR_RESOURCE_TOPOLOGY=1
export LEWM_CHECKPOINT_ROOT=/gpu4-share/data/byx/lewm_data
export LEWM_DATA_ROOT=/gpu4-share/nfs/gpu4-share/lewm_data
export LEWM_OUTPUT_ROOT="$RUN_ROOT/lewm-output" LEWM_RUN_NAME=program-ports-20261027
cd /home/zyf/AAA/le-wm
# No target edit, GPU-memory tensor dump, periodic nvidia-smi subprocesses,
# instruction trace, or CUDA RLIMIT_AS. These are ceilings, not completeness.
exec /usr/bin/time -v -o "$RUN_ROOT/time.txt" \
  /usr/bin/timeout --signal=INT --kill-after=60s 4500s \
  python -B -m scar.cli trace --capture-profile program-ports \
    --out "$RUN_ROOT/capture/trace" --project-root /home/zyf/AAA/le-wm \
    --max-call-events 2000000 --max-call-bytes 1200000000 --max-call-codes 32768 \
    --max-operand-events 2000000 --max-operand-bytes 1200000000 \
    --max-source-files 2048 --max-source-file-bytes 2000000 --max-source-bytes 128000000 \
    --execution-evidence --tensor-physical --os-capture-root "$RUN_ROOT/capture" \
    --max-os-bytes 1500000000 --max-os-lines 6000000 \
    --max-capture-bytes 4000000000 --max-archive-bytes 2500000000 \
    --max-archive-files 4096 --os-timeout 3600 -- \
    /home/zyf/miniconda3/envs/lewm/bin/python run_inference.py --config-name=pusht \
    policy=pusht/weights.pt eval.num_eval=1 eval.eval_budget=25 eval.goal_offset_steps=25 \
    cache_dir=/gpu4-share/data/byx/lewm_data hydra.job.chdir=False
