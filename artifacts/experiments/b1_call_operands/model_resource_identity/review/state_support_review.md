# Follow-up: stale state support with an unobserved current formal

Status: **FINDING F5**, original four-issue report and initial observations are preserved.

Root's changes for F1/F2/F3/F4 were read: segment evidence compares owning process/run; flow retains expected defining visit across a missing producer; multiple disconnected entry roots emit `initial_entry_ambiguous`; public point/catalog wrong types are rejected explicitly. These are appropriate corrections by static review. This agent did not rerun the original probe or root regressions, so those four are not claimed runtime reverified here.

## New concrete F5

The same missing-observation downgrade remains in `validation._Context.check_support`: current state None becomes only a gap even when the canonical current formal and its new defining visit are known. The flow's new expected-definition information is used by operands but not this resource-support path.

A small manual loop IR is extended with a generic region-owned implicit CPU/executor resource. Counter state is its declared resource location. This is an interface stress case, not a business rule or a claimed collected CPU trace.

Actual observations from `state_support_probe.py` (Python3.14.7, torch not imported):

1. At header visit 5, support `5.header.state`: structurally valid.
2. Same point, support `3.header.state`, with current formal recorded: rejected with `stale_state` / `resource_current_state_support`.
3. Remove only the ValueOccurrence for `5.header.state` and replace the corresponding ordinary operands with explicit Unresolved. Keep ResourceAccessBinding/ImplicitBinding support explicitly bound to `3.header.state`: validation becomes true with `formal_unobserved`, `state_support_unresolved`, `resource_current_state_unknown` gaps.

The missing row does not make an already-known older formal incarnation the current state. Preserve/derive the canonical current-state source and expected defining traversal even when its occurrence row is missing; reject support whose known origin is incompatible. Do not mint a replacement state or producer.

Limit this to points with a known canonical current-state origin. INVOKE/BODY_DRIVE common AFTER intentionally lacks a unique post-state and must not borrow a before-state/old visit as its expected post. EvidencePoint unknown state remains a gap.

The baseline and known-stale comparison isolate the risk; all three source hashes were unchanged during the probe. Script, exact command, JSON/stdout and hashes are retained alongside this report. No product/test edits, pytest/full suite or workload execution occurred.
