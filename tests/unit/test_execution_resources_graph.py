"""Resource/execution graph combinations, conditional declarations rather than runtime proof."""
from dataclasses import replace

import pytest

from scar.ir.execution.coordinates import OccurrencePhase, OccurrencePoint
from scar.ir.execution.ids import OperationOccurrenceID, ResourceBindingID, ValueOccurrenceID
from scar.ir.execution.resources import CapacityAt, ConstraintEvidence, EndedAt, ImplicitBinding, InstanceTarget, NativeHandle
from scar.ir.program.providers import ProviderFactReference
from scar.ir.execution.validation import require_valid, validate
from scar.ir.program.validation import require_valid as require_program_valid
from scar.ir.v2.ids import StorageAllocationID
from tests.fixtures.execution_resource_graphs import resource_execution_program, resource_execution_with_allocation


def test_two_activations_of_one_create_keep_occurrences_and_resources_distinct():
    program, model = resource_execution_program()
    require_program_valid(program)
    require_valid(model, program)
    report = validate(model, program)
    assert not report.issues
    assert report.gaps
    assert report.source_runtime_verified is False
    assert report.transformation_authorized is False
    assert len(model.activations) == len(model.resources) == len(model.realizations) == 2
    assert model.resources[0].id != model.resources[1].id
    assert model.resources[0].origin.operation != model.resources[1].origin.operation
    assert model.requirements[0].owner != model.requirements[1].owner
    assert {row.requirement for row in model.accesses[:2]} == {model.requirements[0].id}
    assert {row.requirement for row in model.accesses[2:]} == {model.requirements[1].id}


@pytest.mark.parametrize("external,implicit", ((True, False), (False, True), (True, True)))
def test_external_and_implicit_resources_keep_exact_owners_without_fake_handle(external, implicit):
    program, model = resource_execution_program(external=external, implicit=implicit)
    require_program_valid(program)
    require_valid(model, program)
    assert len(model.values) == len(program.values) * 2
    if implicit:
        assert all(row.handle is None for row in program.resource_uses)
        assert all(isinstance(row.handle, ImplicitBinding) for row in model.accesses)
    assert validate(model, program).gaps


def test_real_dup_and_open_ports_bind_distinct_native_handle_lifetimes():
    program, model = resource_execution_program(activations=1, native_handles=True)
    require_program_valid(program)
    require_valid(model, program)
    native = [row for row in model.handles if isinstance(row.handle, NativeHandle)]
    assert len(native) == len({row.handle.lifetime for row in native}) == 3
    assert native[0].target == native[1].target != native[2].target
    assert len({row.handle.value for row in native}) == 3
    assert len(model.resources) == 2


@pytest.mark.parametrize("which", ("entry-state", "previous-activation-state", "other-owner-binding", "handle-target"))
def test_current_access_support_and_owner_bindings_cannot_be_replaced(which):
    program, model = resource_execution_program()
    require_valid(model, program)
    access = model.accesses[0]
    if which == "entry-state":
        changed = replace(access, support=(ValueOccurrenceID("activation.0.resource.initial"),))
    elif which == "previous-activation-state":
        changed = replace(access, support=(ValueOccurrenceID("activation.1.resource.created"),))
    elif which == "other-owner-binding":
        changed = replace(access, requirement=ResourceBindingID("activation.1"))
    else:
        handles = (replace(model.handles[0], target=model.requirements[1].target), *model.handles[1:])
        changed_model = replace(model, handles=handles)
    if which != "handle-target":
        changed_model = replace(model, accesses=(changed, *model.accesses[1:]))
    report = validate(changed_model, program)
    assert report.issues, (which, report)


def test_a_create_realization_cannot_claim_a_different_static_operation():
    program, model = resource_execution_program()
    require_valid(model, program)
    changed = replace(model.realizations[0], site=model.operations[1].id)
    assert validate(replace(model, realizations=(changed, *model.realizations[1:])), program).issues


@pytest.mark.parametrize("which", ("valid", "allocation-as-file", "file-as-pool", "missing-allocation"))
def test_allocation_identity_is_reused_and_pool_role_is_not_allocation_identity(which):
    program, model, values = resource_execution_with_allocation()
    require_valid(model, program, value_graphs=values)
    placement, = model.placements
    assert len(model.resources) == 2  # OFD and pool, no parallel instance for allocation.
    if which == "valid":
        assert not validate(model, program, value_graphs=values).issues
        return
    if which == "allocation-as-file":
        changed = replace(model, requirements=(replace(model.requirements[0], target=placement.allocation),))
    elif which == "file-as-pool":
        changed = replace(model, placements=(replace(placement, pool=InstanceTarget(model.resources[0].id)),))
    else:
        allocation = replace(placement.allocation, allocation=StorageAllocationID("resource.unknown-allocation"))
        changed = replace(model, placements=(replace(placement, allocation=allocation),))
    assert validate(changed, program, value_graphs=values).issues


@pytest.mark.parametrize("end", ("after-close", "before-start"))
def test_handle_end_is_not_ignored_by_a_stable_region_requirement(end):
    program, model = resource_execution_program(activations=1, close=True)
    require_valid(model, program)
    operation = OperationOccurrenceID("activation.0.resource.close" if end == "after-close"
                                      else "activation.0.resource.acquire")
    phase = OccurrencePhase.AFTER if end == "after-close" else OccurrencePhase.BEFORE
    closed = replace(model.handles[0], end=EndedAt(OccurrencePoint(operation, phase), model.handles[0].source))
    assert validate(replace(model, handles=(closed,)), program).issues


def test_one_native_handle_lifetime_cannot_change_known_resource_target():
    program, model = resource_execution_program(activations=1, native_handles=True)
    require_valid(model, program)
    first, duplicate, independent = model.handles[1:]
    assert first.target == duplicate.target != independent.target
    reused = replace(independent, handle=replace(independent.handle, lifetime=first.handle.lifetime))
    assert validate(replace(model, handles=(*model.handles[:3], reused)), program).issues


def test_same_descriptor_number_does_not_coalesce_two_activation_lifetimes():
    program, model = resource_execution_program(native_handles=True, fixed_descriptor=3)
    require_program_valid(program)
    require_valid(model, program)
    firsts = [row for row in model.handles if isinstance(row.handle, NativeHandle)
              and row.id.value.endswith(".first")]
    assert len(firsts) == 2
    assert firsts[0].handle.value != firsts[1].handle.value
    assert firsts[0].handle.lifetime != firsts[1].handle.lifetime
    assert firsts[0].target != firsts[1].target
    assert validate(model, program).gaps  # Raw 3 is no runtime identity/liveness proof.


def test_static_explicit_handle_cannot_be_bypassed_by_implicit_binding():
    program, model = resource_execution_program(activations=1)
    require_valid(model, program)
    row = model.accesses[0]
    implicit = ImplicitBinding(ProviderFactReference(model.snapshot.artifact, "declared-selection"), row.support)
    changed = replace(row, handle=implicit)
    assert validate(replace(model, accesses=(changed, *model.accesses[1:])), program).issues


def test_explicit_handle_value_must_match_the_original_resource_reference_use():
    program, model = resource_execution_program()
    require_valid(model, program)
    handle = replace(model.handles[0], handle=replace(model.handles[0].handle,
        value=ValueOccurrenceID("activation.1.resource.handle")))
    assert validate(replace(model, handles=(handle, *model.handles[1:])), program).issues


@pytest.mark.parametrize("stale", (False, True))
def test_capacity_obligation_support_uses_current_state_not_entry_snapshot(stale):
    program, model = resource_execution_program(activations=1, capacity=True)
    require_valid(model, program)
    row = model.accesses[0]
    support = (ValueOccurrenceID("activation.0.resource.initial"),) if stale else row.support
    condition = ConstraintEvidence(CapacityAt(program.resource_requirements[0].id, 0), support, row.source)
    changed = replace(model, accesses=(replace(row, constraints=(condition,)), *model.accesses[1:]))
    report = validate(changed, program)
    if stale:
        assert report.issues
    else:
        assert not report.issues
        assert report.gaps  # A current declaration still does not prove actual capacity.
