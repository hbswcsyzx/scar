# Bounded review: existing composite program APIs and the next bridge

2026-10-23. **Observed source review / Proposed next connection.** No source code,
schema or report producer was changed. No SCAR/IR module, whole inventory,
151/106 source graph archive, OS stream or target was loaded for this review.
The prepared ONE369749 source→marker→SBA gate remains the first priority and
will run only after the shared language producers freeze.

This review checks `COMPOSITE_MODEL_CONNECTION.md` against current code. The
106 repeated StateLocation groups /830 original declarations are results of
root's existing SQL+two-checkpoint audit; they were not re-audited here.

## 1. Exact graph ownership is already represented

`scar/ir/execution/coordinates.py::ProgramSnapshot` contains one `artifact` and
`schema_version`. `snapshot_for` in `execution/snapshot.py` serializes a real
ProgramGraph and records its exact schema/hash/bytes. In
`execution/validation.py::_analyze`, `model.snapshot.artifact.schema` must be
`scar.program-graph`, its SHA/bytes must equal `program_dumps(program)` and its
schema version must equal the serialized graph's version.

`ExecutionModel.snapshot` is therefore one canonical graph snapshot. Multiple
regions/bodies and multiple Runs can be represented **inside that same supplied
canonical graph and its validated execution associations**. `CallActivation`
links a caller OperationOccurrence to a callee RegionActivation; call validation
resolves both against that same `_Context.program`. Internal registries such as
`core_values`, `core_uses`, `regions` and `core_operations` are keyed by that
program's IDs, without an additional arbitrary graph namespace.

Existing `ExecutionIndex.call_activation`, `call_entries`, `formal_route`,
`definition_for_use`, `value_source_pair` and `resource_composition` already query
such supplied, validated local program/execution models. The composition query
is not a multi-artifact body importer. It cannot accept a composition manifest
as a ProgramSnapshot or turn independent checkpoint graphs into one graph merely
by appending their rows. Nor should another mutable global producer/state graph
be created to satisfy its current constructor.

## 2. CompositionIndex's endpoint gap is narrower than “no graph support”

The current composition already offers source definition expansion, original
body loading, canonical operation dependencies and qualified source references:

| Existing API | Actual capability / limit |
| --- | --- |
| `definition_reference` / `resolve_definition` / `source_view` | Original source definition with root/provider/artifact/snapshot/context; external source-only supported. |
| `typed_body(file_index, body_index)` | Exact original ProgramGraph + LoweringMetadata, checked against original graph and CP namespace/locator. |
| `expand(ElementReference)` | Source containment/control or canonical Region/Operation expansion. Not a general Value/Use/location query. |
| `dependencies(ElementReference)` | Canonical OperationID ordered Uses, input/result values, StateAccesses, effects and terminator, or source-level dependencies. |

**Concrete defect/limit:** `ElementReference.__post_init__` currently requires
`body_index` if and only if identity is OperationID or RegionID. Thus a canonical
ValueID, UseID, BlockID or LocationID **with** body qualification is rejected;
without body qualification it passes this particular constructor condition but
is not supported by `expand`. `dependencies` explicitly requires an OperationID
for its body path. This convenience reference is not yet a general qualified
canonical endpoint interface.

That gap does not require inventing endpoint identity. `scar/store/graph_index.py`
already stores `UNIQUE(namespace_id, kind, local_id)` and exposes exact
`{namespace, kind, local_id}` query references. A namespace contains original
artifact/decoded graph identity and body identity; `start_body` checks its
original graph pointer, DefinitionID, entry/source and public codec validation.
`GraphIndex.entity`, `incoming`, `outgoing`, `producer`, `ordered_uses` and `facts`
already return original artifact receipts, JSON pointers and qualified endpoints.
For a full selected graph record, `ProgramIndex` has graph-local `values`,
`locations`, `regions`, `operations`, `producer`, `use_site` and related queries.
Those are local helpers after choosing a valid original graph, not global ID
lookup tables.

## 3. Route reports can qualify both ends, with important scope constraints

`SourceBodyAccess` builds candidates by bare definition from
`(snapshot.path, fingerprint, file_index, body_index)` and rejects a definition
with multiple candidate bodies. Ambiguous bare definitions are excluded from
`selected`; `receipt()['bare_definition_conflicts']` preserves that frontier.
The receipt's actual mapping is `namespaces[definition.wire]`, holding original
namespace, file/body view, graph/inventory/metadata locators. The summary field
`canonical_namespaces` is a count, not a replacement identity map.

`ArgumentRoute` carries current caller/callee InvocationKey, caller/callee
DefinitionID+RegionID, caller OperationID/actual UseID/actual ValueID, callee
formal ValueID/ValueSlotID, original anchors/source and rule conditions.
`CompletionRoute` carries the caller normal result and callee payload Use/Value
plus callee `post_world`. `InvocationReturn` and thin templates keep their own
original definition/region and reference IDs. These fields, the bound source
report and the receipt namespace map are enough to resolve the existing positive
route endpoints to their original graphs **when that map is unique**. The
accepted old272038 endpoint audit already exercised this for its retained ports;
it is not evidence about current369749 invocation endpoints.

InvocationKey itself contains process/thread/invocation, not RunID. Consequently
cross-report lookup must bind the original report/input receipts and its explicit
Run, then interpret its InvocationKey. Do not merge rows from two captures by
InvocationKey alone or interpret the same PID as the same process incarnation.
The current prepared gate first creates a new369749 source report and checks
current independent SBA raw counts. Static source references may be reused under
guard; old route rows and old counts are not transplanted.

## 4. World/state composition is still a real modeling frontier

In `call_operand_routes.py`, `world_use` is checked to have STATE_CONTENT role
and a StateVersionValue. Positive ArgumentRoute records describe explicit data
arguments; they do not currently publish a caller-world→callee-world state-domain
instance relation. The completion rule copies `root.post_world` from the callee
InvocationReturn. It does **not** prove that this is a caller post-world version
or identify the corresponding StateLocation across two separate body graphs.

The root audit's repeated coarse-world local IDs therefore require both rules:

- Equal LocationID text in different original namespaces remains two original
  declarations. It is not a merge key or proof of equal runtime state/version.
- Different LocationID text is not a disjointness proof. Opaque Python/native/
  external state may overlap; absence of a proven correspondence remains
  may-alias/unknown rather than removing dependency obligations.

Static StateVersionValue.location is graph-local; a dynamic state occurrence
also needs its bound current activation/operation and state domain identity.
Neither a namespace lookup, a source call, a weak object token nor a recorded
callee post_world alone supplies this relation. Existing local execution flow
and call validators can check declared actual/formal/state ports within their
real ProgramSnapshot, but no such declaration should be synthesized for these
separate coarse worlds from text equality.

## 5. Minimal next bridge, after the current gate

**Proposed; no implementation in this review.** Add a bounded endpoint-query
connection at the existing CompositionIndex/GraphIndex boundary, not another IR:

1. Accept the existing GraphIndex qualified reference shape. Bind its namespace
   to exactly one original composition body/CP locator and kind-specific local
   table. File/body indices remain private views. The namespace/receipt is the
   normative lookup input.
2. Resolve a route record from its SHA-pinned report shard/line and current Run.
   Use `source_body_access.namespaces` with caller/callee definitions to qualify
   actual/formal/result/payload endpoints. Reject bare-definition ambiguity,
   namespace mismatch, missing body, wrong endpoint kind or stale scope.
3. Return the original route plus the original endpoint references/locators and
   all original conditions. Query GraphIndex.entity/ordered_uses/producer/facts,
   or load only the selected original body via typed_body when actual records
   are necessary. Reuse ProgramIndex locally; do not copy/rewrite producers,
   values, locations or region IDs.
4. Keep any absent world/alias/ready relation as an explicit unresolved endpoint
   obligation. Do not publish a cross-world state equality or dynamic tensor
   identity merely because data argument endpoints resolved.

Extending ElementReference to admit all canonical IDs is one possible local
convenience change, but is insufficient by itself and should not become a new
global identity. The more direct next public operation is a qualified canonical
endpoint resolver using the existing GraphIndex reference. A composite query
can then attach current route references through that resolver, preserving the
original source/report/graph owners.

## 6. Small acceptance boundary

After ONE369749 succeeds, select actual positive argument and completion records
from **that** current report, plus their entry/environment ports. Check current
Run and report/shard SHA, both original body namespaces, exact formal/actual Use
ownership and values, return payload/normal result, and all original conditions.
Use a few selected original endpoints/CPs and the existing index; no full151/106
source replay or unified-graph copy is needed. Check malformed/unqualified or
wrong-namespace queries are rejected through the same resolver boundary.

Preserve the already audited repeated-world declarations as distinct qualified
records; report that cross-domain identity and write/version relations remain
unproved. Demonstrate that neither equal world text nor different local IDs
causes an automatic alias/disjointness result. This validates endpoint navigation
and scope conservation only. Single-snapshot ExecutionModel validators continue
to apply to real owned snapshots, not a fabricated whole-program ProgramGraph.

Only after those source/current-call endpoints are connected should the next
necessary state/world instance correspondence and logical provenance evidence be
specified. “Uniform queryable composition”, “correct state dependency graph” and
“complete program model” remain separate acceptance statements.
