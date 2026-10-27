# LeWM with explicit program-interface capture

FAILED: provider wall ceiling1800s, exit241 after1801.896s; episode and whole graph incomplete.

Original unmodified LeWM f70fed80288462ca4d006cb3607ec6da6eaa851f; original pusht configuration, eval1/budget25/goal-offset25. Existing mounted data/checkpoints; output paths isolated here. Collector frozen from SCAR 5e45c8e062843a840b601580ad5968da56be52eb, 434 files/8868929 bytes, tree SHA c25ee6f747be96f4b4d4ffc21c0aed3515ab150007580533a21e6aa48f44d8ef.

This run changes instrumentation: weak static CALL/layout caching (byte-only decoder), batch environment writes, explicit program-interfaces OS selection with seccomp-bpf REQUESTED_NOT_VERIFIED, aggregate raw capture bounds,4-thread verified archival and a bounded262144 active-weak-reference ceiling. Dynamic associations still observed at each occurrence. Source archiving remains once per observed file; no numeric Tensor contents are dumped.

Ceilings are not coverage claims:16GB aggregate raw/4GB archive,1GB OS output,1800s owned provider/2100s outer launcher. V2 native-thread/fork/exec Python frontiers remain. Read ACTUAL_TERMINAL.json and closed collector metadata for the outcome, not partial sizes. This is an instrumented modeling run, not a clean LeWM benchmark.

Observed: stdout remained empty, no episode result; LeWM post-check unchanged. The static metadata caches and narrower OS selection did not make this all-call configuration practical. CPU utilization alone does not locate the remaining callback cost; nonblocking stack reading was denied by host permissions. Preserve this failure and change the recording path before another full-process attempt; do not only enlarge time/byte limits.
