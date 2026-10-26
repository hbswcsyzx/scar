Declaration-only schedule:13 batches cover all209 remaining metadata-ready entries across99 files. Same-file entries stay together; no oversized/unschedulable file occurred. Original817 groups/100438 calls,243 candidates,33 prior terminal outcomes (26 success/7 unsupported) and1 resumable frontier remain referenced. The old outcomes retain their original producer/capabilities. No graph, CodeType, compile, lower or target ran.

Order is the original call-weight/key order, grouped by first file appearance with original within-file order; batches close greedily at8 files/64 entries/300MB unique declared graph decode. No package/function selection or easier-case rearrangement is used. Exact keys, file groups, source/archive provenance and original graph locators are in BATCH_READ_PLAN.json.

| Batch | Entries | Files | Source B | Graph stored B | Graph decoded B | Historical weight | SP5 context proxy B |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 21 | 8 | 246145 | 15210973 | 131916266 | 1806 | 393027766 |
| 2 | 31 | 8 | 552280 | 33729332 | 289515041 | 924 | 1471208984 |
| 3 | 15 | 8 | 467911 | 22615739 | 196938403 | 334 | 318875399 |
| 4 | 25 | 8 | 250322 | 12273863 | 108256870 | 338 | 345050070 |
| 5 | 12 | 8 | 398591 | 23256917 | 200805893 | 212 | 315965129 |
| 6 | 25 | 8 | 285911 | 19413584 | 168162772 | 168 | 704352592 |
| 7 | 18 | 8 | 308839 | 18860693 | 163684861 | 87 | 410240179 |
| 8 | 15 | 8 | 224814 | 13489638 | 119622428 | 27 | 284384127 |
| 9 | 14 | 8 | 312670 | 14835615 | 130559699 | 20 | 243575757 |
| 10 | 10 | 8 | 333364 | 16817611 | 147921380 | 10 | 196694142 |
| 11 | 10 | 8 | 162586 | 10954363 | 96587322 | 10 | 139544602 |
| 12 | 10 | 8 | 192414 | 11193703 | 98943204 | 10 | 109198471 |
| 13 | 3 | 3 | 157319 | 9426939 | 83428220 | 3 | 83428220 |

Total:209 entries/99 files;3893166 normalized source bytes;222078970 compressed/1936342359 canonical source-graph bytes; historical call weight3949. These are declarations, not currentRun call increments or measured worker I/O.

SP5 context proxy sums each source-graph canonical envelope size once per entry, assuming every entry succeeds (total5015545438B). It excludes new body graphs/wrapper differences and does not predict actual SP5 bytes, compression, success, early stops or improved reader CPU cost. Graph300MB excludes the normal owner auxiliary canonical13890260B; real selected-decode/I/O budgets must cover those auxiliaries, repeated ordinary manifest/archive checks and SP5 readbacks separately.

This JSON is not SourceEntryFrontendPlan or owned source evidence. After validation producer stabilization, actual execution must normally reconstruct four archives/catalog/plan, mechanically derive the same keys from original33 terminal receipts, compare each batch keyset/full denominators and enforce separately approved budgets. No producer freeze or real batch was prepared. Production/index/old gates were not modified.
