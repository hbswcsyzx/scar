# Independent source209 postflight, prepared not run

Root confirmed original48283 actualexit1/2768.343s and fresh6064 actualexit1/2208.154731s. The resume completed all97 ordinary public terminals (52successful/45unsupported), but its FINAL_FROZEN_CHECK then failed because a pinned control report was absent. The original gate/freeze/ledger/status remain unchanged. This independent postflight cannot upgrade either exit1 or prove the restored control file existed during the failed check.

Before Root restoration, all463 input pins were enumerated:461 matched original SHA/size (21,519,151B), and exactly2 controls were absent: ORIGINAL_INPUT_SHA_CHECK.json (272B,9d014c3573a36d0ce46be390cdcd1ac6268f8eab3f4d54e4f509d229c7cb8507) and OWNER_FULL_DECLARATION_RECOVERY.json (2998B,a42cedb3c7aa0eed5346ad3fb4f1d4107f83b0861723a17c04cf7a59e64413e6). Root50692 restored the exact originals; preparation independently checked all463 again (21,522,421B), with no mismatch. FINAL_CONTROL_RESTORE.json is pinned.

The runner checks226 immutable public terminal histories (original129 including17failed, plus fresh97), merges exact latest keys into209=115successful/94unsupported, preserves earlier33=26successful/7unsupported and the1resumable frontier, and retains the817groups/100438calls/243candidate denominators. Original live owners are not restored.

It streams the115 original successful SP5 gzip transports once against their original ordinary-result physical SHA/size:252,129,699B. Their2,216,810,250 canonical bytes remain declarations already consumed by the original ordinary worker, not independently decoded by this postflight. Original public reader/code-reader flags are checked as retained facts. It then checks the original376source pins/831runtime pins/463inputs and4archive file member sets. This is no new CodeType/AST/graph/canonical validation, worker, lowering, publication, target/episode or currentRun binding. Static source-entry results do not increase runtime858/6882; whole phase1 remains OPEN.

Budget: external180s/AS1GiB, stored512MB/JSON decoded32MB/per-record8MB/output8MB. Hashing is streamed; interpreter import I/O remains outside this explicit reader accounting. Input restored ctime/mode is not compared to the failed run's old stat. Runtime scope remains the original frozen list, not an assertion every file was imported or executed. prepare.stdout names the earlier pre-I/O-accounting prepared SHA; current freeze.json pins the final runner exactly, with the previous prepared freeze retained. No consumer/model producer changed.

Root launch:

```sh
cd /home/zyf/AAA/scar-worktrees/source209-model
source /home/zyf/miniconda3/etc/profile.d/conda.sh
conda activate lewm
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/home/zyf/AAA/scar-worktrees/source209-model /usr/bin/time -v -o artifacts/experiments/source209_resume01_postflight01_20261026/postflight.time.txt timeout --signal=TERM --kill-after=10s 180s python -B artifacts/experiments/source209_resume01_postflight01_20261026/run.py > artifacts/experiments/source209_resume01_postflight01_20261026/postflight.stdout.json 2> artifacts/experiments/source209_resume01_postflight01_20261026/postflight.stderr.txt
```
