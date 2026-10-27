# Retained source dependency batch

Implemented on main base `b5c1c3cc` in two files only: `scar/analysis/source_dependencies.py` and new `scar/analysis/source_dependency_batch.py`. No collector, CLI, retained port producer or source-return reader changed. These are read-only views over the existing private normal ProgramIndexes and the original qualified model endpoints, not another ProgramGraph or value identity authority.

`SourceDependencyBatchSession(path, expected_sha256=..., budget=SourceReturnBudget()).query_bindings(...)` mechanically selects explicit arguments, independent receivers, normal return inputs and caller-result consumers for the requested original binding ordinals. It reuses body reads/indexes within that session. `query_source_dependency_batch(...)` is the one-call wrapper. The original `argument_origins` defaults still retain the computation boundary; explicit `include_computations=True` enables conservative input navigation. Per-query node/depth/route and pending ceilings remain enforced, with separate batch binding/query ceilings.

| View edge | Meaning |
| --- | --- |
| `OPERATION_INPUT_DEPENDENCY`, `COMPLETION_INPUT_DEPENDENCY` | Original operation Uses may contribute to a result/completion. Carries exact UseRole, relevant StateAccess and original completion edge; does not assert a result-specific function, reference alias, purity or observed effect. |
| `CONTROL_GUARD_DEPENDENCY` | Immediate original incoming guard Use and successor identity; not a complete postdominator analysis or selected runtime path. |
| `ORIGINAL_USE_CONSUMER` | Exact ProgramIndex consumer of the original result Value in its original body and invocation context. |
| `OPERATION_OUTPUT_DEPENDENCY`, `COMPLETION_OUTPUT_DEPENDENCY` | Conservative interface dependence toward original outputs; no claim that every input has an exact data contribution to every output. |
| `ACTUAL_TO_FORMAL_CONSUMER`, `BOUND_RECEIVER_PROJECTION_CONSUMER` | Existing checked language port or independent callable-to-receiver projection, retaining original entry/dispatch conditions. |

Original local binding read/payload and CFG transfer routes remain intact. Unknown binding writes remain frontiers. State and protocol Uses are preserved as separate ports instead of recursively treated as ordinary data. Incomplete operations retain `INCOMPLETE_OPERATION_EFFECTS` and explicitly unexpanded implementation boundaries even when their known interface inputs can be followed. Alternative CFG edges retain their original identity/guard; no loop iteration or runtime return is selected. Fine state, resources, identities, content/ready and transformation permission are not supplied by this navigation.

## Actual retained-model acceptance

`attempt01/RESULT.json`: session **2378 actual exit0**, **0.687781807 s**, peak RSS **131,916 KiB**. Original two-binding/three-body model SHA `4a78314ff0c840f37a694150d44fc4f7adfd798d19d3206c5a09f2fc792afde0`, source capture PID272038. Seven bounded queries completed without truncation; normal readers decoded the three bodies exactly once each: **9,647,490 stored + 20,631,693 decoded bytes**. The full old capture denominator remains 100,550 attempts; this retained model selects two calls, not all attempts.

The second receiver query now crosses the original lookup completion: **19 nodes / 24 routes**, including two independent receiver projections, one actual-to-formal route, eleven completion-input dependencies and one immediate control guard. Binding0 return-input query follows **26 nodes / 38 routes**. Both normal-return consumer queries list original consumer Uses and declared output dependencies. The missing upper entry and incomplete operation effects remain explicit. The model's conditional return interfaces are not observations that the callees returned or that object contents stayed equal.

The compressed query view is **24,161 stored / 525,128 decoded bytes** with exact receipts in RESULT. The runner forbade raw frame/operand/target/syscall streams and live LeWM source opens: zero attempts, zero capture, zero target execution. No source was re-lowered, no CodeWitness replay or full201 publication reader ran, and no GPU/native evidence from another process was attached. Exact production source hashes are recorded in RESULT; original model/body/declaration URIs and SHAs remain authoritative. Existing inputs were not copied or changed.
