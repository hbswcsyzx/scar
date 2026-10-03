from copy import deepcopy
from dataclasses import replace

import pytest

import scar.ir.v2 as ir
from scar.ir.invocation_bindings_v2 import (
    InvocationBindingsV2, InvocationCall, InvocationClock, InvocationClockDomain,
    InvocationRole, InvocationSlotBinding, SlotCoverageState, StructureState,
    TypeCompatibilityState,
)
from scar.ir.provenance import (
    EventPoint, GuardState, MutationCoverage, ProvenanceRegistry,
)
from scar.ir.v2.ids import LogicalValueID, MaterializationID, ObjectID, ValueVersionID


def claim(reference="fixture:observer", scope="run"):
    return ir.EvidenceClaim(ir.EvidenceKind.OBSERVED, (reference,), scope=scope)


def _semantic_edge(graph, identity, operation, slot, relation=ir.SemanticRelation.READS_SLOT):
    graph.add_edge(ir.SemanticEdge(identity, relation,
        ir.SemanticEndpoint(ir.SemanticNodeKind.OPERATION, operation),
        ir.SemanticEndpoint(ir.SemanticNodeKind.VALUE_SLOT, slot), claim(identity)))


def fixture(*, formal_input=True, include_read=True):
    semantic, evidence = ir.SemanticGraph(), ir.EvidenceGraph()
    parent = ir.OperationDefinitionID("parent")
    operation = ir.OperationDefinitionID("operator")
    semantic.add_definition(ir.OperationDefinition(parent, ir.OperationKind.FUNCTION, "parent"))

    input_slot = ir.ValueSlotID("formal-input")
    state_slot = ir.ValueSlotID("formal-state")
    output_slot = ir.ValueSlotID("formal-output")
    actual_slot = ir.ValueSlotID("actual-read-owned-by-parent")
    formal_inputs = (input_slot,) if formal_input else ()
    semantic.add_definition(ir.OperationDefinition(
        operation, ir.OperationKind.OPERATOR, "operator", parent_id=parent,
        input_slots=formal_inputs, state_slots=(state_slot,), output_slots=(output_slot,)))
    if formal_input:
        semantic.add_slot(ir.ValueSlot(input_slot, "formal input", "input", owner=operation))
    semantic.add_slot(ir.ValueSlot(state_slot, "formal state", "state", owner=operation))
    semantic.add_slot(ir.ValueSlot(output_slot, "formal output", "output", owner=operation))
    semantic.add_slot(ir.ValueSlot(actual_slot, "actual source", "binding", owner=parent))
    if include_read:
        _semantic_edge(semantic, "reads-actual-slot", operation, actual_slot)

    instances = (
        ir.OperationInstanceID("call:one"),
        ir.OperationInstanceID("call:two"),
    )
    for identity in instances:
        evidence.add_instance(ir.OperationInstance(identity, operation, 13, 5))

    registry = ProvenanceRegistry(scope="run", namespace="invocation-fixture")
    allocation = registry.allocation("cpu", 16, "buffer", "buffer-lifetime")
    region = registry.region(allocation, 0, (4,), (1,), "float32")
    value = registry.origin(ObjectID("input-value"), region, claim("value-origin"),
                            coverage=ir.Completeness.COMPLETE)

    roles = []
    if formal_input:
        roles.append((InvocationRole.INPUT, input_slot))
    roles.extend(((InvocationRole.STATE, state_slot),))
    if include_read:
        roles.append((InvocationRole.READ, actual_slot))
    roles.append((InvocationRole.OUTPUT, output_slot))

    calls, bindings = [], []
    for identity in instances:
        entry = registry.event(identity.value + ":entry")
        for role, slot in roles:
            if role is InvocationRole.OUTPUT:
                continue
            event = entry
            evidence_claim = claim(f"binding:{identity.wire}:{role.value}:{slot.wire}")
            interval = registry.bind_slot(slot, value, evidence_claim,
                                          scope=identity.wire, event=event)
            bindings.append(InvocationSlotBinding(identity, role, slot, value, event,
                                                   interval.evidence))
        exit_event = registry.event(identity.value + ":exit")
        evidence_claim = claim(f"binding:{identity.wire}:OUTPUT:{output_slot.wire}")
        interval = registry.bind_slot(output_slot, value, evidence_claim,
                                      scope=identity.wire, event=exit_event)
        bindings.append(InvocationSlotBinding(identity, InvocationRole.OUTPUT,
                                               output_slot, value, exit_event,
                                               interval.evidence))
        instance = evidence.instances[identity]
        calls.append(InvocationCall(identity, operation, instance.process_id,
                                    instance.thread_id, entry, exit_event,
                                    claim(f"call:{identity.wire}")))

    bundle = ir.IRBundle(semantic, evidence, registry.graph)
    bundle.assert_valid()
    overlay = InvocationBindingsV2(
        InvocationClock("run", InvocationClockDomain.REGISTRY_EVENT_ORDINAL),
        tuple(calls), tuple(bindings))
    return bundle, registry, overlay, {
        "operation": operation, "instances": instances, "input": input_slot,
        "state": state_slot, "output": output_slot, "read": actual_slot,
        "handle": value, "region": region,
    }


def test_complete_two_call_overlay_connects_formal_slots_and_cross_owner_read():
    bundle, registry, overlay, ids = fixture()
    report = overlay.validate(bundle, registry)
    assert report.structure is StructureState.VALID
    assert report.slot_coverage is SlotCoverageState.COMPLETE
    assert report.bindings_currently_guarded
    assert len(report.guards) == 8
    assert all(item.state is GuardState.VALID for item in report.guards)
    assert all(item.slot != ids["read"] or item.role is InvocationRole.READ
               for item in overlay.bindings)
    assert InvocationBindingsV2.from_json(overlay.to_json()).to_json() == overlay.to_json()


def test_missing_formal_or_actual_read_slot_is_incomplete_not_inferred():
    bundle, registry, overlay, ids = fixture()
    missing_formal = replace(overlay, bindings=tuple(
        item for item in overlay.bindings
        if not (item.instance == ids["instances"][0]
                and item.role is InvocationRole.INPUT)))
    report = missing_formal.validate(bundle, registry)
    assert report.structure is StructureState.VALID
    assert report.slot_coverage is SlotCoverageState.INCOMPLETE
    assert (ids["instances"][0], InvocationRole.INPUT, ids["input"]) in report.missing_slots

    bundle2, registry2, overlay2, ids2 = fixture(formal_input=False, include_read=True)
    missing_read = replace(overlay2, bindings=tuple(
        item for item in overlay2.bindings
        if not (item.instance == ids2["instances"][0]
                and item.role is InvocationRole.READ)))
    report2 = missing_read.validate(bundle2, registry2)
    assert report2.structure is StructureState.VALID
    assert report2.slot_coverage is SlotCoverageState.INCOMPLETE
    assert (ids2["instances"][0], InvocationRole.READ, ids2["read"]) in report2.missing_slots
    assert any("READ" in gap and ids2["read"].wire in gap for gap in report2.coverage_gaps)


def test_empty_formal_inputs_do_not_hide_semantic_reads():
    bundle, registry, overlay, ids = fixture(formal_input=False, include_read=True)
    definition = bundle.semantic.definitions[ids["operation"]]
    assert not definition.input_slots
    assert overlay.validate(bundle, registry).slot_coverage is SlotCoverageState.COMPLETE
    assert any(item.role is InvocationRole.READ and item.slot == ids["read"]
               for item in overlay.bindings)


def test_duplicate_binding_wrong_role_and_owner_are_rejected():
    bundle, registry, overlay, ids = fixture()
    with pytest.raises(ValueError, match="unique by instance, role and slot"):
        replace(overlay, bindings=overlay.bindings + (overlay.bindings[0],))

    changed = []
    for item in overlay.bindings:
        if item.instance == ids["instances"][0] and item.role is InvocationRole.READ:
            changed.append(replace(item, role=InvocationRole.INPUT))
        else:
            changed.append(item)
    report = replace(overlay, bindings=tuple(changed)).validate(bundle, registry)
    assert report.structure is StructureState.INVALID
    assert any("formal slot owner differs" in error or "does not have role INPUT" in error
               for error in report.errors)


def test_unknown_instance_version_and_missing_registry_observer_are_invalid():
    bundle, registry, overlay, ids = fixture()
    unknown_call = replace(overlay.calls[0], instance=ir.OperationInstanceID("absent"))
    unknown_overlay = replace(overlay, calls=(unknown_call, *overlay.calls[1:]))
    assert unknown_overlay.validate(bundle, registry).structure is StructureState.INVALID

    unknown_handle = replace(
        ids["handle"],
        version=ValueVersionID(LogicalValueID("unknown-value"), 0),
        materialization=MaterializationID("unknown-materialization"))
    changed = tuple(replace(item, handle=unknown_handle)
                    if item.instance == ids["instances"][0]
                    and item.role is InvocationRole.INPUT else item
                    for item in overlay.bindings)
    report = replace(overlay, bindings=changed).validate(bundle, registry)
    assert report.structure is StructureState.INVALID
    assert any("unique live registry binding" in error or "value handle" in error
               for error in report.errors)

    no_observer = replace(overlay, bindings=tuple(
        item for item in overlay.bindings
        if not (item.instance == ids["instances"][0]
                and item.role is InvocationRole.INPUT)))
    report = no_observer.validate(bundle, registry)
    assert report.slot_coverage is SlotCoverageState.INCOMPLETE
    assert report.structure is StructureState.VALID


def test_expired_binding_interval_and_wrong_clock_or_process_are_rejected():
    bundle, registry, overlay, ids = fixture()
    first = next(item for item in overlay.bindings
                 if item.instance == ids["instances"][0]
                 and item.role is InvocationRole.INPUT)
    index = next(index for index, interval in enumerate(registry.bindings)
                 if interval.slot == first.slot and interval.scope == first.instance.wire)
    registry.bindings[index] = replace(registry.bindings[index], end_event=first.at)
    report = overlay.validate(bundle, registry)
    assert report.structure is StructureState.INVALID
    assert any("unique live registry binding" in error for error in report.errors)

    bundle2, registry2, overlay2, ids2 = fixture()
    altered_call = replace(overlay2.calls[0], process_id=999)
    bad_process = replace(overlay2, calls=(altered_call, *overlay2.calls[1:]))
    assert any("process differs" in error for error in bad_process.validate(bundle2, registry2).errors)
    bad_clock = replace(overlay2, clock=InvocationClock(
        "foreign-scope", InvocationClockDomain.REGISTRY_EVENT_ORDINAL))
    assert any("clock scope" in error or "event scope/clock" in error
               for error in bad_clock.validate(bundle2, registry2).errors)


def test_foreign_alias_and_observed_write_are_recomputed_as_current_guards():
    bundle, registry, overlay, ids = fixture()
    registry.set_coverage(ids["handle"], MutationCoverage(
        registry.scope, ir.Completeness.COMPLETE, foreign_aliases=("external-view",),
        evidence=(claim("alias-coverage"),)))
    report = overlay.validate(bundle, registry)
    assert report.structure is StructureState.VALID
    assert {item.state for item in report.guards} == {GuardState.NEEDS_VERIFICATION}

    bundle2, registry2, overlay2, ids2 = fixture()
    before = overlay2.validate(bundle2, registry2)
    assert {item.state for item in before.guards} == {GuardState.VALID}
    point = registry2.event("observed-write")
    registry2.mutate(ids2["handle"], ids2["region"], claim("observed-write"), event=point)
    after = overlay2.validate(bundle2, registry2)
    assert after.structure is StructureState.VALID
    assert {item.state for item in after.guards} == {GuardState.INVALID}
    assert {item.checked_at for item in after.guards} == {registry2.current_event}


def test_declared_coverage_evidence_stays_declared_in_current_guard_report():
    bundle, registry, overlay, ids = fixture()
    declared = ir.EvidenceClaim(
        ir.EvidenceKind.DECLARED, ("fixture:complete-mutation-coverage",), scope="run")
    registry.set_coverage(ids["handle"], MutationCoverage(
        registry.scope, ir.Completeness.COMPLETE, evidence=(declared,)))

    report = overlay.validate(bundle, registry)
    assert report.bindings_currently_guarded
    assert all(item.state is GuardState.VALID for item in report.guards)
    assert all(item.binding_evidence.kind is ir.EvidenceKind.OBSERVED
               for item in report.guards)
    assert all(declared in item.registry_evidence for item in report.guards)
    assert all(item.type_compatibility is TypeCompatibilityState.NOT_ESTABLISHED
               for item in report.guards)

    document = report.as_dict()
    assert "calls listed in this overlay" in document["slot_coverage_scope"]
    assert "not atomic" in document["validation_atomicity"]
    assert "optimization legality" in document["bindings_currently_guarded_scope"]
    input_guard = next(item for item in document["guards"] if item["role"] == "INPUT")
    assert input_guard["binding_evidence"]["kind"] == "Observed"
    assert any(item["kind"] == "Declared" for item in input_guard["registry_guard_evidence"])


def test_known_python_bool_slot_rejects_physical_tensor_and_ambiguous_type_is_unproved():
    bundle, registry, overlay, ids = fixture()
    bundle.semantic.slots[ids["input"]].semantic_type = "python.bool"
    report = overlay.validate(bundle, registry)
    assert report.structure is StructureState.INVALID
    assert report.compatibility_gaps
    assert all("INCOMPATIBLE" in item for item in report.compatibility_gaps)
    input_guards = [item for item in report.guards if item.slot == ids["input"]]
    assert input_guards
    assert all(item.type_compatibility is TypeCompatibilityState.INCOMPATIBLE
               for item in input_guards)

    bundle2, registry2, overlay2, ids2 = fixture()
    bundle2.semantic.slots[ids2["input"]].semantic_type = "bool"
    report2 = overlay2.validate(bundle2, registry2)
    assert report2.structure is StructureState.VALID
    assert not report2.compatibility_gaps
    input_guards2 = [item for item in report2.guards if item.slot == ids2["input"]]
    assert input_guards2
    assert all(item.type_compatibility is TypeCompatibilityState.NOT_ESTABLISHED
               for item in input_guards2)


def test_stale_materialization_at_binding_event_is_not_confused_with_current_guard():
    bundle, registry, overlay, ids = fixture()
    first = next(item for item in overlay.bindings
                 if item.instance == ids["instances"][0]
                 and item.role is InvocationRole.INPUT)
    validity = registry.validity[ids["handle"].materialization]
    registry.validity[ids["handle"].materialization] = replace(
        validity, end_event=first.at, state=GuardState.INVALID, reason="expired at sample",
        evidence=(claim("expired"),))
    report = overlay.validate(bundle, registry)
    assert report.structure is StructureState.INVALID
    assert any("unique live registry binding" in error
               or "not live at binding event" in error for error in report.errors)


def test_strict_serde_rejects_forged_status_and_context_check_catches_handle_tamper():
    _, _, overlay, _ = fixture()
    document = deepcopy(overlay.to_dict())
    document["validation"] = {"structure": "VALID"}
    with pytest.raises(ValueError, match="document fields"):
        InvocationBindingsV2.from_dict(document)

    bundle, registry, overlay, ids = fixture()
    document = deepcopy(overlay.to_dict())
    row = next(item for item in document["bindings"]
               if item["instance"]["value"] == ids["instances"][0].value
               and item["role"] == "INPUT")
    forged_object = ObjectID("forged-object").as_dict()
    row["handle"]["object_id"] = forged_object
    decoded = InvocationBindingsV2.from_dict(document)
    report = decoded.validate(bundle, registry)
    assert report.structure is StructureState.INVALID
    assert any("handle" in error or "interval handle mismatch" in error
               for error in report.errors)


def test_evidence_is_not_synthesized_or_upgraded_from_missing_binding():
    bundle, registry, overlay, ids = fixture()
    call = replace(overlay.calls[0],
                   evidence=ir.EvidenceClaim(ir.EvidenceKind.OBSERVED, (), scope="run"))
    changed = replace(overlay, calls=(call, *overlay.calls[1:]))
    report = changed.validate(bundle, registry)
    assert report.structure is StructureState.INVALID
    assert any("requires explicit observer references" in error for error in report.errors)
    assert all(item.evidence.kind is ir.EvidenceKind.OBSERVED for item in overlay.bindings)
