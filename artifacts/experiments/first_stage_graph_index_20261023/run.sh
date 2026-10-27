#!/usr/bin/env bash
set -eu
source /home/zyf/miniconda3/etc/profile.d/conda.sh
conda activate lewm
cd /home/zyf/AAA/scar-worktrees/structured-program-model
export PYTHONPATH="$PWD${PYTHONPATH:+:$PYTHONPATH}"
scar_index_tag="${1:-attempt01}"
/usr/bin/time -v -o "artifacts/experiments/first_stage_graph_index_20261023/time.${scar_index_tag}.txt" python -u artifacts/experiments/first_stage_graph_index_20261023/run.py "$scar_index_tag" > "artifacts/experiments/first_stage_graph_index_20261023/run.${scar_index_tag}.log" 2>&1
