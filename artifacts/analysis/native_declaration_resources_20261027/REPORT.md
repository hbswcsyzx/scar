# Same-Run native declaration → GPU work/resource references

Implemented in the isolated tree based on `312ab664`. Main and its live native
producer were not modified. The old 24,082-work publication belongs to Run
`1ddea…`, PID 369749, ETO SHA `625558…`; it cannot be joined to Run `ca66…`,
PID 1578961, ETO SHA `119604…`. Its 12,541 enclosing-context cases remain a
separate historical scope.

The existing `acquire_native_activity_work` now accepts explicit
`NativeWorkBudget.max_os_lines` (default 2M), and an input ceiling up to 8GB
(default remains 4GB). Output 512MB, wall 600s and all original source/provider
checks remain. The final source also counts bundle chunks when the caller
supplies a manifest filename; that accounting correction and positional-field
compatibility placement were made after the successful acquisition and were
syntax checked, not re-acquired.

Actual retained evidence:

- Work attempt01: exit 1, worker 50.516s, outer 51.61s. The normal coordinate
  binder rejected the factory's fixed 2M OS-line cap; this capture has 3,075,182
  OS lines. No work was created; reported input 2,551,292,489B, output 0.
- Work attempt02: exit 0, worker 147.930s, outer 148.98s, RSS 291,324KiB.
  Limits: 8GB input, 3.2M OS lines, 512MB output I/O, 600s.
  All 461,242 EEG instances visited. 46,142 GPU candidates = 24,082 retained
  single-activity WorkTickets + 22,060 explicit frontiers. Output I/O
  312,020,275B. The original meter reports 4,196,477,450B input. Because its
  selected root was a manifest filename, it missed 76,202,388B of compressed
  bundle bytes which the ordinary partition reader nevertheless read and
  SHA-checked. The separately reconciled total is **4,272,679,838B**; the
  original receipt is unchanged. No second acquisition was used to fix metrics.
- One disposable locator index: all 1,170,339 original EEG edges visited,
  126,335 provider/resource locators, 1,324,882,124B metered stored+decoded,
  27.171s. SQLite is 94,863,360B and is excluded from Git. It stores only
  ID/relation/ordinal locators; every query rechecks original selected rows.
- Query04: actual exit 0, worker 15.408s. Normal source/core/ABI reader for the
  closed native fragment plus original work/EEG/resource readers succeeded;
  381,324,097B metered artifact stored+decoded (SQLite page I/O is not separately
  instrumented). The mechanical selector chose real `aten::copy_`, original
  ETO instance `…:eto:20819`, canonical invoke `native-declaration:147ebd…:invoke`.
  It returns **two original paths to one WorkTicket**: provider-scope → GPU
  activity `…:kineto:385137`, and provider-scope → runtime `…:kineto:385139` →
  submits-work → the same activity. Both locate original GPU device 0 and stream
  `(context=1, stream=7)` ResourceRequirement IDs/records. They are not two work
  items, direct calls, Tensor ports, normal completion or ready evidence.

The original native source shard 0 had no such GPU-work path; that bounded
selection refusal is retained. Query02 combined discovery with the normal query
and exceeded its 512MB artifact budget. Query03's unqualified first-scope hint
selected a host without qualifying work and returned no connections; its
assertion failure is retained. Query04 uses a bounded separate selector hint,
then the normal session's exact-work candidate check on the closed source shard.
No work/edge import was repeated for these queries.

API in `scar.analysis.native_declaration_resources`:

```python
index = build_native_resource_index(bundle: ProviderArtifact, out, budget=...)
with NativeDeclarationResourceSession(index, work_manifest, coordinates,
                                     budget=...) as session:
    hint = session.candidate(closed_native_shard_manifest)  # locator hint only
    view = session.query(fragment, source_instances=None) # default: every native row
```

`query` keeps `NativeDeclarationOccurrence`, `WorkActivityProjectionLink`,
`WorkHostRelation` with its existing `native=None`, ordered original
`EvidenceEdgeRef`s, original WorkSubmission/Binding/Quiescence, and original
ResourceRequirement IDs/locators. The new canonical occurrence stays in its own
field; no fake legacy binding or full snapshot is created. Source instances may
be selected only within the supplied qualified fragment. One verified byte
chunk per table is privately reused; public graph checks are unchanged. Bounds
stop a query rather than silently truncate connections.

`CONNECTIONS04.json` is the 88,495B real view, SHA
`bd40c20bfb948deb638239a8577eb20a7c9f142670449835c30fe09569996ebe`.
`CONNECTION_RESULT04.json` lists all exact input URIs/SHA/bytes. This is a
batch-capable consumer, **not a completed all-native resource publication**.
The 24,082 denominator is the complete work producer denominator, not a claim
that all native declarations have been queried. Provider association claims
remain inferred under their recorded fixed-provider assumptions. Completion,
state/content, materialization, lifetime and readiness remain OPEN.
