# Original source attachments and shared definition references

## Status and scope

Verified against the retained 272038 capture: explicit source binding, the common
resolver, dispatch association and selected original-source queries passed.
This is a first-stage modeling connection, not an optimization or proof that
the whole program has been modeled. Actual receipts and limits are below.

The existing project composition remains the authoritative project inventory.
Its document, canonical SHA, file indices, typed bodies and schema 1/2 meaning
are unchanged. Dependency evidence is a separate, explicit input to the same
`CompositionIndex`, not a second inventory or an enlarged project root.

## What is referenced

`scar.ir.program.source_references` defines two frozen wire records:

- `SourceArtifactLocator`: the original stored artifact URI/SHA/bytes/schema,
  decoded canonical JSON SHA/bytes, representation, JSON pointer and original
  manifest declaration. A gzip artifact's physical and decoded hashes are
  deliberately separate.
- `SourceDefinitionReference`: original root and provider evidence locators,
  original source-graph definition locator, `SourceSnapshot`, complete
  `SourceContextDigest`, original `OperationDefinitionID` and `SourceReference`.
  Its explicit format is `scar.source-definition-reference.v1`.

There is no inventory `file_index` in normative definition identity. The
version-qualified identity key is the original namespace root, semantic graph
SHA, source snapshot and definition ID. Carrier and root/provider evidence
remain in the full reference and are checked against bound original artifacts.
`ElementReference` remains a project composition view, not a cross-root identity.

For project definitions the graph locator points into the original source-layer
record at `#/payload/semantic/definitions/N`; the namespace and producer metadata
are referenced from that same record. For dependencies it points into the
original parent or continuation graph at `#/semantic/definitions/N`, with
root/provider records in the SHA-pinned continuation. No original ID is renamed.

## Public connection

```python
index = CompositionIndex(
    original_composition_index,
    source_attachments=((continuation_json_path, exact_continuation_raw_sha256),),
    attachment_budget=SourceAttachmentBudget(...),
)
```

Attachments currently require an existing partitioned composition (schema 2),
and the invocation binder requires `witness_mode="same_capture"`. These are
explicit supported input boundaries; old schema 1/2 behavior without attachments
is preserved.

The shared query surface is:

- `source_inputs()`: original composition SHA/inventory receipt plus explicit
  attachment receipts; detects mutation of the original composition document.
- `definition_reference(file_index, original_definition_id)`: qualified project
  definition, while keeping the index only as a local lookup argument.
- `attached_definition_reference(pid, complete_code_key)`: qualified dependency
  definition supported by an original code/source witness.
- `resolve_definition(reference)` and `source_view(reference)`: resolve through
  the bound original root/artifact/namespace, returning defensive copies.
- `attached_code_witness(...)`: original complete captured descriptor,
  descriptor anchor, CodeSourceLink and historical guard provenance.
- `verify_source_attachments(scan, entered_groups)`: compare the existing
  complete strict raw scan with the attachment's entire raw manifest, metadata,
  issues, code/group identities, entry counts and original anchors.

The private loader does not enumerate imports, scan more roots, read current
source files, compile code, prepare source, execute the target or write source
artifacts. It validates SHA-pinned parent/continuation reports, source snapshots,
provider ownership metadata and original graph records. Source graph decoding
uses the shared `source_layers` decoder and its complete existing structure,
source correspondence and context-digest validation. It does not manufacture an
inventory replay receipt. A private bounded graph LRU and compact definition
references and fully validated original definition records avoid copying all graphs
into the composition document. Exact full-reference matches can return defensive
copies of those small records; unknown references still receive original graph
validation. The binder batches demanded project definitions by source file via
`prefetch_definition_references`, and each external file resolves all its demanded
code definitions on the first read. `source_view` still loads the original graph
on demand; actual graph
reads remain measured separately from the unique canonical input budget.

## Binder and dispatch wire versions

With attachments, `bind_source_invocations` emits explicit schema **3** for its
report, bindings and events. Schema 1/2 meanings are retained. In schema 3:

- `definition` is a `SourceDefinitionReference` or null;
- `composition_element` retains the original project-only ElementReference or
  null, for existing typed body access;
- `source_origin` is `INVENTORY` or `SOURCE_ATTACHMENT`;
- source attachment rows carry original descriptor/CodeSourceLink/guard
  locators and the complete CodeSourceLink;
- headers declare the exact reference format and explicit `source_inputs`;
- complete same-capture checks are recorded separately from source proofs.

An external definition with a source graph but no canonical typed body is
source-linked, with `body=null` and
`CANONICAL_BODY_NOT_MODELLED_BY_SOURCE_ATTACHMENT`. It receives no invented
CallSourceAdmission, RegionID, RegionActivation or program-entry root. The
source graph is inspectable through the public resolver; its absence of a typed
body remains a modeling frontier.

`bind_dispatch_sources` accepts this explicit schema 3 through the same supplied
`CompositionIndex`. Project definitions/bodies still receive the original schema
2 checks. External definitions receive exact original full descriptor, group,
CodeSourceLink, root/provider/artifact/snapshot/context and resolver checks.
It emits schema 3 associations with the same qualified definitions and original
binding references. Marker-index schema 1 is unchanged. Marker ancestry stays
`RETAINED_ANCESTOR_CONTEXT`, never a claimed direct Python/ATen callsite.
`query_dispatch_source` accepts versions 1/2/3 and checks the explicit format for
version 3.

## Historical evidence and current guards

Three facts are distinct:

1. The current reader saw the exact retained raw capture bytes and all original
   descriptors/groups. This is checked against the existing strict raw scan.
2. The earlier admitted compiler/source witness matched that capture's code to
   the retained source snapshot. It is reused with its original provenance;
   this reader does not repeat compilation.
3. The continuation recorded whether source on disk matched that snapshot at
   admission time. The reader preserves that observation and marks its scope
   `RECORDED_AT_ATTACHMENT_ADMISSION_NOT_REFRESHED`; it does not refresh it.

A recorded current-source guard failure does not erase a valid historical
capture/source association. It also cannot authorize a transformation of the
current file. Provider METADATA/RECORD prove retained metadata/ownership facts,
not provider version at capture or observer origin of a particular invocation.
All existing whole-model/effect/version/transformation authority flags remain
false.

## Real-artifact acceptance gate and actual results

Use only the original PID **272038** capture and its existing 151-file project
composition. Bind the existing continuation with raw SHA
`c9ff2f87a0e90ee42297501d256d9d24aeeab60273c6172fe692c0323207173e`
and its exact parent raw SHA
`fc97075aa66a92758938ad8416347d895e6b18ef0e454053fc7f9c1a7d2f0424`.
No source preparation or compiler matching is required.

The complete denominator must remain **817 entered code groups / 100,438
invocations / 855 captured descriptors**. Original attachment evidence contains:

- 553 project-scope groups / 12,933 calls, handled by the original project path;
- 243 verified dependency groups / 86,702 calls with original snapshot,
  definition and source witnesses;
- 21 unresolved non-file groups / 803 calls, retained as frontiers;
- 14 calls with a historical source witness for the earlier
  `execution_evidence.py` snapshot and a false recorded current-source guard.

The new connection must preserve these counts, raw family SHA/counts, all
original qualified locators and project document SHA, with no fake external
body/activation. Check output artifact SHA/count denominators and selected public
resolver/dispatch query results using retained evidence, not a second source
prepare. Dependency source graphs total 106 snapshots and 106 graph triples;
the largest saved graph is 111,660,136 canonical bytes, within the explicit
128 MB record default. Unique source-artifact budget is separate from physical
re-read cost. Do not mix this capture with PID 369749.

Attempt01 exited at a runner receipt-path assumption before constructing these
readers; its failure is preserved. The original capture has plain raw files and
needs no archive index. Attempt02 used the correctly located original files and
completed the public connection without preparing or compiling source.

All 817 groups / 100,438 entries = exits / 855 descriptors were preserved. The 243
dependency groups / 86,702 calls are source-only; project body activations remain
5,624. Weighted output is 5,624 BODY_LINKED / 89,864 SOURCE_LINKED / 4,950 UNRESOLVED. The original
composition document and canonical SHA stayed identical.

All 79,592 markers / 109,288 slots remain: 79,106 definition-linked, 10,992 body-linked,
50,658 external-source-only, 6 invocation-only and 480 without a retained ancestor.
Public queries checked all status categories and selected original definitions,
source atoms, snapshots, contexts and real graph pointers. No typed dependency
bodies or activations were manufactured.

Binding took 1355.11s and dispatch association 433.90s. The 106 dependency graph
artifacts were each read once for binding; dispatch validation reused243compact
verified definitions. Input budget charged 2,087,497,217 canonical bytes including
144 auxiliary artifacts; physical reads 241,685,433 bytes. Two selected public full
source views caused two additional measured graph reads. Peak RSS 1,749,776 KiB.
Full records are in `first_stage_source_attachments_20261023/attempt02`.

This gate establishes this source/runtime connection only.
Actual/formal/return routing, function environments, fine effects/state versions,
resource readiness and full software/hardware closure remain separate gates.
