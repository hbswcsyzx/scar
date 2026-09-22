# G3 independent criteria report

Status: **PASS**

Revision: `1af7d14f69f15c6b71acf6938b3e642c414a5e65`

Source digest: `e6d6515ea9d3fe074f1694c319780987ed75adf081f01096ef0c7c0a8305a9e4`

| Criterion | Status |
| --- | --- |
| raw_record_conservation | PASS |
| invocations_and_incomplete_pairing | PASS |
| typed_control_and_runtime_resources | PASS |
| clock_domains_and_stream_order | PASS |
| physical_evidence_is_not_a_source_call | PASS |
| deterministic_roundtrip_and_cli | PASS |

Scope: Offline raw-record normalization to v2: conservation, observations, clock separation and runtime resource evidence. Actual archived trace results are recorded separately in g3-runtime-pressure.json.

- Value IDs are provisional snapshot identities; semantic provenance is G4.
- Unobserved return/state/alias evidence remains incomplete.
- This measures conversion cost, not LeWM performance.
