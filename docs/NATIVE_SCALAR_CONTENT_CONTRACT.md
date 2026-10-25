# Pinned native scalar decoder and owned integration boundary

2026-10-25. The pure helper is implemented in
[`native_scalar_content.py`](../scar/trace/native_scalar_content.py). It does not
read raw captures, modify native replay, create graph records, or authorize
native-port evidence. Whole-dispatch integration and scalar content correspondence
remain OPEN. Tensor ReferenceValue/ObjectIdentity meaning remains unchanged.

The API is:

```python
decode_pinned_scalar(provider_revision, provider_type, formal_kind, value,
                     *, formal_real_kind) -> ScalarDecode
# ScalarDecode(literal: PythonLiteral | None,
#              builtin_type: str | None, frontier: ScalarFrontier | None)
```

This is a local interpretation result, not another persistent IR. No caller
boolean, metadata field or returned literal grants ownership. The owned producer
must replay the original node/slot, path, schema, Run, occurrence and ordinal.
The helper preserves an exact original `PythonLiteral` or a concrete frontier.
It never coerces strings to numbers, bools to ints, enums to builtins or symbolic
values to concrete data. Its public result constructor checks internal type/kind
consistency, without granting authority to independently constructed results.

The content contract is derived from official sources at the exact provider
revision `cf30153c4c131c8164ee7798e5022d810682e2cb`, rather than sample payloads:

* [ETO serializer](https://github.com/pytorch/pytorch/blob/cf30153c4c131c8164ee7798e5022d810682e2cb/torch/csrc/profiler/standalone/execution_trace_observer.cpp#L63)
  emits signed integer decimal and bool tokens; None reaches the tagged sentinel
  fallback. Finite Double uses decimal formatting without a binary64 round-trip
  guarantee; nonfinite Double becomes text. Both remain frontiers, including
  apparently simple finite values. String escaping is reviewed at
  [the same pinned source](https://github.com/pytorch/pytorch/blob/cf30153c4c131c8164ee7798e5022d810682e2cb/torch/csrc/profiler/standalone/execution_trace_observer.cpp#L733).
  The helper accepts only ASCII strings; non-ASCII byte/char interpretation is
  unestablished. Container serialization can truncate, so a container leaf is
  never converted into scalar content.
* [Pinned IValue declarations](https://github.com/pytorch/pytorch/blob/cf30153c4c131c8164ee7798e5022d810682e2cb/aten/src/ATen/core/ivalue.h#L550)
  distinguish exact scalar tags from symbolic tags. Concrete boxing can erase
  earlier symbolic origin; the decoder claims only content of the declared
  provider scalar at this slot, never the original Python object's type.

The small schema API check also establishes that `argument.type.kind()` alone
cannot exclude enum or SymInt formals. `ScalarType` exposes `IntType` there but
`ScalarTypeType` in `real_type.kind()`. For SymInt, both printed type strings can
be `int`, while `real_type.kind()` remains `SymIntType`. Integration must retain
the actual real kind from the existing pinned parser, traversing the exact
formal container path without losing that information. Plain type strings are
insufficient. In particular, the old native schema `_argument` text fields do
not themselves satisfy this new helper's real-kind input contract.

| Provider leaf | Required formal kind and real kind | Exact local result |
| --- | --- | --- |
| None with original `<None>` string | same `NoneType` or same `OptionalType` | original NONE literal |
| Bool with exact bool | both `BoolType` | original BOOL literal |
| Int with exact int in signed int64 range | both `IntType` | original canonical decimal INT literal |
| String with bounded exact ASCII str | both `StringType` | original STR literal |
| Double, including finite values | both `FloatType` | precision/nonfinite/stringified frontier |
| Tensor | any | existing reference branch; scalar frontier only |
| enum, Sym*, Device, unsupported or container leaf | original kinds retained | specific frontier |

For a None observation, preserve the original optional kind. For a non-None
element of an optional/container, the owning schema replay must select the
actual primitive leaf kinds. Missing leaf-kind evidence is a frontier; no text
parser, schema default or neighbouring slot replaces it. A JSON null is not the
pinned None sentinel. An unsupported or over-budget value remains in the caller's
slot denominator with its original path/type and the helper frontier.

Content representation and evidence ownership are separate obligations.
Existing `ValueGraph` already has `LogicalValue`, `ValueVersion` and
`ProvenanceRecord`; `ExecutionModel` already has occurrence-scoped
`ValueDenotation(DataIdentity(VersionRef))` with `NativeInputRef`/`NativeOutputRef`
and exact `FactSource`. These can express independent lineage identities and
qualified content provenance. The content need not be embedded in ValueVersion:
an independently checked typed evidence reference to the immutable provider
fact may be sufficient. This helper does not introduce a duplicate content
catalog or recommend adding literal bytes to free-form metadata.

The currently implemented owned native resolver handles ObjectIdentity held
Tensor references only. It does not independently validate scalar DataIdentity,
per-occurrence scalar lineage or exact decoded content. `content_validation`
currently reports successful native correspondence through its reference branch,
and native queries do not expose an owned typed scalar observation. The unresolved
work is an owned scalar resolver/query contract over the original facts and
existing VersionRef/basis. This is distinct from a requirement to add literal
fields directly to ValueVersion. A future review should first determine whether
that existing fact-reference path suffices; any necessary typed field change
must identify the unexpressible relation and normal validation/codec consumer.

`LiteralEvaluation` is a ProgramGraph declaration on an original OperationResult
or InvokeLiteralResult. It is not indexed by ValueOccurrence/VersionRef. Native
canonical signatures can be shared by multiple invocations with different
values, so an observed dynamic scalar must not become ExactLiteralOrigin or a
shared static LiteralEvaluation. No such attachment is made here.

Future integration must keep the original ProgramSnapshot, Operation, ordered
Value/Use and NativeBoundary identities. Each occurrence receives an independent
LogicalValue/Version; equal decoded contents do not merge occurrences. A native
output's provenance must name the exact existing ETO OperationInstance and
replayed output port. A native input is an observed root with unknown upstream
producer, never an output of the operation that consumes it. Exact FactSource,
Run/body/artifact, direction, ordinal and actual ValueOccurrence must be checked
by the owned resolver. The pure helper cannot enforce those joins and does not
pretend to do so.

Only small synthetic metadata/API and existing literal codec checks are allowed
for this helper task. No raw window, full dispatch import, target execution,
CodeWitness compilation or large gate is run. Whole-dispatch reference modeling
can retain all scalar frontiers and integrate this helper later under root
review; an exact local scalar decode alone closes no content/alias/state/ready
or complete-first-stage obligation.
