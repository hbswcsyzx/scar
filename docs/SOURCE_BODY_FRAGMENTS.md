# Shared source contexts and independent SP5 bodies

`scar.store.source_fragments` splits existing `SourceProgram/5` archives without changing their core graph, IDs, source links, interface or SP5 wire. It is opt-in storage/reading; the source-entry worker/stage can select `shared_context=True`, while old publishers, catalogs and full `SourceProgram.read_structure` keep their default path. It does not build a new graph, execution snapshot, live capture owner, or backend.

Each `scar.source-context/1` record holds the original `semantic`, `semantics`, and `control` tables. Its identity includes the existing `SourceSnapshot` and `SourceContextDigest`: exact namespace root and three canonical hashes. Each `scar.source-body-fragment/1` holds all other original SP5 fields, the typed context reference, the exact original `SourceArtifactLocator`, and the original canonical-tree hash. The context payload and body use ordinary `SourceArtifactLocator` stored/decoded receipts. Original decoded-byte identity is checked with the two supported public JSON forms, canonical UTF8 or those same bytes plus one LF; other forms are explicitly unsupported. Original URIs/namespaces are retained; equal bytes do not merge different source namespaces.

```python
from scar.store.source_fragments import SourceContextSession, SourceFragmentWriter

writer = SourceFragmentWriter(new_archive_directory)
body_locator = writer.write(original_sp5_locator, namespace_root=original_namespace)
writer.finish()

with SourceContextSession(source_texts={original_source_path: retained_text}) as session:
    fragment = session.read(body_locator, namespace_root=original_namespace)
    body = fragment.body  # existing LoweredSourceBody
    graph, metadata = body.graph, body.metadata
```

A body is independently readable from its locator and referenced context; no project-wide manifest/index or old full-SP5 payload scan is needed. Independent workers use independent sessions and atomically publish immutable context/body files; no shared mutable IR or central writable index is required. A session is for serial owned construction/reads, not a concurrent mutable cache.

`SourceProgram.read_structure_fragment(body_document, *, context_session, context, max_operations=10000)` is the explicit body-only entry. The session ordinarily decodes and checks source/semantics/CFG once per exact context. It privately holds the typed tables, and checks their canonical hashes and exact snapshot/namespace before and after each body validation. Only a real live session can use the private reuse path; there is no serialized accepted token or `verified=True`. Changing input receipts/namespaces selects another context; modified private IR is rejected; provided source texts are copied immutable strings, and close clears context ownership and rejects further reads. Public results expose existing immutable body/core records and context receipts, never shared mutable context tables or a full SourceProgram retaining them.

Every body still passes the ordinary graph codec, closed SP5 profile, structured/language, source-correspondence and formal/interface checks. This is STRUCTURE transport plus the existing context source/AST/CFG checks, not full body re-lowering, a new CodeWitness, runtime dispatch, effects, contents, ready or optimization proof. Existing `ProgramSnapshot` input is the unchanged original `ProgramGraph`; the store does not mint a replacement snapshot or unify bodies into an empty graph. Full SourceProgram reads remain the existing API and intentionally perform their ordinary full checks.

`SourceFragmentBudget` bounds stored/decoded input, per-record size, stored output, context count, operations and wall time. Context and body JSON are strict/canonical with explicit schema versions; gzip is bounded before decoded allocation. EOF/SHA and input stat guards apply. Publishing is atomic and refuses conflicting existing bytes. Repeated existing-output verification is charged. New fragment storage currently supports SP5 only; SP1–4 and SP6–8 require separate deliberate adapters and are rejected here. Old readers/writers are unchanged.

Actual two-body closure, original failure records, source SHA receipts, bytes/RAM/time and the independent origin-receipt check are in [the experiment report](../artifacts/experiments/source_body_fragments_20261026/REPORT.md). The real 239-op newer-capability sample motivated this work but was not revalidated here; the checked bodies are the retained real 85/217-op pair sharing `world.py` context. No 161-body recheck or LeWM run occurred.

The source-entry stage now has an optional `shared_context=True` output. It performs the existing SP5/code checks before archive splitting, shares one context writer across its window, and returns exact fragment receipts with `#/program/graph`. After writer finish guards pass it retires only full SP5 copies newly created inside that worker; old inputs/receipts remain unchanged, and fragments retain the actual original decoded identity. This saves final archive space, while full-SP5 generation and validation I/O still occurs. Default output remains SP5; the existing strict CP2 publication/binding reader does not accept fragments. The real two-body storage/normal-read closure and explicit limits are recorded in [the production adapter report](../artifacts/experiments/source_entry_shared_context_20261026/REPORT.md).
