# Native Scalar formal versus observed boxed content

Design only, 2026-10-25. No producer change, capture, target, Torch import, gate,
qualification-row read or raw read was performed for this note. The prior gate
remains 264 scalar input ports = 4 roots (2 None, Bool(False), Int(0)) + 260
frontiers. The 257 `ENUM_OR_NONBUILTIN_SCALAR_FORMAL` entries are a union bucket;
their runtime tag / formal-real-kind distribution is **NOT_MEASURED**.

The existing 2,011-byte native-interface catalog contains four signatures. One
declares `Scalar alpha` with observed ETO type `Int`; another declares `Device?`
with type `Device`. These are interface observations, without per-signature
occurrence counts. They establish neither 257 enums nor 257 recoverable numbers.
Current `decode_pinned_scalar` excludes `NumberType` before examining the scalar
tag, so the bucket includes supported-looking union formals as well as genuinely
unsupported formals.

At the fixed provider revision `cf30153c4c131c8164ee7798e5022d810682e2cb`:

- [Schema parsing](https://github.com/pytorch/pytorch/blob/cf30153c4c131c8164ee7798e5022d810682e2cb/torch/csrc/jit/frontend/schema_type_parser.cpp#L79)
  maps `Scalar` to `NumberType`; `ScalarType` is a different enum formal. The
  parser retains real types while exposing some enum/SymInt formals as `IntType`.
- [ETO conversion](https://github.com/pytorch/pytorch/blob/cf30153c4c131c8164ee7798e5022d810682e2cb/torch/csrc/profiler/standalone/execution_trace_observer.cpp#L408)
  starts from the actual IValue tag and retains it in the ordered type tree.
  Its scalar writer emits exact signed int64 decimal and bool tokens; None has
  its tagged sentinel. Double formatting is still insufficient for exact
  binary64, including signed zero/NaN payloads. Containers may truncate.
- [IValue](https://github.com/pytorch/pytorch/blob/cf30153c4c131c8164ee7798e5022d810682e2cb/aten/src/ATen/core/ivalue.h#L906)
  distinguishes Int/Bool/Double/Enum/Device/Sym tags. Earlier conversions can
  erase origin: concrete SymInt and some unsigned values can become Int.
- [NumberType Python conversion](https://github.com/pytorch/pytorch/blob/cf30153c4c131c8164ee7798e5022d810682e2cb/torch/csrc/jit/python/pybind_utils.cpp#L500)
  also lowers dtype, qscheme and layout objects to integer IValues. Thus an ETO
  Int tag proves native boxed Int content, never the original Python builtin
  class or absence of an earlier enum/symbolic conversion. This is a general
  provider limitation, including the existing primitive-formal decoder.

The highest-value bounded extension is an explicit
`SCAR_NATIVE_SCALAR_OBSERVED_ROOT_V2` capability. Retain V1 and default reference
behavior exactly. V2 adds only `formal_kind == formal_real_kind == NumberType`
with actual ETO `Int` / exact signed-int64 JSON integer or `Bool` / exact JSON
bool. Keep the original formal kinds rather than fabricating an IntType or
BoolType formal. The proof is exact **native boxed content at this occurrence**;
the PythonLiteral/builtin_type is its existing representation, not a claim about
the pre-conversion Python object. Enum representation origin remains unknown;
no enum name, Python object or symbolic lineage is reconstructed.

| Actual/formal evidence | Qualification |
| --- | --- |
| NumberType/NumberType + Int or Bool, pinned ordered tag/value | V2 native observed root, independent Version per occurrence/port |
| ScalarTypeType/LayoutType/MemoryFormatType/other enum real formal, even with Int tag | Specific enum-formal frontier; no builtin numerical authorization |
| Device or Enum runtime tag | Specific frontier; no parsing/casting to number or string |
| None or String runtime tag | Existing compatible None/Optional or String formal only; pure NumberType does not admit either |
| Double/Complex/UInt/Sym*, arbitrary UnionType/Any, missing tag, truncated/empty container | Explicit frontier; Tensor, including 0D, remains reference |

No new capture field is required for that bounded boxed-content extension: ETO
already records the actual tag/value and the owned reader binds the exact slot.
If the obligation instead asks for pre-conversion builtin-versus-enum origin,
the existing trace is insufficient. A later unified capture would need an
ordered dispatch operand kind/origin observation at the existing live
DispatchRecorder before its lowering/re-entry, with exact shared-issuer/schema
path/marker provenance. It cannot be inferred from a JSON number or a Python
held-Tensor-only list. Such capture work is outside this increment. Exact Double
support would separately need lossless provider bits, not more decimal parsing.

Implementation boundary: at most four existing sources, no IR/schema change:

1. `scar/trace/native_scalar_content.py`: add an explicit V2 interpretation path;
   preserve the old strict API default, reject enum-real-kind mismatches, and
   distinguish incompatible formal, unsupported tag and representation gaps.
2. `scar/ir/execution/native_port_protocol.py`: own the new capability, replay
   original formal/real kinds and ordered tag/value, keep independent exact
   source/basis/Version/ORIGIN/producer/inventory checks and batch typed query.
3. `scar/trace/native_protocol.py`: project only independently eligible roots;
   reuse existing LogicalValue/ValueVersion/ORIGIN, DataIdentity(VersionRef),
   NativeInputRef, ValueOccurrence and FactSource. ProgramSnapshot stays exact.
4. `scar/trace/native_capture_batch.py`: explicit opt-in and typed classification
   inventory; retain all original denominators/frontiers and verified callbacks.
   No content_validation change is needed: the existing owned typed result works.

One later root-run CPU/offline real-artifact gate can reuse the same saved
capture, ordinary binder and canonical static artifacts across all 260 normal
boundaries; the 261st RAISED boundary keeps its missing-witness frontier. No
target/new capture/G1/OS-interface import is needed. Retain 68,000,000-byte
accounted input ceiling, 120s/outer150s, RSS2GiB, index128MB and output64MB;
source/hash/output checks are separate. V2 adds no input pass or artifact. The
gate must measure actual formal/real-kind/tag buckets, query eligible roots in
one batch, preserve the old four roots/Tensor qualifications, and show distinct
observation Versions for equal Int occurrences. Use one genuine actual-port
source/Version swap through fresh owned checking as the sole negative; if the
needed observed ports are absent, report BLOCKED rather than inventing them.
No general numeric coverage, upstream producer, constancy, state or ready claim
follows from passing that gate.

The old capture's collector-execution-source assumption is retained; consulting
current pinned provider sources does not turn them into historical code witnesses.
