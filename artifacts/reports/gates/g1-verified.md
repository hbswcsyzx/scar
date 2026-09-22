# G1 independent criteria report

Status: **PASS**

Revision: `aff0c20f15a9c6e5e160a7043de05d448e3546cb`

Source digest: `da647ebaa0d2b55a691913f0bf2f1c018e17b0e7a6487ec0a04ad036bc25c75e`

| Criterion | Status |
| --- | --- |
| identity_and_cross_graph_integrity | PASS |
| cycles_relations_and_mutable_records | PASS |
| replacement_boundaries_and_noop | PASS |
| four_report_only_plan_forms | PASS |
| strict_deterministic_codec | PASS |
| v1_trace_analyze_compatibility | PASS |

Scope: Typed IR structure, boundary integrity and exact JSON round-trip; all plans are fixtures, no automatic simplification is claimed.

- Semantic proof construction and region inference are later gates; PROVEN records are supplied declarations in these fixtures.
- Literal substitutions currently accept finite JSON literals only; tuple, bytes and non-string-key mappings are rejected to prevent type loss.
- INSTANCE_OF is represented by OperationInstance.definition and correspondence records.
- No new backend, transformation or LeWM speedup is tested by this gate.
