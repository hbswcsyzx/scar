# LeWM as an external testcase

LeWM is useful because its CEM policy combines Python control, PyTorch module
execution, GPU state, host data, and environment side effects. It is **not** a
special case in SCAR. This document records what a generic graph should be able
to represent when fed the unmodified LeWM command.

## Expected graph regions

* **Control (K):** Hydra setup, episode loop, CEM sample/score loop, solver
  dispatch, environment step and policy call.
* **State (Σ):** pixels, actions, goals, latent tensors, model parameters and
  buffers, RNG state, dataset rows, environment state, and each logical data
  version. A view is a Region over storage; it is not a new content identity.
* **Action (A):** encoder/predictor/value calls (`VAL`), reshape/cast/layout
  (`REP`), allocation and release (`MEM`), copies (`XFER`), module and solver
  dispatch (`CTRL`), synchronization (`ORDER`), dataset/video/logging (`IO`).
  Multiple labels may apply to one invocation.
* **Resource (R):** CPU DRAM, pinned memory, GPU HBM, CUDA stream/event,
  storage file, worker thread and environment process.
* **Contract (Q):** selected action, score/cost, trajectory, required model and
  environment state, RNG semantics, exceptions, and external video/log files.
* **Measurement (M):** wall time, module/operator counts, CPU/GPU duration,
  transfer bytes, memory peaks, synchronization events and confidence/source.

## Optimization hypotheses to test

These are hypotheses, not claims about a run until an execution trace proves
them:

* repeated CEM scoring may expose repeated pure-like encoder/predictor regions;
* constant goal/image preprocessing may be loop invariant;
* repeated H2D materialization may be a residency candidate;
* CPU scalar extraction or synchronization inside a GPU loop may be a deferred
  materialization candidate;
* model buffers and hooks make `.eval()` insufficient to prove purity;
* action gradients (when using a gradient solver) invalidate inference-only
  reuse assumptions.

The generic detector must report an observed dynamic count first, then a
guarded candidate. It must reject a LeWM region when its effects or logical
versions are unknown; it must never pattern match a LeWM class, function, goal,
or model name.

## Observed from the latest generic trace

The fresh one-episode run contained 45,888 events, 20,820 module calls,
22,457 CUDA kernels, 543 physical CUDA memcpy activities and 360 CUDA barriers.
The graph contained 210,581 nodes and 545,653 edges, including 14,609 observed
producer-to-consumer dependencies, 12,635 overwrites, 80 escapes and 41,342
alias relations. Only six physical copies received a unique inferred logical
mapping; 349 signatures were ambiguous and 188 had no host match.

The archived event-level analysis emitted 1,457 candidates. Re-evaluating the
same JSONL with the current detector additionally found 16 generic
`PythonReuseCandidate` records; all were rejected because their Python effect,
callback, or invalidation contract was incomplete. The independent graph pass
reconstructed 1,071 repeated-action candidates from State read sets and
intervening-write indices. Every candidate was rejected because the trace did
not prove complete effects, lifetime/ordering, consumer behavior or measured
guard cost. These are observations about this run, not claims that LeWM has no
optimization opportunity.

## Simplification lessons

1. Repeated CEM module calls are only a hypothesis. A graph must connect the
   exact logical input versions, all writes and aliases, stateful buffers,
   escapes, RNG and ordering before reuse is legal.
2. A `.to("cuda")` call is a representation request, not physical-transfer
   proof. Residency needs a runtime memcpy record, a logical-version mapping,
   destination lifetime, stream ordering and a memory budget.
3. A host scalar or synchronization event is not removable merely because it
   is frequent. The graph must show that no branch, exception, callback or
   later consumer depends on the materialized value or ordering edge.
4. `.eval()` and inference mode do not establish a pure region. Hooks,
   buffers, RNG, module state, environment state and external logging remain
   contract dimensions.
5. A legal transformation can still be rejected. The generic residency
   backend's clean benchmark measured 19.530 ms baseline versus 23.012 ms with
   source/resident snapshot guards, so SCAR selected NO-OP despite 71 cache
   hits and bitwise-equal output.
6. Liveness must remain three-valued. The latest graph has 6,799 LIVE states
   and 2,027 UNKNOWN states; none can be called dead without a closed-world
   contract. This prevents an apparently unused CEM intermediate from being
   removed merely because its consumer was outside the captured span.
7. A discarded call in a source graph is still not automatically removable.
   SCAR's source rewrite only accepts an explicit closed-world and pure/no-raise
   contract; logging, environment updates, exceptions and callbacks remain
   observable actions even when their return value is ignored.
