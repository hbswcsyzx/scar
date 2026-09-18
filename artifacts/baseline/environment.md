# LeWM baseline environment

## Repository
```
/home/zyf/AAA/le-wm
origin	git@github.com:hbswcsyzx/lewm.git (fetch)
origin	git@github.com:hbswcsyzx/lewm.git (push)
f70fed80288462ca4d006cb3607ec6da6eaa851f
```

## Python and Torch
```
/home/zyf/miniconda3/envs/lewm/bin/python
Python 3.14.7
torch 2.13.0+cu132
cuda 13.2
cuda_available True
device NVIDIA GeForce RTX 4090
```

## GPU
```
Wed Sep 16 12:25:22 2026       
+-----------------------------------------------------------------------------------------+
| NVIDIA-SMI 595.58.03              Driver Version: 595.58.03      CUDA Version: 13.2     |
+-----------------------------------------+------------------------+----------------------+
| GPU  Name                 Persistence-M | Bus-Id          Disp.A | Volatile Uncorr. ECC |
| Fan  Temp   Perf          Pwr:Usage/Cap |           Memory-Usage | GPU-Util  Compute M. |
|                                         |                        |               MIG M. |
|=========================================+========================+======================|
|   0  NVIDIA GeForce RTX 4090        Off |   00000000:84:00.0 Off |                  Off |
| 30%   42C    P8              6W /  450W |       1MiB /  24564MiB |      0%      Default |
|                                         |                        |                  N/A |
+-----------------------------------------+------------------------+----------------------+

+-----------------------------------------------------------------------------------------+
| Processes:                                                                              |
|  GPU   GI   CI              PID   Type   Process name                        GPU Memory |
|        ID   ID                                                               Usage      |
|=========================================================================================|
|  No running processes found                                                             |
+-----------------------------------------------------------------------------------------+
```

## Known successful command
```
python run_inference.py --config-name=<pusht|cube|tworoom|reacher> policy=<name>/weights.pt
Existing artifacts under le-wm/inference_results/* show successful runs with policy weights.pt and 50 evals.
```

The concrete one-episode command subsequently reproduced by SCAR is:

```bash
cd /home/zyf/AAA/le-wm
source /home/zyf/miniconda3/etc/profile.d/conda.sh
conda activate lewm
LEWM_CHECKPOINT_ROOT=/gpu4-share/data/byx/lewm_data \
LEWM_OUTPUT_ROOT=/home/zyf/AAA/scar/artifacts/experiments/lewm_outputs \
python run_inference.py --config-name=pusht policy=pusht/weights.pt \
  eval.num_eval=1 eval.eval_budget=25 eval.goal_offset_steps=25 \
  cache_dir=/gpu4-share/data/byx/lewm_data hydra.job.chdir=False
```

Dependency snapshot: [pip-freeze.txt](pip-freeze.txt). The original Git status
was clean; repeated checks still show the same HEAD and no tracked changes.
The legacy clean run log is `lewm_pusht_clean/run.log`. Its single wall-time
sample is not a repeated A/B benchmark and contains no complete CPU/GPU
utilization time series. The resource-enabled run below supplies observed
utilization evidence, but neither run is a clean baseline/optimized comparison.

## Resource-enabled observed run

The same command was rerun through the generic SCAR entry point with
`scar trace --resources --resource-interval 0.25`. It returned code `0`,
reported `success_rate=100.0`, and took `102.70049062976614 s` wall-clock. The
trace contains `45,892` events and `259` resource samples. Process CPU was
`2.3108832021070826%` average and `38.518550721414975%` peak. GPU 0 utilization
was `0.7441860465116279%` average and `23.0%` peak; GPU memory was `438.1279069767442`
MiB average and `2250.0` MiB peak. These are `Observed` measurements from an
instrumented run, not a clean baseline/optimized comparison. Raw samples are
in `../traces/lewm_resource_sampled_20260917/resources.jsonl`, with the
machine-readable summary at
`../traces/lewm_resource_sampled_20260917/resources.summary.json`.

After adding generic CPython `c_call` boundary records, the same command was
rerun without changing LeWM. It returned code `0`, reported
`success_rate=100.0`, and took `104.85442663868889 s` under instrumentation.
The new trace has `45,894` events, including four observed C-call boundaries
(`append` three times and `setdefault` once), all conservatively labeled
`CTRL+STATE+OPAQUE`. Its generic detector produced `1,465` rejected
opportunities and selected zero transformations. This is `Observed` trace
evidence, not a clean optimized A/B result. Raw events are in
`../traces/lewm_resource_sampled_c_call_20260917/`, with the analysis summary
at `../reports/lewm_resource_sampled_c_call_20260917.summary.json`.
