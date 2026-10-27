# R1 root execution modules — limited static closure

Conclusion: **PASS_WITH_SCOPE — static closure of F1–F6 in the five reviewed root modules**. No new probe or pytest was run for this closure; the initial reproductions and reports remain untouched.

## Corrections checked

- **F1:** segment ingress and unresolved-thread evidence compare run/process with the owning activation, in addition to internal EvidencePoint foreign-key validation. A process omitted in evidence is not fabricated.
- **F2:** flow carries canonical expected defining traversal independently of a captured ValueOccurrence. An operand with a known older origin is rejected even when the newer producer row is absent. This is transient information derived from the existing canonical CFG/records; it creates no replacement state/producer.
- **F3:** multiple disconnected roots named region entry emit `initial_entry_ambiguous`. This deliberately represents unresolved ingress correspondence, not two proved initial executions or a total trace.
- **F4:** invalid point variants become a point-type error, and malformed supplied catalog shapes become `catalog_type`; ordinary foreign-key errors remain separate.
- **F5:** flow derives current state source per Location as `(canonical StateValueID, defining visit)`, records it at before/after/taken-edge points, and check_support compares the known support's static identity/traversal when the current row is missing. Missing data no longer makes an older known formal compatible. INVOKE/BODY_DRIVE common AFTER explicitly clears both state and expected-state definitions; EvidencePoint derives neither. These preserve the intended unknown cases rather than borrowing a before-state.
- **F6:** same-family external graph validation/canonicalization's expected record/shape failures become `external_graph_invalid` issues. Wrong family, unavailable catalog and digest/schema/size mismatch remain distinct. Failed graphs are not cached as successful matches. snapshot.external_artifact also limits accepted graph families and normalizes expected malformed-shape failures.

## Other reviewed boundaries retained

ExecutionModel's canonical IDs remain exact with nested string rechecks, and legacy EEG instance identity is not rebranded as a core occurrence. Snapshot comparison uses canonical bytes/schema/version/size/digest without opening URIs. Query coordinate views are now strongly typed; they return detached associations to canonical Uses/definitions/producer origins and the original canonical operation contents, with no source/runtime or transform authority. The earlier wording observation about “Original Use” is not a blocking connection error and does not require object aliasing.

No additional concrete blocker was found in this bounded follow-up. This conclusion concerns these corrections and the reviewed connection logic only, not all malformed inputs or all execution/resource combinations.

## Verification boundary

Root's `flow/attempt003` was nonpassing (33 passed, 4 failed as reported); this closure does not relabel that run as a passed component. Root reports the two F5 regressions passed there, while F6 was corrected subsequently and its regression is to be exercised by the final component gate. No post-fix execution evidence is claimed by this reviewing agent. Other-agent resource-validation corrections, the component gate and full regression remain root-owned.

This is not completion of the whole program model, runtime adapters, actual identity/permission/liveness, GPU ordering/readiness, optimization legality or speedup. All original evidence/logs remain independently inspectable.

## Reviewed source SHA256

- `scar/ir/execution/model.py`: `f1b9941741f48bcfafc224e50722422450e6a07ef7c606c2422395d2de274411`
- `scar/ir/execution/snapshot.py`: `03e14e4f14ad50efbc9d0c450e55964440201cc73e6e1fe256660f78063f127b`
- `scar/ir/execution/validation.py`: `2c60deee43107fe0310140fcd9e73a55288a45b7ebebda22b699d238e695cdfa`
- `scar/ir/execution/flow.py`: `2b6189a1ad658072176a00bc4c72a4c5af4c66e96edc844bad904471c8eb0501`
- `scar/ir/execution/query.py`: `3fc8137359765f878f2b82476893cc6562da90f4a710144ed764280b4f027c3e`
