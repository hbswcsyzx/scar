# One real LeWM process-scope capture

Status: FAILED / incomplete capture. Exit241 after3,601.876s; no complete-model or speedup result is claimed.

The runner uses the original successful pusht configuration (one evaluation, budget25, goal offset25), unmodified LeWM commit f70fed80288462ca4d006cb3607ec6da6eaa851f, and existing mounted data/checkpoints. Outputs are isolated under this directory. The collector is a private Git-archive snapshot of SCAR4f23a6d6; all426 files/8,666,445B are pinned in COLLECTOR_SOURCE.json, tree SHA7be2deb71d998b89c54a7278c196503bb2191ca5ea0a4c516ce988675e73a644. Later main-tree changes do not alter the active process.

V2 records process Python calls in installed threads, source bytes once per file, explicit native/forward boundaries, stream backing observations, ETO/Kineto/Tensor metadata, collector source/process images, topology and OS evidence. Native-thread/fork/exec Python scope limitations remain explicit; this run is not automatically full coverage. Numeric Tensor contents are not dumped.

RUN_STATUS.json is operational metadata; live process/session state determines whether the job is running. Root session41962, initial wrapperPID2062772 and targetPID2062781. Actual stdout/stderr and terminal/LeWM-after checks will be retained. Do not treat an open status file or partial output sizes as success.

Configured event/byte/source limits are ceilings, not completeness claims. The source tree is checked before/after. No CUDA address-space limit, global environment change, target edit, periodic GPU sampling or additional synthetic capture is performed.

Observed terminal: the OS provider stopped at its3,600s wall ceiling (`budget_stop=WALL_SECONDS`, provider returncode−15). The outer runner exited241. The LeWM post-check confirms the original repository is unchanged. Stdout reached dataset column caching and ViT-tiny creation, but contains no completed episode result. Some dispatch and execution-trace bytes exist; their existence does not establish a completed solve or episode. Required closed call/operand/source manifests are absent.

The partial trace directory alone is6,652,274,145B. `PARTIAL_OUTPUTS.json` lists retained sizes, not validated trace membership or complete graph coverage. `/usr/bin/time` observed2,945.87s user and787.95s system CPU,103% aggregate CPU,82,697,619 voluntary context switches and peakRSS1,896,908KiB. This is an instrumented run, not a LeWM benchmark or speedup measurement.

Inspection establishes that hooks synchronously snapshot metadata and JSON-encode it, while graph lowering/binding are offline. The OS provider was configured as `strace trace=all`, including collector-side transport syscalls. Thus the current capture has both serialization and syscall-tracing overhead. Their separate wall-time contributions were not measured. Increasing threads alone is not a demonstrated remedy. Preserve this failed run; reduce redundant transport and use bounded independent offline workers before another whole-process capture.

Lossless retention update: the stopped provider's bulk members were archived using4 bounded compression workers. ARCHIVAL_RESULT.json and capture/partial-archive-index.json retain exact raw/compressed SHA/byte receipts.8,027,996,678B raw became677,057,591B gzip in38.746s; originals were removed only after all roundtrip checks and manifest publication. PARTIAL_OUTPUTS.json remains the historical pre-archive size list. The capture is still incomplete/exit241; archival does not create a successful Run or repair missing source/frame manifests.
