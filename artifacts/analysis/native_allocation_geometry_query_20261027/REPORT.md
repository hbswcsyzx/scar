# Native input allocation query with ETO geometry

## Result

The public `query-native-allocation` command now follows the exact qualification-row reference already present in the selected navigation row. It verifies that chunk's stored SHA, reads only the referenced JSONL row, and joins its ETO locator and denotation to the same `NativeInputRef`. It then uses the existing allocation query result and storage bundle record to return a derived `StorageRegion` alongside the original allocation. It reuses the normal Program/Execution load in `query_native_input_allocation`; it does not load those models a second time.

The actual query was input row 53, path `[0]`, for the retained `copy_` invocation. It returned ETO tuple `[58,36,0,1,4,"cpu"]`, scalar shape `[]`, strides `[]`, and observed storage offset 0. That port joins to the original provider allocation epoch ID 2 (CPU, 640 bytes). The returned region is `region:native-input-observed-region:5a6e7713acb79b5ad7e48e63c65d0012a9e6f9c620de40e6a3ad6976bf14ae3d`, with offset 0 and dtype `torch.float32`. The region is a query result, not a new stored IR row.

The ETO `storage_id` token 36 remains distinct from the profiler allocation epoch ID. The result makes no content, readiness, or write claim. The existing `--derive-region` option still runs its prior bounds-only protocol independently.

## Actual public CLI run

`ACTUAL.json` is 23,851 bytes, SHA256 `b0840c0c0d959228e171562c7351f3a609ad499cb083841c71f825b4692b5cb3`. The command exited 0 in 3.79 seconds (104,112 KiB maximum RSS); the query meter reports 25,670,342 stored bytes and 46,031,018 decoded bytes, 71,701,360 total, over 1.943 seconds. This includes one 1,998,789-byte qualification chunk read as both stored and decoded data. No raw ETO bytes were read.

The navigation row's existing `canonical_parent.qualification_row` carries the chunk URI, SHA, size, and line number, so no user-supplied qualification-manifest argument is needed. The exact result retains the qualification row at `#/lines/10`, the ETO input leaf at `#/nodes/50/inputs/values/0`, allocation evidence at bundle line 106, and epoch birth at physical-observation line 11.

The first CLI attempt exited 1 with `Tensor storage query: artifact SHA/stability differs` while reading the storage-index manifest. A subsequent independent SHA check matched the supplied digest, and the next unchanged CLI command exited 0. The first failure's cause is unresolved and is retained in `ACTUAL_TERMINAL.json`.
