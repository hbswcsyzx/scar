#!/usr/bin/env bash
set -euo pipefail
source /home/zyf/miniconda3/etc/profile.d/conda.sh
conda activate lewm
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH=/home/zyf/AAA/scar-worktrees/structured-program-model
output_dir=/home/zyf/AAA/scar-worktrees/structured-program-model/artifacts/experiments/first_stage_lewm_environment_mounted_20261022
test ! -e "$output_dir/trace"
mkdir -p "$output_dir/os"
export LEWM_CHECKPOINT_ROOT=/gpu4-share/data/byx/lewm_data
export LEWM_OUTPUT_ROOT="$output_dir/lewm_outputs"
export LEWM_RUN_NAME=stage1_environment_mounted
git -C /home/zyf/AAA/scar-worktrees/structured-program-model rev-parse HEAD > "$output_dir/scar-revision.txt"
git -C /home/zyf/AAA/le-wm rev-parse HEAD > "$output_dir/lewm-revision.txt"
git -C /home/zyf/AAA/le-wm status --porcelain > "$output_dir/lewm-status-before.txt"
strace -V > "$output_dir/strace-version.txt" 2>&1
nvidia-smi --query-gpu=index,name,memory.used,memory.total,utilization.gpu --format=csv,noheader > "$output_dir/gpu-before.txt"
cd /home/zyf/AAA/le-wm
/usr/bin/time -v -o "$output_dir/command.time.txt" \
  strace --seccomp-bpf -ff -qq -ttt -T -s 256 \
  -e trace=%file,%process,%memory,%desc \
  -e raw=read,write,readv,writev,pread64,pwrite64,preadv,pwritev,preadv2,pwritev2,ioctl,sendto,recvfrom,sendmsg,recvmsg,sendmmsg,recvmmsg,getdents,getdents64 \
  -o "$output_dir/os/syscalls" \
  python -m scar.cli trace --call-operands --execution-evidence \
  --project-root /home/zyf/AAA/le-wm --out "$output_dir/trace" \
  --max-call-events 250000 --max-call-bytes 256000000 \
  --max-operand-events 2000000 --max-operand-bytes 1200000000 -- \
  python run_inference.py --config-name=pusht policy=pusht/weights.pt \
  eval.num_eval=1 eval.eval_budget=25 eval.goal_offset_steps=25 \
  cache_dir=/gpu4-share/data/byx/lewm_data hydra.job.chdir=False \
  > "$output_dir/command.stdout.txt" 2> "$output_dir/command.stderr.txt"
git -C /home/zyf/AAA/le-wm status --porcelain > "$output_dir/lewm-status-after.txt"
