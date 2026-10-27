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

## Allocation connection remains open

The existing allocation bridge resolved the exact original `self` input port (`NativeInputRef`, row 53, path `[0]`) to provider allocation ID 2, CPU, 640 bytes. Its allocation birth reference is the retained tensor-physical record `#/lines/11`. The input geometry is float32 scalar (4-byte bounding span); storage offset is not observed, the allowed offset range is 0–159 elements, and no unique StorageRegion is derived.

There is no output-time physical geometry/allocation epoch for `#/nodes/50/outputs/values/0`. The input allocation query therefore remains attached to input0 and is not transferred to output0 based on their shared ObjectIdentity. Linking output0 to that allocation would require a qualified same-point output epoch or a sufficiently qualified storage-stability contract plus runtime dispatch/implementation evidence. Neither is present here. No output allocation, region, materialization, readiness, or content version is asserted.
