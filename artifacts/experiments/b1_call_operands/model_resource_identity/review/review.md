# R1 execution associations — independent bounded review

Status: **FINDINGS**, not a product/full-model acceptance. No tracked file was edited and no pytest/full/workload/GPU run occurred.

Read root-authored `model.py`, `snapshot.py`, `validation.py`, `flow.py`, `query.py`; read resource validation only to understand the integration boundary. The 13-case bounded script is stdlib plus existing SCAR/manual fixtures, Python 3.14.7, `torch_imported=false`. Its six module hashes were unchanged between start and finish. Exact hashes and command are in `command.json` / `results.json`; no fixes or subsequent runs overwrite these observations.

## Concrete findings

### F1: segment evidence may name another process in the same run

`validation.py:236-253` checks `segment.ingress.source.run` but does not compare a non-None source process with `activation.process`. The `UnresolvedHostThread.point` similarly gets internal point validation but no owner-process/run comparison.

Observed: both `same_run_foreign_process_ingress` and `same_run_foreign_process_unresolved_thread_point` return `valid=true` with no scope issue. Each points to a genuine second ProcessInstance in the same Run; the segment still belongs to the first process.

Minimum correction: enforce owner run and, whenever supplied, exact process incarnation on these segment-owned evidence points. A None process remains an explicit unknown rather than being assigned an invented process. Missing thread must remain a gap and grant no thread ordering.

### F2: a known old cross-block result can be downgraded to an observation gap

`flow.py:118-135` rejects old producers when the producer is in the consumer's own block visit. At `flow.py:162-188`, entering a new defining block kills the old result to plain None. If that new producer observation is missing, a later consumer in another block loses the known required producer visit.

Observed: the existing loop fixture reaches header visit 5. Remove only `5.read.counter` and its result observation; give `5.compare` an explicit Unresolved input. The exit at visit 6 is then explicitly rebound to `3.counter.value` (same static ValueID, previous header traversal). Validation returns `valid=true` with `definition_unobserved` instead of rejecting the known old incarnation. The observed path includes the newer defining traversal, so missing its ValueOccurrence does not make the old origin compatible with that traversal.

Minimum correction: preserve the current defining visit/operation coordinate as an obligation even when no ValueOccurrence row was captured. Distinguish “current row unknown” from “no path establishes which defining visit is current”. This is not a request to fabricate the missing ValueOccurrence or a second producer table; derive the expected coordinate from the canonical block/operation and recorded traversal.

### F3: multiple initial-entry roots silently reuse one activation

`flow.py:75-103` requires an InitialEntry segment to have some root at the region entry, then exempts every root at that entry from `visit_ingress_unobserved`.

Observed: append a second complete visit to `loop.entry` (fresh visit/Use/value identities) in the same initial segment/activation, with no incoming transfer. Validation is true and has no missing-ingress gap. This static entry has no CFG predecessor, so it cannot be a hidden ordinary backedge.

Minimum correction: distinguish the single activation initial ingress from additional disconnected roots. An impossible second initial entry is an issue; a permissible but unobserved predecessor must be an explicit ingress gap. Never infer that all roots named entry are independent initial executions of one activation.

### F4: two public malformed-input paths escape as AttributeError

- `ExecutionIndex.state_at(None)` enters `check_point`, assumes `.operation`, and raises AttributeError.
- Allocation validation with `value_graphs=[]` enters `_external`, assumes `.get`, and raises AttributeError.

These do not grant proof, but the public validation/query boundary should reject malformed input deliberately. Validate point variants and supplied catalog shape before dereferencing; do not mask real unknown foreign-key diagnostics behind a broad catch.

## Checks without a new finding

- Unknown transfer source/target both report `transfer_endpoint`; no crash in those cases.
- Allocation with correct supplied ValueGraph succeeds conditionally. Wrong declared byte size reports `external_snapshot`; absent catalog is `external_graph_unavailable` gap, not identity/absence proof.
- `_external` cache key includes digest/schema/size/family, so same digest with changed metadata does not inherit a previous success. Root's separate exact-hash/different-family/many-to-many tests were read, not rerun here.
- Snapshot comparison hashes canonical program bytes, checks byte size, schema family and program schema version; URI is not opened or used to guess identity.
- Suspend uses a new segment in the same activation, and transfer/resume declarations must agree. Resume state ports are target canonical BlockArgument occurrences; no old shared-state snapshot is presumed.
- INVOKE/BODY_DRIVE common AFTER state is deliberately unknown; actual outcome state comes from the selected successor formals. No success result is synthesized from absent completion.
- `source_runtime_verified` and `transformation_authorized` remain false, including for structurally valid reports with evidence references.

## Query boundary / wording

DefinitionLink currently contains exact coordinates (OperationOccurrenceID, UseID, ValueID, ValueOccurrenceID, producer origin), not original Use/Value objects. `occurrence()` exposes detached canonical operation contents, so the producer/Use can be followed without constructing another graph. The method wording “Original Use/definition” should describe coordinates or expose a clear derived record accessor if callers require those records; this is an API clarity point, not a proven incorrect edge. Detached result copies are intentional and the existing test protects that behavior; this review does not demand mutable original-object aliasing.

## Scope

The concrete script does not establish native capture/source correctness, actual content equality, physical resource denotation, device ordering, readiness or whole-program completeness. It does not test every malformed graph/catalog. Root may fix the identified paths and run its owned regression/component gate; closure should bind final hashes separately and preserve this initial report.
