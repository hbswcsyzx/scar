# R0 root decisions and bounded acceptance

Final contract SHA256:
`74a606fca89ecb94ad9a04f77d8ad41706bcdacb10210352ccad185272993729`.
This is a relation contract, not an implemented schema/validator or runtime proof.

| Issue from review | Decision |
| --- | --- |
| Reuse old EEG instance ID as a core occurrence | Reject. Different definition spaces and granularity require new core occurrence identities plus explicit scoped many-to-many links. |
| Raw pid/tid/window or address as identity | Reject. Run/process/thread incarnations and typed realm; window/clock remain evidence coordinates. Segment can keep UnresolvedHostThread. |
| One resource generation counter for all identities | Reject. Resource lifetime ID, handle slot lifetime, event record and ticket are different. No redundant counter for the same lifetime. |
| Allocation/process/thread parallel resource identity | Reuse the existing identity through ResourceTarget; placement is not same-identity. |
| Whole activation satisfies every constraint after entry binding | Reject. Identity binds once; current rights/capacity/closed-state are checked per access against canonical support. |
| INVOKE needs ordinary StateAccess to describe effects | Reject. Use exact owned state Use plus actual completion/result→formal or UnresolvedPost; no fake producer/normal branch. |
| Submission must be BEFORE/AFTER host call | Reject. WithinOperation with physical fact, or external scoped source; actual call can submit before raising. |
| Completion required before any safe device consumer | Reject. CompletedVisibility and precise OrderedVisibility are alternatives per contribution; all required contributions AND. Failure cannot be repaired by order alone. |
| Ready means free/quiescent/no borrows | Reject. Pending work retains original targets until explicit release/quiescence support or unknown end. |
| All consumers are code Uses, all materializations have allocations | Reject. Explicit external observation root, EndpointPlacement and Unresolved branches; no fake code consumer or allocation. |
| region=None means a file | Reject. Placement requires explicit association. Different backing does not prove disjointness. |
| ResourceUse.handle=None means UnknownHandle with a made-up value | Reject. Explicit, ImplicitBinding and UnresolvedHandleAssociation are different; implicit selection does not bypass a declared static handle. |
| Rights/ownership/visibility as free strings | Reject. Typed protocol members, holder/current-state support, distinct domain variants and explicit unresolved branches. |
| New static WorkSite/ReadyUse required now | Not required for this execution interface. Exact original op/use/access/completion links suffice. Genuine future static signature/constraint extensions must version explicitly. |
| Re-run full repository after docs/isolated design witnesses | Not required: registered source/test/gate fingerprint remains identical to accepted D2.4. Existing 4,050-case run is referenced as prior evidence, never claimed as a new R0 run. |

## Observed versus proposed

Six stdlib CPU/OS cases executed once, all asserted PASS. The worker-failure case
observes `submit` returning normally followed by worker failure and a host
`Future.result()` exception. It does not observe a submit/enqueue API itself
raising after partial submissions. No CUDA/event generation or power-failure
experiment was performed. Resource/ready records remain proposed for R1/R2.

Review drafts are retained as reports with their original candidate hashes;
the final contract/plan byte snapshots are archived separately. A root patch
attempt failed its expected-context check before writing; it was corrected with
the actual current context, without changing product code or experimental data.
