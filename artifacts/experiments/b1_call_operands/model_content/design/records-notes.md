# R2.3-D content record notes

Status: implementation notes for the records layer only. The records preserve typed associations; they do not establish that source artifacts are true or that a read happened.

## Scoped denotation

- `VersionRef(artifact, version)` scopes a logical `ValueVersionID` to one exact `ProviderArtifact`. It checks the nested logical ID and revision exactly; `bool` is rejected as an integer revision.
- `ObjectRef(artifact, object)` scopes an `ObjectID` the same way.
- `ValueDenotation(id, value, identity, basis, source)` associates one dynamic `ValueOccurrenceID` with a `DataIdentity(VersionRef)`, `ObjectIdentity(ObjectRef)`, or an `Unresolved` value. Its basis is one exact EEG edge, EEG observation, native input slot, native output slot, or unresolved reason.
- `EvidenceEdgeRef` and `EvidenceObservationRef` include the artifact identity. Their rows must be resolved and checked by the later validator; an EEG edge's operation/value endpoints do not identify an input-use or output-result ordinal.

Example: one object occurrence may remain `ObjectIdentity(obj)` across several reads while each `ContentRead` points at a different current materialization/version. Object identity does not freeze content.

## Native port associations

- `NativeInputRef(boundary, entry, position)` retains a declared input-slot position at a particular entry `BlockVisitID`.
- `NativeOutputRef(boundary, operation, position)` retains a declared output-slot position at a particular `OperationOccurrenceID` (including Return or Raise).
- These references do not claim that the native artifact exposed or consumed the slot. The validator must match the declared boundary and actual occurrence. If the artifact has no exact port record, the result remains an exact-port gap.

## Work and read consumers

- `WorkEvidenceBinding(id, ticket, artifact, instance, source)` binds one exact work ticket to one legacy `OperationInstanceID`. Two work tickets may share an instance and must remain separate consumers.
- `ProtocolInterval(start, end, protocol, source)` keeps the read interval and the protocol that describes it.
- `HostConsumer` names an exact core Use/Access subject and interval. `ResourceConsumer` names that subject, one exact work ticket (`WholeWorkRead` or `NativeWorkRead`), and an input association. `ObservationConsumer` names an exact observation root; it does not fabricate a work ticket.
- An `EvidenceEdgeRef` as a resource input is operation-level evidence only. It cannot replace a native input ordinal.

## Placement and state

- `StorageContent(materialization, selector)` reuses `MaterializationRef`; a `None` selector means the whole original storage region, subject to the validator confirming that the materialization has a region.
- `EndpointContent(materialization, target, selector)` associates an existing materialization with a resource target and exact use/access/protocol selector.
- `ContentRead` keeps consumer, placement, optional canonical Access/Invoke effect, occurrence anchor, state support occurrences, evidence basis, and source.
- State, binding, and protocol denotations are derived from existing core state accesses/current-state flow, binding records, and protocol value kinds. These records do not add parallel state or producer tables.

## Limits

The records layer does not decide whether a source basis proves a port, whether an EEG operation observation matches a specific `UseID`, whether an `OperationResult.index` matches an EEG production edge, or whether state contents map to a logical version. Those require exact artifact parsing and cross-record validation. Missing port ordinals remain unresolved; no locator or `FactSource` alone closes them.
