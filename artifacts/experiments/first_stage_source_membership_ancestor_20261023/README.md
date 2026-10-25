# ONE fixed-source ancestor query gate

2026-10-23. **Observed / Verified limited query: actual exit0, PASS_WITH_OPEN.**
No raw trace was read, no private SameRunSourceProof factory was constructed and
no new runtime source/body binding ran. The full first-stage model remains OPEN.

The frozen public API is
`CompositionIndex.require_source_membership_ancestor(expected_composition_canonical_sha256,
expected_inventory, max_depth=16, max_total_decoded_bytes=1_000_000_000)`.
It verifies the exact original source-membership ancestor through actual parent
composition/inventory receipts. It checks stored/decoded/canonical SHA/size,
paired inventory/composition declarations, original compiler component/origin,
source_layers, full ordered151-source snapshot/context vector and project
discovery reference. Only compact metadata/receipts are retained; the query
does not construct another CompositionIndex or replay old body accounting.

The real input is the published843-body snapshot and original
`first_stage_current_source_gate_20261023/result/source/report.json`. The latter
is a navigation input here, not a manufactured dynamic proof. The actual chain
is revision comp3/publication2 →842-body comp3/publication1 →original comp2.
The exact expected source ancestor is found at depth2. The original compiler
inventory dictionary still equals the original OLD source report inventory;
the strict equality has not been relaxed or redirected to a newer842 report.

| Actual owned ancestor-reader activity | Count |
| --- | ---: |
| Parent composition indexes parsed | 2 |
| Parent inventory readers constructed | 2 |
| Cumulative decoded composition/inventory/publication bytes | 154443079 |
| Additional parent reads for identical query | 0 |
| Additional parent parses for wrong-ancestor refusal | 0 |

These counts describe this query's owned ancestor readers; ordinary current
CompositionIndex construction and existing compiler-origin metadata checks are
separate. Every parent index is parsed once and discarded after extracting small
source metadata. The declared depth16/decoded1GB bounds remain fixed. Cache hits
require the same bound current document/manifest/attachment inputs and unchanged
checked file identities, sizes and timestamps; they reuse prior cryptographic
receipt verification rather than falsely claiming a fresh full hash replay.

An identical second query returns the exact same receipt without new parent
parsing. A different, absent ancestor canonical SHA is rejected with the original
inventory unchanged; cached metadata does not grant the nonexistent ancestor.
`ancestor.json`, `same-input-cache.json` and `wrong-ancestor-rejected.json` preserve
these checks. No fake CapturedCode, old RegionActivation or dataflow producer is
created by this query.

The production change to `SameRunSourceProof.require_composition` calls this
regular ancestry query instead of requiring the immediately preceding snapshot.
It retains the original compiler-inventory, attachments, project-root, owned
current raw, producer/source/build and recorded guard checks. The receipt rule
is explicitly SAME_RUN_STATIC_SOURCE_MEMBERSHIP_ANCESTRY_V2/rule_version2 and
declares static membership only, with no old body/activation reuse. An existing
proof cannot silently switch to another current snapshot. Old pre-revision
source checkpoints cannot equal a new installed receipt or be resumed as new
snapshot output. These factory/runtime integration paths were AST/import
reviewed, **not executed by this dry query gate**; they await the coordinated
current-Run gate.

Frozen sources are in `production-source/` with exact `implementation.patch`:
program_composition SHAa0577c7762a53a1c167451bf6b4bd0bd029cd82bbd115721b36315f283dda070;
current_source_evidence SHA1886477d1845dd5ddf669aec8b2b5830c375cbb328647e345b6329615d09cdf2.
`freeze.json` is the preserved pre-execution receipt, while `summary.json` records
the actual query. Actual participating source bytes were checked unchanged;
unused candidate files were not producer guards.

Session82962, Python PID697602, confirmed exit0. `/usr/bin/time -v`: wall26.18s,
user24.36s, system1.77s, peakRSS711056KiB. Ordinary composition loading ended at
18.63s, and the actual ancestor query took4.77s; all checks ended at25.48s. These
are offline query costs, not a target benchmark. No prepare, compile, lowering,
raw read, target execution or GPU action occurred. No100k current binding was
started. Root will coordinate the single complete source/dispatch/SBA connection
after freezing all participating producers and original inputs.
