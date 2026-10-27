# Native normal completion and output allocation connection

This is one retained-instance query, not a LeWM-wide result. The reproduction is `run_copy_completion.py`; its actual typed result is `ACTUAL.json`.

## Actual records read

The query decoded the original ProgramGraph (5,273,398 bytes, SHA256 `d70685d1521bf28527fa32beb319fa0f9d66db257b6df3ce2559f013141d5bc6`) and first ExecutionModel shard (7,846,834 bytes, SHA256 `d58eaa17e99f207f5a7780ab6e7904615e9376ab472dfcdb81ce7922a28f6dbc`) with their normal codecs. It did not open or rescan the 321,365,939-byte ETO. The retained ExecutionModel binds the instance `opinst:native:636fde61a45803f11712767bc1cbf0b0ea3de13b14e0b27edc2d6071daea1612:eto:63` to the pinned ETO SHA256 `11960422233619b68d4a42d5b699a34cb57349df04df0bc90b6fd5ef3d8e4684`, node `#/nodes/50`.

The query resolved original canonical invoke occurrence `native-port:capture:ca66b69a8cfc3c1b88e0c22e8ec00d58d735fd016d16edf85e8cf0ac51eb5fc3:9:invoke`, selected successor 0 (NORMAL), and original normal-return occurrence `...:9:return`. It linked all three ordered schema inputs to their original Use/Value occurrences, and the one schema output to its original `NativeOutputRef`, Use, ValueOccurrence, and ETO leaf `#/nodes/50/outputs/values/0`. The non-Tensor bool input remains a ValueOccurrence with no Tensor denotation.

The world interface resolves through original invoke Use `...:invoke:use:3` to normal completion formal `...:9:outputs:1`. The returned `InvokeBoundaryStateEffect` describes this original state continuation; it does not claim a Tensor write. The static Operation retains `effects_complete=False`.

## What the output establishes

At PyTorch revision `cf30153c4c131c8164ee7798e5022d810682e2cb`, the dispatcher calls the selected kernel and sets the RecordFunction outputs only after that kernel returns. The execution-trace observer serializes the outputs supplied to its RecordFunction exit callback. Thus this nonempty output leaf, together with the retained selected NORMAL transfer, supports Dispatcher-level normal completion for the ordinary pinned observer/dispatcher path. A RecordFunction end callback or timestamp alone would not establish it: end callbacks can also run during exception unwinding.

This is not evidence that the kernel wrote memory, copied equal bytes, completed asynchronous work, or made the result ready. Runtime implementation-code identity and exact dispatch branch are not established by this record. The output and `self` input have equal original `ObjectIdentity` references, reported as `(output position 0, input position 0)`. This means the same observed Tensor object reference; it is not a storage epoch, content version, or write/alias proof.

Pinned source references: [ExecutionTraceObserver](https://github.com/pytorch/pytorch/blob/cf30153c4c131c8164ee7798e5022d810682e2cb/torch/csrc/profiler/standalone/execution_trace_observer.cpp), [Dispatcher](https://github.com/pytorch/pytorch/blob/cf30153c4c131c8164ee7798e5022d810682e2cb/aten/src/ATen/core/dispatch/Dispatcher.h), and [Copy.cpp](https://github.com/pytorch/pytorch/blob/cf30153c4c131c8164ee7798e5022d810682e2cb/aten/src/ATen/native/Copy.cpp). The implementation source is a protocol reference; this capture does not establish the runtime code object or which internal `copy_` branch ran.

## Exact ETO port geometry was already retained

The `port-qualifications` receipt for the same source shard contains exact input and output rows. Its manifest is SHA256 `c57875f849794a9b8cb3e2a4494b0f6aadf53d41de209f17b8f698be44b52e71`; the 560-row chunk is SHA256 `455b8631e9b9f9b9669569e8cc07eadfc061c4ff5963728ccb09ced1fbe1c27d`. The input row at `#/nodes/50/inputs/values/0` and output row at `#/nodes/50/outputs/values/0` each carry tuple `[58,36,0,1,4,"cpu"]`, shape `[]`, strides `[]`, and type `Tensor(float)`. These rows are qualified against the same ETO SHA and program snapshot as the original canonical native ports.

The earlier allocation query only consumed the companion `native-tensor-inputs` metadata. That adapter reports `storage_offset=null` because its binding does not expose the field; this is not an absence in ETO. ETO itself supplies offset 0 at both exact port locators. The previous statement that no output-time physical geometry existed was incorrect.

The input port has an independent same-capture allocation join: provider allocation ID 2, CPU, 640 bytes, with birth reference `#/lines/11`. ETO's `storage_id` value 36 is an observer pointer token, not the profiler's allocation epoch ID. The input geometry can be joined to that allocation through the exact original input port, its ETO source locator, and the existing provider-allocation query. The output row has observed ETO geometry and the same ETO tensor/storage tokens, but no direct profiler allocation epoch attachment. Its allocation remains unresolved unless represented as a separately guarded conditional derivation from the pinned `copy_` protocol. No output materialization, readiness, or content version is asserted.
