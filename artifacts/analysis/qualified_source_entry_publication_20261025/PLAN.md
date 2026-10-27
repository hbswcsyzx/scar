# Qualified external-entry publication → ordinary invocation binding

Design only; no production edits, graph decoding, raw reads, lowering or gate execution.
This is a source-body association increment, not callable/environment/effect proof.

## Input and current hard boundaries

Use the immutable CLI terminal
`model_run_source_entries_gate_20261025/model/attempts/1792962847383051508-1430458/terminal.json`
(17,280B; SHA256 `c4b3bbbf287175b06113dea7dc2d3a72f212d86bed51f5da8dcd95d6228ef917`).
Mechanically enumerate its successful `products.source_programs`; never select a function name.
The single original SP5 URI ends in `source-entries/worker/attempt-00001/source-program5.json.gz`;
stored 299,377B/SHA `3e15a2b1a82bb61a6e346727c43c79d9945522ed11b43b32a9913d07c5b7e1d9`,
decoded 2,893,898B/SHA `59372527a18ff9400c5c4a2592bae1aded452f85adfbc7d9122538e5bb94f13a`.
Keep that exact full URI and the terminal's complete SourceDefinitionReference, not just these suffixes/hashes.
Resolve dependency/bootstrap terminals and all products with the existing source-entry terminal checks.
The parent is this CPU capture's original monolith composition (8,872B stored/40,161B decoded),
not the unrelated 858 partition chain. Preserve both original readonly archives, all 9 groups/271 calls,
6 candidates, and each original root/provider/graph namespace.

Existing blockers are precise: `source_program_publication.py:119,313` require a partitioned parent
and a unique project fi/bi/DefinitionInventory; `program_composition.py:704` permits only continuation
attachments on partitioned parents; `source_invocations.py:555` forces every verified attachment's
body to None, while `:859` decodes body regions as ElementReference. No fi/bi exists for this entry.

## Smallest production slice (five files; no CLI, lowerer or IR graph change)

| File | Proposed public change; old entry points/defaults remain strict |
|---|---|
| `source_program_publication.py` | `publish_source_entries(base_composition, catalog, source_programs, out_dir, *, max_programs=1, max_operations_per_body=4000, max_record_bytes=64000000, progress=None)` and `read_source_entry_publication(path, *, expected_sha256, catalog, ...)`. Each input is an exact `(entry_key, original artifact receipt)`; rederive entry from catalog, never trust terminal success as admission. |
| `program_composition.py` | Define a qualified body reference beside existing ElementReference: original SourceDefinitionReference, original SP5 graph locator/namespace, actual RegionID, CP2 admission locator. Add `CompositionIndex.from_source_entry_publication(path, *, expected_sha256, archives, ...)`, `body_reference(definition_ref)` and `typed_qualified_body(body_ref)`. The factory opens exact original parent plus direct-admissions inputs via existing `SourceAttachments.from_admissions`; no fake continuation or mutation of parent document/files. |
| `function_interfaces.py` | Add `extract_entry_signature(context, definition_reference)`: exact original AST/source atom/slot membership, then the same signature algorithm as `extract_signature`. No fabricated DefinitionInventory, project index or function/module object. |
| `call_demand.py` | Add `derive_entry_source_admission(origin, code_source_link, *, catalog, entry, body)`. Require the real catalog-owned resolved entry, owner.resolve_definition, exact descriptor/link/snapshot/source and checked BodyInventory; return existing CallSourceAdmission. Do not relax existing indexed-definition derivation. |
| `source_invocations.py` | Extend the ordinary same_capture path to the checked publication overlay. Use exact current descriptor/group/anchor verification, then qualified definition→admission→body lookup. Explicit report/bindings version4 for qualified external bodies; prior v1–3 behavior unchanged. Activation construction takes the checked actual RegionID/namespace, not a fabricated ElementReference. |

The publication manifest is a bounded navigation/CAS overlay, e.g. `scar.source-entry-publication/1`:
exact parent composition+inventory+layers receipts, original admission/capture scope and both archive
receipts, producer receipts, complete catalog denominator/digest, selected definition refs, original
SP5 refs and CP2 refs. ADD requires no existing body for that full qualified definition; a conflict
rejects. CP2 retains fixed `#/graph`, `#/metadata`, `#/interface`, `#/structured`, `#/language`
locators into the original SP5, SOURCE_PROGRAM5_ADMISSION origin and UNKNOWN construction cost.
No graph payload is copied and this manifest is not a partitioned inventory or a new ProgramSnapshot.
`source_inputs()` includes the new overlay receipt as well as parent/admissions; a parent hash alone
does not bind the added body. Readers verify all locators and reject a changed URI, namespace or CAS.

Publication independently runs ordinary `SourceProgram.read_structure(document, max_operations=4000,
source_texts={reference.snapshot.path: readonly_store.text(reference.snapshot)})`, original semantic/
semantics/control digest and definition/source membership checks, exact AST signature/interface,
`SourceCodeEvidence.from_entry(catalog, entry)` and `require_valid_structured_body` with that evidence.
Use catalog.prepare only for archived text/AST/context, never seal/lower/prepare_source. The consumer
uses the same ordinary structure/source readers; it cannot recover the expired lower owner or its cost.

## One root-owned CPU gate after review

1. Metadata preflight pins the immutable terminals, exact parent/admission/archive roots and saved SP5
   receipt. Keep full 9/271 rows and six candidates; select successful artifacts mechanically. Preserve
   old CLI/standalone results. Fresh outputs and failed/started journals; no resume of live ownership.
2. Publish the one original SP5 independently; reopen the publication through the public composition
   factory. Query its qualified definition→body and typed original graph. This query must return the
   same SP5 URI/hash/namespace/root; original project queries still refer to the original parent.
3. Obtain genuine coordinates using the existing native-batch acquisition idiom
   (`native_capture_batch.py:1166–1236`), not a JSON owner loader and not the full native batch function:
   check pinned G1 capture-model/retained-coordinate/archive declarations and member accounting, then
   `bind_capture_coordinates(root, max_bytes=verified_raw, profile_uri=output_coordinate_path)`.
   Require Run, full payload and verified byte count equal the original retained coordinates, as that
   code does. This revalidates retained member/OS evidence; it does not import/rebuild native/OS graphs.
4. Call existing `bind_source_invocations(composition, coordinates, capture/"trace", fresh_out,
   call_budget=..., witness_mode="same_capture")`. Its ordinary scan reproduces all raw files,
   metadata, complete CodeDescriptors, nine groups, entry/exit anchors and 271 invocations; attachment
   `verify_capture` is reused. No invocation filtering or old invocation JSONL substitution.
5. Query the unified composition and resulting binding rows by qualified refs. Only exact checked
   associations may have BODY_LINKED status. The selected group has original weight260, so 260 is
   an acceptance criterion, not a measured result or a field to prefill. Every remaining group retains
   its own source/body frontier; counts, completion and process/point availability come from the scan.

Gate ceilings: one artifact/file, 4000 read operations, selected source/provider decode128MB,
record64MB, output128MB post-stage, metadata2MB, external180s. Existing catalog/archive limits remain
9/271-capable (16 groups/16 candidates, 6 admitted files, 8 roots, 2 archives/21 keys/32MB payload).
Suggested CallEdgeBudget: raw2MB, lines2048, line1MB, processes4, codes16, events1024; the three original
call files declare 536,684B total/585 lines. Genuine coordinate binding uses declared complete
verified_raw with an outer64MB ceiling and the native-batch stored/decoded precharge/reconciliation
method; no claim that per-API limits are a measured cumulative-I/O hard cap. Stage actual counts/bytes
and any unmetered cumulative I/O remain explicit. No import_capture, native producer, lower, compile,
target or admission rerun. Production/source/input SHA checks surround the one real gate.

BODY_LINKED here means current complete code descriptor→original qualified source definition→original
typed body, and where available a frame EvidencePoint/RegionActivation. It does not prove function
object identity, globals/builtins/defaults/closures, actual-formal or return routing, environment/state,
effects/readiness or legal replay. Keep those separate OPEN fields/frontiers even if 260 associations
are established; missing environment evidence must not erase a valid code/body association. The new
v4 report is intentionally not yet accepted as a completed SBA/dispatch proof: their v2/v3-only guards
stay closed until a separately reviewed consumer increment. The global LeWM source858/runtime843
and 6699 are unchanged; this is the independent CPU capture's body association, phase1 still OPEN.

Read-only design evidence: current source API inspection; immutable CLI terminal17,280B,
bootstrap terminal60,127B, retained coordinate metadata198,782B, seed metadata3,450B stored/18,313B
decoded, and worker manifest1,223B. No old858 chain, SP5/source-context graph, raw or DB was opened.
