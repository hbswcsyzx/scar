# Invocation slot bindings v2

The scar.ir.invocation_bindings_v2 module adds an independent typed overlay
between operation instances, semantic slots, provenance handles, and registry
events. It supplies connection evidence for later analyses. A valid overlay
does not prove reuse, motion, value equality, hidden-state completeness, or
effect equivalence.

## Records

- InvocationClock fixes one registry scope and the typed
  REGISTRY_EVENT_ORDINAL clock domain for all records in a document.
- InvocationCall binds an OperationInstanceID to its exact
  OperationDefinitionID, process/thread IDs, typed entry/exit EventPoints,
  and a scoped evidence claim.
- InvocationSlotBinding binds one (instance, role, ValueSlotID) to a
  ValueHandle at an event. Roles are INPUT, STATE, OUTPUT, and READ.
- InvocationBindingsV2 contains only those records. It does not serialize a
  validation status or guard result.

INPUT, STATE, and OUTPUT refer only to the formal slots explicitly listed on
the operation definition. Each such slot must be owned by that definition.
READ refers to an actual source slot reached by a
READS_SLOT(operation, slot) semantic edge. The actual source slot can belong
to another definition; it is not reclassified as a formal port. Every
distinct READS_SLOT target is included in per-invocation slot coverage. A READ
binding records one sample for that slot; it does not close every repeated
read event, identify operand order, or prove hidden-read completeness. An
input list being empty does not erase known actual reads.

Input bindings are sampled at call entry, output bindings at call exit, and
state/read bindings inside the call interval. All event points must use the
overlay scope and registry ordinal clock.

## Validation

Call overlay.validate(bundle, registry) each time current validity is needed.
It builds fresh local indexes for reads, intervals, and object bindings, then
checks:

- bundle and registry integrity, instance/definition/process/thread identity,
  scope/clock, and ordered call bounds;
- declared formal slots, actual READS_SLOT targets, role/owner agreement,
  missing/duplicate slots, and per-slot evidence;
- a unique live registry binding interval for the same instance-scoped slot,
  event, handle, and evidence claim;
- version, object, materialization, region, and allocation references in both
  the registry graph and IRBundle.values;
- materialization and allocation lifetimes at the recorded event; and
- a newly computed registry guard for each supplied handle at
  registry.current_event.

The report separates three results:

- structure: whether cross-references and typed records are valid;
- slot_coverage: whether every declared formal slot and known READS_SLOT
  target has an overlay record; and
- each BindingGuard.state: the registry's current VALID,
  NEEDS_VERIFICATION, or INVALID result.

`slot_coverage` applies only to the calls listed in this overlay and the
formal slots and known `READS_SLOT` targets derived for those calls. It does
not close omitted call instances, hidden reads, or unmodeled state. Diagnostic
`as_dict()` repeats this scope explicitly. The `bindings_currently_guarded`
boolean means only that the listed bindings have complete listed-slot coverage
and VALID current registry guards; it does not upgrade DECLARED evidence to
OBSERVED or establish type compatibility, equality, reuse legality, or motion
legality.

Each returned `BindingGuard` preserves both the binding's observer evidence and
the evidence returned by `ProvenanceRegistry.guard()`, including its evidence
kind, references, scope, and assumptions. A DECLARED complete mutation-coverage
record can contribute to a VALID current guard under the registry's existing
rules; the returned evidence remains DECLARED and is not treated as an
independent observation. Type compatibility is not generally established by
this overlay. An explicitly typed `python.bool` or `builtins.bool` slot bound
to a `strided_tensor` materialization is reported as INCOMPATIBLE. A tensor
bool dtype is not treated as a Python bool singleton, and other types remain
unassessed until a typed scalar/object materialization model exists.

A historical interval proves which handle was bound at that event. The guard
is always checked at the registry's current event; it is not represented as a
historical guard. Re-validating after a mutation reads the changed registry
and returns the changed guard. No tensor or other runtime value is retained.

Call entry/exit ordinals and their evidence are caller-supplied. Validation
checks them against the instance, scope, and registry clock, but it does not
replay an independent runtime event log. Validation is also not an atomic
snapshot of the mutable bundle and registry. The caller must provide stable
models for the entire validation, for example by holding an external lock or
validating immutable snapshots.

Missing slots and unclassified semantic reads remain explicit coverage gaps.
They do not become Observed because another operation or observation points
to the same version. The overlay evidence must match the corresponding
registry binding interval's evidence claim. Declared remains Declared.
Q cannot replace an interval, a mutation-coverage record, or an equality
witness.

## Strict wire format

to_dict() and to_json() serialize only the typed clock, calls, and bindings,
in deterministic order. from_dict() and from_json() reject unknown fields,
unsupported schema versions, malformed typed IDs, duplicate records/JSON
fields, noncanonical ordering, and non-finite JSON values. Deserialization
validates the document's structure only. Callers must still run
validate(bundle, registry) against current external models; no saved status is
trusted.

## Deliberate limits

Slot coverage covers formal slots and semantic READS_SLOT edges represented
in the supplied graph. It cannot discover hidden Python reads, unmodeled
external state, aliases absent from the registry, or missing semantic edges.
ProvenanceRegistry.guard() reports readiness and mutation/alias coverage for
the current registry state; a VALID guard is not a proof that two handles
are equal or that two invocations are interchangeable. This overlay is one
input to later REUSE work, not an optimization permission.

The current ProvenanceRegistry materialization path represents physical
strided-tensor storage and requires a storage region. It cannot represent a
Python bool singleton output or other scalar/object-only result faithfully.
Structural tests may use registered tensor handles to exercise this overlay;
they do not exercise the planned Python is/is-not positive proof. That needs
a truthful scalar/object handle model in a later step, not fabricated tensor
storage.
