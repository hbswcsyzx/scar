#!/usr/bin/env bash
set -euo pipefail
source /home/zyf/miniconda3/etc/profile.d/conda.sh
conda activate lewm
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH=/home/zyf/AAA/scar-worktrees/structured-program-model
scar_capture_root=/home/zyf/AAA/scar-worktrees/structured-program-model/artifacts/experiments/first_stage_lewm_physical_20261023
test ! -e "$scar_capture_root/trace"
mkdir -p "$scar_capture_root/os"
export LEWM_CHECKPOINT_ROOT=/gpu4-share/data/byx/lewm_data
export LEWM_OUTPUT_ROOT="$scar_capture_root/lewm_outputs"
export LEWM_RUN_NAME=stage1_physical
export SCAR_DISPATCH_MAX_EVENTS=2000000
export SCAR_DISPATCH_MAX_BYTES=1200000000
git -C /home/zyf/AAA/scar-worktrees/structured-program-model rev-parse HEAD > "$scar_capture_root/scar-revision.txt"
git -C /home/zyf/AAA/le-wm rev-parse HEAD > "$scar_capture_root/lewm-revision.txt"
git -C /home/zyf/AAA/le-wm status --porcelain > "$scar_capture_root/lewm-status-before.txt"
strace -V > "$scar_capture_root/strace-version.txt" 2>&1
nvidia-smi --query-gpu=index,name,memory.used,memory.total,utilization.gpu --format=csv,noheader > "$scar_capture_root/gpu-before.txt"
cd /home/zyf/AAA/le-wm
/usr/bin/time -v -o "$scar_capture_root/command.time.txt" \
  strace --seccomp-bpf -ff -qq -ttt -T -s 256 \
  -e trace=%file,%process,%memory,%desc \
  -e raw=read,write,readv,writev,pread64,pwrite64,preadv,pwritev,preadv2,pwritev2,ioctl,sendto,recvfrom,sendmsg,recvmsg,sendmmsg,recvmmsg,getdents,getdents64 \
  -o "$scar_capture_root/os/syscalls" \
  python -m scar.cli trace --call-operands --execution-evidence --tensor-physical \
  --project-root /home/zyf/AAA/le-wm --out "$scar_capture_root/trace" \
  --max-call-events 250000 --max-call-bytes 256000000 \
  --max-operand-events 2000000 --max-operand-bytes 1200000000 -- \
  python run_inference.py --config-name=pusht policy=pusht/weights.pt \
  eval.num_eval=1 eval.eval_budget=25 eval.goal_offset_steps=25 \
  cache_dir=/gpu4-share/data/byx/lewm_data hydra.job.chdir=False \
  > "$scar_capture_root/command.stdout.txt" 2> "$scar_capture_root/command.stderr.txt"
git -C /home/zyf/AAA/le-wm status --porcelain > "$scar_capture_root/lewm-status-after.txt"
