# One real LeWM process-scope capture

Status: RUNNING; no complete-model or speedup result is claimed.

The runner uses the original successful pusht configuration (one evaluation, budget25, goal offset25), unmodified LeWM commit f70fed80288462ca4d006cb3607ec6da6eaa851f, and existing mounted data/checkpoints. Outputs are isolated under this directory. The collector is a private Git-archive snapshot of SCAR4f23a6d6; all426 files/8,666,445B are pinned in COLLECTOR_SOURCE.json, tree SHA7be2deb71d998b89c54a7278c196503bb2191ca5ea0a4c516ce988675e73a644. Later main-tree changes do not alter the active process.

V2 records process Python calls in installed threads, source bytes once per file, explicit native/forward boundaries, stream backing observations, ETO/Kineto/Tensor metadata, collector source/process images, topology and OS evidence. Native-thread/fork/exec Python scope limitations remain explicit; this run is not automatically full coverage. Numeric Tensor contents are not dumped.

RUN_STATUS.json is operational metadata; live process/session state determines whether the job is running. Root session41962, initial wrapperPID2062772 and targetPID2062781. Actual stdout/stderr and terminal/LeWM-after checks will be retained. Do not treat an open status file or partial output sizes as success.

Configured event/byte/source limits are ceilings, not completeness claims. The source tree is checked before/after. No CUDA address-space limit, global environment change, target edit, periodic GPU sampling or additional synthetic capture is performed.
