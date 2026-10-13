# Python object-reference observations

`PythonObjectObserver` records direct Python references within one capture.
An `ObjectID` names the object reference seen by that observer. It does not
mean that two values have equal contents, share Tensor storage, or have equal
contents over time.

Each object gets one fixed `PythonObjectHandle`:

```text
ObjectID + python.object_reference ValueVersionID + MaterializationID
```

The object reference has one logical version for this capture. Mutating a list,
Tensor, NumPy array, or another object does not create a new identity version
and does not prove its contents stayed stable. The observer does not call the
value's `__eq__`, `__hash__`, or `__repr__`, inspect Tensor data, or copy any
value.

## Object table and graph projection

`observer.model.objects` maps each `ObjectID` to a `PythonObjectRecord` with its
fixed handle, representation and tracking method. The record projects into an
ordinary `ValueGraph` as one `python.object_reference` logical value and
version, one `ObjectBinding`, and one materialization with
`representation="python_object_identity"` and `region=None`. This projection
describes a captured Python reference; it does not claim a physical allocation,
copy, storage region, device transfer, or ready event.

An unannotated `region=None` materialization remains unclassified. Only the
matching object table row and its cross-checked graph records establish this
overlay. Each call to `observe` appends a `ReferenceObservation` with a unique
`observation_id`; repeated samples reuse the same handle and materialization.
This preserves separate operand occurrences without inventing physical copies.

For exact Python bools, classification occurs only after `type(value) is bool`.
`True` and `False` use separate `BOOL_TRUE` and `BOOL_FALSE` object rows. Repeated
observations of either singleton reuse its handle, while each sample remains a
separate observation. The producer and return event for a bool result belong to
the execution record, not to this object table.

The sample's `type_category` is `builtins.bool` only for an exact bool and
`builtins.NoneType` only for `None`; other values receive the fixed opaque
category `opaque.python-object`. The observer does not read class names or
module attributes, since metaclass descriptors and mutable class attributes
could run code or spoof a built-in type name.

## Events and capture lifetime

Each observer adds a random suffix to its internal scope and namespace. Two
observers cannot treat matching user labels, object addresses, or event ordinals
as shared identity or shared time. `event(label)` issues the observer's next
`EventPoint`; `observe(..., at=...)` accepts only an event issued by that
observer and only its current event. Multiple operands can use one current
event.

Weak references are used by default. The collector verifies a repeated
reference with `is`, after using the runtime address only to select candidates.
A weak reference is only an identity lookup aid: it does not create a lifetime
interval and an expired reference does not mark the historical object dead.
The observer does not provide a live reuse guard.

Objects that cannot be weakly referenced are rejected unless
`allow_strong_leases=True` and a finite `max_strong_leases` is supplied. A lease
holds one strong reference per captured object and is limited by object count,
not by retained bytes. `close()` releases all leases. Collection can therefore
extend object reachability and affect runtime behavior; it is an observation
instrument, not a transparent operation.

## Historical evidence and serialization

`observer.attest_observation(handle, at, observation_id=None)` checks a sample
against the collector's private record of a real `observe` call and the
corresponding model row. It attests only that historical sample. It does not
check current liveness or support a future call. Attestation remains historical
after `close()` because the private sample record contains only the sampled
identifiers and event, not the target object.

`PythonObjectModel.to_json()` and `from_json()` use the shared `record_codec`
for typed records and the existing ValueGraph codec for the graph projection.
Loading JSON validates its schema and joins, but creates no runtime reference,
private sample record, live guard, or capture authority. Saved JSON is a
historical artifact, not authentication: structure checks reject inconsistent
links, while a coherent rewrite of an artifact cannot be authenticated without
an external signature.

The model exposes `scope`, `namespace`, `process_id`, `current_event`,
`objects`, `observations`, and `graph`. Call `model.validate()` to check the
typed table and its ValueGraph projection.
