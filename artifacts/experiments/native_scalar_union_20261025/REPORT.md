# Native boxed scalar union V2 actual result

Root session68758 confirmed terminal exit0. Gate elapsed21.848741628986318s;
GNU wall22.37s, maximum RSS738128KiB, exit status0. The immutable attempt01
freeze is748696f8e349b5431e1a1fa9bebc5447fad154dbe68a3dd1ae8feb015796fa13.
The four-source candidate, runner, original outputs and actual stdio are kept.
No new target, capture, G1 import or OS-interface model was run.

The same owned CPU Run
`capture:0819d8df4eb6d0a8e5990bdeeac4b5b1c88c5aa760d21c80904dfbef6ad28e44`
retains261 dispatches,260 normal modeled boundaries/two verified shards,
2332 companion rows and3095 metadata paths (516 associations/2579 boundary
frontiers). The RAISED dispatch frontier, one missing parent edge/two affected
nodes and whole-tree-closure=False remain. Exact original ProgramSnapshot and
interface artifacts were reused. These counts do not share a denominator with
other source-call experiments.

The same-run owned replay measured264 scalar inputs =260 observed roots +4
frontiers. The old257 union frontier is now observed as256 NumberType/Int ports
and one Device port. It was not a count of257 actual enums. The prior four
observation footprints (2 None, Bool(False), Int(0)) are preserved, with the
same observation VersionIDs/source/occurrences and a new exact projection
artifact. No content-based merging occurs.

| Formal kind / real kind | Actual ETO tag | Count | Result |
| --- | --- | ---: | --- |
| NumberType / NumberType | Int | 256 | observed native boxed roots |
| OptionalType / OptionalType | None | 2 | observed roots |
| BoolType / BoolType | Bool | 1 | observed root |
| IntType / IntType | Int | 1 | observed root |
| DeviceObjType / DeviceObjType | Device | 1 | nonbuiltin-formal frontier |
| IntType / SymIntType | Int | 2 | symbolic-content frontier |
| ListType / ListType | GenericList[] | 1 | container frontier |

Only explicit `SCAR_NATIVE_SCALAR_OBSERVED_ROOT_V2` adds the NumberType branch;
V1 decoder default/replay and reference defaults are retained. Original formal
kinds are kept. Each eligible occurrence/port has its own LogicalValue/Version,
ORIGIN(producer=None), NativeInputRef, ValueOccurrence and exact ETO FactSource.
Typed queries perform one exact scope/projection check per shard then indexed
ordered lookups. The pure syntax/API preparation imported no Torch and ran no
owned producer. It is separate from this actual gate.

The sole negative used two actual NumberType/Int observations, each literal1:
sequence2 `#/nodes/12/inputs/values/2` and sequence3
`#/nodes/21/inputs/values/2` in the original ETO artifact
SHA09c7c992081de904b3d3e9037f566a8eb1e11075f56d65964e409630d7009b47.
Their source and VersionRefs were exchanged while retaining original bases and
occurrences, then codec-roundtripped. Fresh evidence from the same live owner
and actual prepared token rejected both `native_scalar_source` and
`native_scalar_identity`; this was not an old seal/scope refusal. Distinct roots
do not assert different underlying contents or upstream producers.

Tensor qualifications remain776 ports =520 held +256 unresolved; C remains520
qualified +256 gaps. The accounted completed verified input phases total
67,598,442B with pending0; control metadata864,842B. These preserve the original
68,000,000B/1,000,000B limits; inherited binder pass accounting is not kernel I/O
measurement. Limits120s/outer150s, RSS2GiB, index128MB and output64MB were not
raised. Two source/runner SHA passes separately read13,279,264B.

`builtin_type` is a normalized literal representation, not the original Python
class. Pinned NumberType conversion can lower enum-like dtype/qscheme/layout
objects to Int; earlier conversion/symbolic origin remains unknown. No runtime
NumberType/Bool case or general numeric/String coverage was demonstrated here.
Double/Sym/enum-formal/Device/container unsupported cases stay open. Native
upstream producers, Tensor contents, state/effects/alias completeness, readiness,
whole model and the historical collector-execution-source assumption remain
OPEN. This gate does not upgrade old40k/1901 evidence or authorize optimization.
