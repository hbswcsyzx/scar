# Connect original source entries to real lowerer returns

Design only at main38855155. No raw, source-graph decode, target/package import,
lowering or compilation. Module entry belongs to the other agent. The existing
6 SOURCE_VERIFIED DefinitionIDs/context records and readonly4-key CodeWitness
are inputs, not six published bodies; original9groups/271calls stay intact.

Implementation amendment approved by root: the first slice now includes a fifth
file, source_layers.py, solely for its original dependency graph reader's exact
snapshot-locator discriminator. Original admissions supply a direct original
artifact; continuations keep the existing complete PARENT locator. The helper
previously accepted only PARENT. Unknown/partial locators or declaration schemas
still reject; all existing canonical/hash/flag/root/context checks remain. No
fake parent, continuation, trust flag, CP1 or CP3 is constructed. The frozen
source set uses current main bytes including root's newly applied native4 files.

## Decision: a qualified entry resolver, then the existing worker

Implement the first four-file slice below. It must feed one actual definition
into the normal sealed lowerer and retain an owned return; another CLI sidecar,
repeated admission, continuation with nothing missing, or a synthetic project
inventory is not the proposed advance. Publication/binding follow as separate
explicit transport changes; do not promise an end-to-end connection in four files.

1. **source_attachments.py**: add explicit
   `SourceAttachments.from_admissions(path, *, expected_report_sha256,
   project_root, budget)` for the already-published admission schema1. Keep the
   current continuation constructor unchanged. Reuse its snapshot/provider,
   root-ID, graph-declaration, digest, source-atom and DefinitionID validators.
   Graphs remain lazy, one original file at a time. This mode has no inherited
   parent or continuation source_guards: never fabricate those fields or a
   current-source/Run verification bit. It resolves original historical source
   facts; capture applicability still requires a genuine later strict scan.
2. **new source_entry_catalog.py**: one read-only `SourceEntryCatalog` over
   explicitly pinned project CompositionIndex inputs, admission/continuation
   owners, and `CompilerWitnessArchives`. Its metadata catalog keeps all9groups,
   weights/descriptors/anchors and all retained frontiers. Six rows are candidates
   until their source graph membership has been checked. `resolve(key)` returns
   a `ResolvedSourceEntry` analysis view holding the existing
   `SourceDefinitionReference`, actual original semantic definition, exact source
   view, CapturedCode/CodeSourceLink and selected readonly archive receipt.
   `prepare(entry)` uses archived `store.text(snapshot)`, the original source
   graphs and one AST/symtable parse, then the existing PreparedSource constructor
   and `seal_for_lowering()`. No prepare_source or dependency reconstruction.
3. **source_language.py**: add a strict `SourceCodeEvidence.from_entry(...)`
   path, while retaining the old CompositionIndex constructor unchanged. Accept
   the exact catalog/resolved-entry types, not duck typing or a supplied witness
   dictionary. Independently require source graph/definition/source-atom identity,
   the original full captured descriptor and link, recorded flags/optimize levels,
   exact explicitly admitted store, `resolve(..., allow_compile=False)` and
   `describe_code(code)==captured`. Existing lowerers still consume the same
   SourceLanguageOptions/SourceCodeEvidence type.
4. **source_frontend_worklist.py**: a version2 plan/worker mode enumerates that
   catalog, not just inventory files/bodies. Preserve version1/default behavior.
   Dispatch and cache by full source-entry/file identity, never invented fi/bi.
   Retain the existing automatic call-weight ordering, capability checks,
   per-file session reuse, total/per-body budget and terminal accounting. A
   dependency record is not converted into a fabricated DefinitionInventory;
   use the original resolved definition/code correspondence and exact source
   span to select the normal lowerer entry. Preserve missing entry-kind adapters.
   A producer-owned `_lower_and_capture_return(session, entry, ...)` performs the
   normal `session.lower(... STRUCTURED_ENV, expand_candidates=False)` itself
   and immediately binds its actual return to an active construction owner.
   It accepts no caller-supplied LoweredSourceBody or serialized return receipt.
   The owner holds the same graph/metadata/interface/language objects, exact
   source/code basis, actual operations_emitted and work key before serialization.

The catalog is lookup/analysis transport, not a new definition or graph owner.
Project entries resolve through CompositionIndex.definition_reference(),
resolve_definition() and source_view(); these existing methods validate original
project graph membership and can address a monolithic source view. Dependency
and runtime entries resolve through the direct admission reader in their original
namespace. A project fi/bi may remain an optional legacy **view**; an external
entry has none. Catalog identity uses SourceDefinitionReference.identity_key()
plus the selected captured/compiler variant and original owner receipt. Same
text, local ID or qualname across two roots does not merge entries or variants.
The tool4, frozen1 and module1 remain explicit non-dispatch rows, not deletions.

## Per-entry origin and actual checkpoint contract

SourceCodeEvidence currently hard-checks CompositionIndex and reads only
inventory_component("call_sources"). Its witness also unconditionally emits an
`inventory` origin (source_language.py:L29-50). Extending only the worklist would
therefore misstate external evidence. New evidence uses an explicit versioned
source-origin discriminator: PROJECT_INVENTORY retains the current basis;
DEPENDENCY_ADMISSION names the original admission record, captured/link locators,
root/provider/source-graph locators and qualified definition. Runtime stdlib is a
provider role under that original source root, not a fake project file. Archive
selection uses complete store receipts, not a union manifest or path guessing.
The serialized SourceProgram5 language evidence must retain this origin and be
reproduced by the ordinary reader; no runtime CodeType/function instance is granted.

Do **not** label the owned return CP1: InventoryPartitions.checkpoint() explicitly
rejects EXTENDED_PROTOCOLS in CP1 (L369-377). Do not relabel current CP2 as a known
construction count either: CP2 deliberately records unknown cost and points to
an independently admitted SourceProgram5 (L378-387). Keep both contracts.

Version the existing worker's **source-frontend-lowered-return record to2** for
this handoff. It references the unchanged normal SourceProgram5 graph/metadata/
interface/structured/language fields and records the exact qualified entry,
per-entry origin, actual integer operations_emitted and producer/input receipts.
The in-process owned return may be passed directly to the publisher only while
its active owner and object identities still match. Disk JSON cannot recreate
that live owner. Keep the normal published checkpoint **CP2 with cost UNKNOWN**:
the actual-return work receipt supplies budget/accounting provenance, not a new
canonical-body cost authority. No CP3 is needed for this slice. A resumed SP5
still undergoes ordinary independent admission; it does not fabricate a fresh
owned return or CP1. Serialization failure preserves returned metadata and the
actual charged work; graphless returns are UNSUPPORTED, not fabricated bodies.

## Following slices: ordinary publication/reader, then call binding

**Publication slice** changes source_program_publication.py and the existing
body transport/reader in inventory_partitions.py, with the necessary composition
reader adapter. Current plan_source_body_publication() finds the original project
snapshot, fi/bi and DefinitionInventory (L119-165); _publish_source_programs() repeats
those source/context/CAS checks (L354-405). The new route must explicitly accept
a resolved original entry and owned return, independently run the normal SP5
STRUCTURE/AST/readonly-CodeWitness validators with that module's archived text,
then publish only original artifact/checkpoint references. Preserve project
ADD_GRAPH/REVISE_GRAPH behavior and CAS unchanged.

For external entries use a versioned qualified body-attachment index, keyed by
the original SourceDefinitionReference and expected parent index/root/hash.
It is an original-body lookup/CAS transport using existing graph/artifact/
representation/pointer/body/kind/local_id identities, not copied source IR or a
second graph authority. The public reader must return the same existing typed
body bundle and verify original snapshot/context/namespace, graph digest, exact
interface and source/code evidence. Never allocate an external entry a project
fi/bi, append a fake FileInventory, rewrite admission graphs or claim this turns
G1's monolith into partitioned composition. Keep old readers strict; the qualified
body index and per-entry origin require an explicit new reader/version, while
the CP2 field/cost rules stay unchanged.

**Binding slice** changes the ordinary source_invocations.py/body-access adapter,
using the same catalog/body reader. Today local bindings locate definitions and
bodies through project snapshots/files and final CallSourceAdmission (L475-546),
and SourceBodyAccess.bundle() assumes composition fi/bi (L473-520). Add an explicit
qualified-source binding report version4 instead of claiming schema2/3 or loosening
the partitioned guard. A fresh bounded public call scan and genuine coordinates
must verify the original artifacts/Run/process/anchors; no ownership object is
restored from G1 JSON. Resolve each body through the entry's original qualified
definition and checkpoint. Preserve all271 invocations/parents and missing
interfaces; classify actual body-linked/source-only/unresolved outcomes only after
the public body reader and applicability checks. Source matching/body linkage
does not close function environment, actual/formal or return value routing,
ordered runtime data/state/content, alias/object identity, native occurrence or ready.

Thus existing SourceAttachments continuation-only input, CompositionIndex's
partitioned-only attachment registration (L708), SourceCodeEvidence's inventory
dependency, worklist inventory-only enumeration, publisher fi/bi and body-access
fi/bi are separate real barriers. None is solved by changing a CLI boolean.
Compiler witness acquisition wrappers also enumerate inventory VERIFIED links;
the first slice needs no such change because this gate already has the four
required readonly module keys. A missing exact key remains a frontier.

## First implementation gate and current design evidence

After approval of the four-file slice, use the saved admission manifest SHA
`0bdaa8329394beef8ecb04592cbfeec276550376421acce3eda93fc3f26dd416` and
readonly witness manifest SHA
`8c16a942e037c6a3a5357043e291df521ba67a809ed5d3770c98d663b5057c71`.
Catalog all9/271 and six candidate definitions; dispatch at most **one** by the
existing generic call-weight policy, not a name list. Lazily validate only its
needed original graph, use its saved source/context and CodeType, run the normal
lowerer once, capture the genuine owned return, then use the ordinary SP5 structure
reader with exact archived text. Actual body support and operation counts are
unknown. Keep the other entries/frontiers NOT_ATTEMPTED/unchanged and publish no
new runtime binding or main-source count in this first slice. Then feed that
same return/artifact to the publication slice; do not re-admit/re-lower it merely
to move to the next API.

Suggested first-slice limits: one dispatch/one source file, existing current
capability policy frozen,4000 operations/body and total,64MB record/128MB stored
output,≤128MB selected source/provider graph decode,readonly4-key archive ceilings,
180s external wall. No raw scan, compile acquisition, source re-preparation,
native/OS import or target in this first lower/reader gate; a later binding gate
is separately bounded by512calls and the genuine public source scan. Plans and
failures retain the full denominator. Success of one owned return is not body
publication or complete phase1; count those only at their actual consumer gates.

Current design read only small saved headers/API code, not graphs or archives'
payloads. Symbol discovery used rg; its internal source-read bytes were not
metered, so strict total code-I/O≤1MB is not claimed. No metadata/raw/graph/lower/
compile/target gate was run for this design. Module/frozen/tool-origin work and
all first-stage completeness obligations remain separate.
