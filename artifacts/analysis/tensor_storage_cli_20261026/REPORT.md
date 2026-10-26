# Public Tensor storage query

Implemented two generic commands: `index-tensor-storage` accepts three original artifact receipts and builds only ID/row/chunk locators; `query-tensor-storage` accepts an index SHA and an original object-to-storage SourceFact or region ID. Both call the existing normal index/query APIs. No workload or function-name rule is present.

Verified once through the public CLI in the main worktree, using the original ca66/PID1578961 LeWM capture and the already-built index: exit0, 2.558004s including Python startup. Query time was 0.996391s, with 157,442,012 charged input bytes. The original CUDA view is float32[192,3,14,14]; IDs and evidence scope remain those of the original capture. Index construction was already measured once by the underlying API; this integration did not rebuild it or rerun the target.

The result resolves the original held-Tensor observation to view/storage/allocation only. It does not prove logical content/version, cross-point storage equality, lifetime, materialization or readiness. It is not a target-program optimization or speedup measurement.
