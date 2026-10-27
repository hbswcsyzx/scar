# Callee-entry snapshots can close a local formal-port relation

Read-only design,2026-10-25. The public read_call_operands performed exactly one
complete frame strict scan:536,684 decoded bytes/585lines. Operand sidecars added
13,285B:combined549,969B within2,000,000B. Both protocols reported no issues.
No Tensor materialization,Torch import,target,lowering,native graph/DB read or
production/Git change occurred. observations.json preserves exact receipts,
typed samples and current source hashes; those hashes are not historical code
execution witnesses. A5,191B CP2 header was checked separately; SP5 stayed unread.

Observed facts:

| Domain | Actual retained observations |
| --- | --- |
| Frame trace |9codes,271entries/271exits; all parameters_complete=True |
| Existing28op qualified body |260entries, each [op,torch_dispatch_class],520weak parameter refs |
| Operand CPYTHON_CALL_WINDOWS_V1 |21 INSTRUCTION,11 CALL_ATTEMPT,0 ENTRY_HANDSHAKE,0loads; no reported gaps/drops/errors |
| Return profile |270NORMAL at RETURN_VALUE;1UNKNOWN at CALL_FUNCTION_EX |

These names identify the sample only. Product matching must use the verified
code/source/interface, never business names. Other11calls retain their existing
source/body frontiers; this audit grants no new routing qualification.

The v1 collector's call callback reads callee frame.f_locals with the actual
CodeDescriptor parameter names, after Python argument binding. It writes named
reference tokens, completeness/suspended flags, InvocationKey, code key and
original row coordinate. The strict reader checks complete names against the
code descriptor and validates full files/metadata/counts/reference domains.
source_invocations._Sink currently reduces the vector to counts, then emits
ACTUAL_FORMAL_ROUTING_UNVERIFIED for all271invocations.

This supports **callee-entry binding snapshot→formal port**, separately from
**caller actual-expression→callee formal**. The latter is unproved here: the
operand data has no entry handshakes/load values, and caller_locals is not the
caller evaluation stack. Parent intervals/callable+arg0 cannot fill that gap.
Missing FunctionObject/environment/content does not erase the local snapshot.

References remain scoped: the recorder's weakref map tests the actual referent,
uses monotonic epochs and removes dead entries; nonweak snapshots last only for
that event. Operand weak refs delegate to the same recorder and snapshots are
re-scoped. Exact base_manifest binds its frame files, but this capture has no
collector-witness UUID/generation sidecar. Historical same-live-issuer/executed
collector-source assumptions remain. Never join bare strings across captures.
A local single-entry binding requires no cross-provider object identity/content.

Implement opt-in CALLEE_ENTRY_PARAMETER_ROUTING_V1 with an explicit new source
invocation output profile/version; preserve v1–v4 defaults. Keep legacy
actual_formal_routing_established=False, expose per-port
CALLEE_ENTRY_REFERENCE_SNAPSHOT, and leave caller-actual routing UNKNOWN. Preserve
all271calls and previous body/source evidence; a refined label must not claim
complete calls,returns,environment,state or readiness.

Reuse normal qualified-body/CodeWitness readers and original CP2→SP5 locators.
For each fresh complete entry, validate its complete code/source match, then map
captured parameter NAME→FunctionSignature parameter slot→BodyEntryInterface
FormalPort(slot,value), with exact owner/namespace,coverage,kind/layout and entry
BlockArgument/ReferenceValue. Code layout is positional,keyword-only,*args,**kwargs;
FunctionSignature ordering differs, so a global positional zip is wrong. The
sample's two ordinary positional parameters naturally select two original entry
formal values. world is a separate StateVersionValue, not a Python argument.

Retain typed FrameEntry/NamedReference/CallRecordAnchor until complete EOF,
metadata,coordinate and source checks pass. Reuse
ReferenceOccurrence(role=PARAMETER,core_value=...), original SourceReference,
qualified body namespace and coordinate-bound ProviderFactReference/EvidencePoint;
keep original parameter ordinal/name and row SHA. This is one observed endpoint
mapped to a static port: do not invent a second occurrence/identity route,
ObjectID or LogicalVersion. An independent checker rejects changed original row,
invocation,name,port/order,namespace or incomplete inventory. Missing body/source,
incomplete vectors and suspended frames keep concrete local frontiers.

No CallActivation follows from a parent interval. Full dynamic canonical
execution would need its own initial-visit contract; current DenotationBasis
has no qualified Python-formal-entry variant. This increment is a checked
projection onto existing static formal ports, not an Unresolved-based shortcut
to ExecutionModel qualification or another graph authority.

Minimal3sources: analysis/source_invocations.py retains vectors and owns the
opt-in phase; new analysis/source_entry_routing.py projects existing typed
endpoints; new analysis/source_entry_routing_validation.py independently checks
original/source/port inventory. No collector,IR schema,publication,CLI,module or
native change. Existing normal qualified-body lookup supplies the interface;
report an actual missing API before expanding scope.

One later root-run CPU/offline gate reuses this capture/publication and the
ordinary fresh binder in one process: no relower,publish,target or restored JSON
owner. Scan frames once,query the body once,build/check every available mapping.
260×2is the measured candidate, not a prequalified expected result. Keep2MB for
call+operand raw and existing separate source/provider/coordinate budgets; the
latter include normal SP5/archive reads, so2MB is not a whole-gate I/O promise.
Report cumulative actual reads. One genuine same-entry port/source swap must
fail independently; no test matrix. Later caller-actual work should first reuse
existing bounded operand-window/load/ENTRY_HANDSHAKE tools for exact ordered
actual Uses/keywords/expansions and their entry; no equal-ref/content guessing.

NORMAL is the actual v1 return-opcode observation, not an identified canonical
Return/payload route. UNKNOWN is not proved unwind/RAISE or a known exception.
return_ref is an opaque reference, not None content; missing logs never supply
None. Stronger completion/value claims need explicit supported evidence, and
all full execution,content,state/effect/lifetime/ready obligations remain OPEN.

Implementation location: frame-entry-routing at Root baseline bc139e19. Explicit opt-in source-invocations v5; v4 defaults stay unchanged.
