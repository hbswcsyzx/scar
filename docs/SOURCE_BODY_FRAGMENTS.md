# Shared source contexts and independent SP5 bodies

`scar.store.source_fragments` splits existing `SourceProgram/5` archives without changing their core graph, IDs, source links, interface or SP5 wire. It is opt-in storage/reading; existing publishers, catalogs and full `SourceProgram.read_structure` keep their current path. It does not build a new graph, execution snapshot, live capture owner, or backend.

Each `scar.source-context/1` record holds the original `semantic`, `semantics`, and `control` tables. Its identity includes the existing `SourceSnapshot` and `SourceContextDigest`: exact namespace root and three canonical hashes. Each `scar.source-body-fragment/1` holds all other original SP5 fields, the typed context reference, the exact original `SourceArtifactLocator`, and the original canonical-tree hash. The context payload and body use ordinary `SourceArtifactLocator` stored/decoded receipts. Original decoded-byte identity is checked with the two supported public JSON forms, canonical UTF8 or those same bytes plus one LF; other forms are explicitly unsupported. Original URIs/namespaces are retained; equal bytes do not merge different source namespaces.

```python
from scar.store.source_fragments import SourceContextSession, SourceFragmentWriter

writer = SourceFragmentWriter(new_archive_directory)
body_locator = writer.write(original_sp5_locator)  # namespace from the same checked SP5 read
writer.finish()

with SourceContextSession(source_texts={original_source_path: retained_text}) as session:
    fragment = session.read(body_locator, namespace_root=original_namespace)
    body = fragment.body  # existing LoweredSourceBody
    graph, metadata = body.graph, body.metadata
```

The writer accepts an optional explicit `namespace_root`; it must match exactly. Omitting it recovers the original `language.namespace_root` from the same already-read document, avoiding a second discovery pass.

The public storage command consumes the existing source-publication selection; it does not import the target or rebuild bodies:

```bash
python -m scar.cli store-source-fragments \
  --selection PATH/selection.json --sha256 EXPECTED_SELECTION_SHA256 \
  --out fresh-store --limit 2
```

Omit `--limit` to process all selected requests within the explicit I/O/context budgets. Each manifest body locator can be passed to `query-source-region --source ... --sha256 ...` for a core-only local view. This path reads neither the old full SP5 nor the shared context; it does not claim source admission. A normal `SourceContextSession.read` remains available when context/source validation is required.

The main-tree command packed two original OmegaConf bodies into one context plus two fragments: 5,153,469 → 2,736,372 stored bytes. The first body query read 172,894 stored / 1,930,477 decoded bytes and returned the identical original Region view. The existing source entry publisher still uses the old format; this is an implemented storage/query path, not a completed migration of all catalogs. Actual command terminals are in `artifacts/experiments/source_fragments_cli_20261026/`.

A body is independently readable from its locator and referenced context; no project-wide manifest/index or old full-SP5 payload scan is needed. Independent workers use independent sessions and atomically publish immutable context/body files; no shared mutable IR or central writable index is required. A session is for serial owned construction/reads, not a concurrent mutable cache.

`SourceProgram.read_structure_fragment(body_document, *, context_session, context, max_operations=10000)` is the explicit body-only entry. The session ordinarily decodes and checks source/semantics/CFG once per exact context. It privately holds the typed tables, and checks their canonical hashes and exact snapshot/namespace before and after each body validation. Only a real live session can use the private reuse path; there is no serialized accepted token or `verified=True`. Changing input receipts/namespaces selects another context; modified private IR is rejected; provided source texts are copied immutable strings, and close clears context ownership and rejects further reads. Public results expose existing immutable body/core records and context receipts, never shared mutable context tables or a full SourceProgram retaining them.

Every body still passes the ordinary graph codec, closed SP5 profile, structured/language, source-correspondence and formal/interface checks. This is STRUCTURE transport plus the existing context source/AST/CFG checks, not full body re-lowering, a new CodeWitness, runtime dispatch, effects, contents, ready or optimization proof. Existing `ProgramSnapshot` input is the unchanged original `ProgramGraph`; the store does not mint a replacement snapshot or unify bodies into an empty graph. Full SourceProgram reads remain the existing API and intentionally perform their ordinary full checks.

`SourceFragmentBudget` bounds stored/decoded input, per-record size, stored output, context count, operations and wall time. Context and body JSON are strict/canonical with explicit schema versions; gzip is bounded before decoded allocation. EOF/SHA and input stat guards apply. Publishing is atomic and refuses conflicting existing bytes. Repeated existing-output verification is charged. New fragment storage currently supports SP5 only; SP1–4 and SP6–8 require separate deliberate adapters and are rejected here. Old readers/writers are unchanged.

Actual two-body closure, original failure records, source SHA receipts, bytes/RAM/time and the independent origin-receipt check are in [the experiment report](../artifacts/experiments/source_body_fragments_main_20261026/REPORT.md). The real 239-op newer-capability sample motivated this work but was not revalidated here; the checked bodies are the retained real 85/217-op pair sharing `world.py` context. No 161-body recheck or LeWM run occurred.
