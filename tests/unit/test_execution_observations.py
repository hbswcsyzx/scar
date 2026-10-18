"""Explicit Q roots over canonical resources; no source/runtime readiness claim."""
from dataclasses import FrozenInstanceError, fields, replace

import pytest

from scar.ir.execution.common import EvidencePoint, Unresolved
from scar.ir.execution.coordinates import ExecutionRun, HostThreadInstance, OccurrencePhase, OccurrencePoint, ProcessInstance
from scar.ir.execution.ids import (
    ObservationRequirementID, ObservationRootID, OperationOccurrenceID,
    HostThreadInstanceID, ProcessInstanceID, ResourceBindingID, ResourceInstanceID, RunID, ValueOccurrenceID,
)
from scar.ir.execution.observations import (
    BoundEndpoint, ExternalEndpoint, OutputValue, RequiredOutput,
)
from scar.ir.execution.resources import InstanceTarget, ProcessTarget, ThreadTarget
from scar.ir.execution.snapshot import snapshot_for
from scar.ir.execution.validation import require_valid, validate
from scar.ir.program.ids import OperationID, ResourceRequirementID
from scar.ir.program.validation import require_valid as require_program_valid
from scar.ir.v2.contracts import ContractFacet
from scar.ir.v2.ids import ContractID, ValueSlotID
from tests.fixtures.execution_observation_graphs import observation_execution as _observation


def _report(program, model, graphs):
    return validate(model, program, semantic_graphs=graphs)


def _change_root(model, **changes):
    return replace(model, observation_roots=(replace(model.observation_roots[0], **changes),))


def _change_requirement(model, **changes):
    return replace(model, observation_requirements=(replace(model.observation_requirements[0], **changes),))


@pytest.mark.parametrize("options", ({}, {"output": True}, {"external": True},
                                     {"facet": ContractFacet.RNG}, {"facet": ContractFacet.EXCEPTION}))
def test_canonical_output_and_explicit_endpoint_roots_are_conditional_without_work(options):
    program, model, graphs = _observation(**options)
    require_program_valid(program)
    require_valid(model, program, semantic_graphs=graphs)
    report = _report(program, model, graphs)
    assert not report.issues
    assert report.gaps
    assert not model.submissions
    assert report.source_runtime_verified is False
    assert report.transformation_authorized is False
    assert any(row.code == "observation_source_protocol_unverified" for row in report.gaps)
    if not options.get("output"):
        assert any(row.code == "contract_endpoint_protocol_unverified" for row in report.gaps)


def test_endpoint_binding_owner_can_precede_actual_observation():
    program, model, graphs = _observation()
    assert model.requirements[0].owner == model.activations[0].id
    assert model.observation_roots[0].anchor.operation == model.operations[-1].id
    assert not _report(program, model, graphs).issues


def test_operation_owned_binding_can_be_observed_later_but_not_substituted_for_other_requirement():
    program, model, graphs = _observation()
    original = program.resource_requirements[0]
    extra = replace(original, id=ResourceRequirementID("operation-endpoint"), owner=OperationID("resource.use.0"))
    program = replace(program, resource_requirements=(*program.resource_requirements, extra))
    binding = replace(model.requirements[0], id=ResourceBindingID("operation-endpoint"),
                      requirement=extra.id, owner=OperationOccurrenceID("activation.0.resource.use.0"))
    model = replace(model, snapshot=snapshot_for(program), requirements=(*model.requirements, binding))
    model = _change_root(model, actual=BoundEndpoint(binding.id))
    report = _report(program, model, graphs)
    assert any(row.code == "observation_binding_requirement" for row in report.issues)
    requirement = model.observation_requirements[0]
    model = _change_requirement(model, target=replace(requirement.target, requirement=extra.id))
    require_program_valid(program)
    assert not _report(program, model, graphs).issues


def test_cross_activation_observation_is_not_falsely_claimed_or_forbidden():
    program, model, graphs = _observation(activations=2, anchor_activation=1)
    report = _report(program, model, graphs)
    assert not report.issues
    assert any(row.code == "observation_binding_activation_unverified" for row in report.gaps)


def test_external_observation_uses_real_evidence_interval_without_fake_core_work():
    program, model, graphs = _observation(external=True)
    root = model.observation_roots[0]
    point = model.activations[0].entry
    interval = replace(root.interval, start=point, end=point)
    model = _change_root(model, interval=interval, anchor=Unresolved("no exact host point", point), support=())
    report = _report(program, model, graphs)
    assert not report.issues
    assert any(row.code == "observation_anchor_unresolved" for row in report.gaps)
    assert not model.submissions


@pytest.mark.parametrize("thread", (False, True))
def test_known_external_process_and_thread_endpoint_cannot_cross_observer_process(thread):
    program, model, graphs = _observation(external=True)
    source = model.runs[0].source
    process = ProcessInstance(ProcessInstanceID("other-process"), model.runs[0].id, None, source)
    host_thread = HostThreadInstance(HostThreadInstanceID("other-thread"), process.id, None, source)
    target = ThreadTarget(host_thread.id) if thread else ProcessTarget(process.id)
    model = replace(model, processes=(*model.processes, process), threads=(*model.threads, host_thread))
    report = _report(program, _change_root(model, actual=ExternalEndpoint(target)), graphs)
    assert any(row.code == "observation_endpoint_process" for row in report.issues)


def test_unresolved_anchor_point_cannot_claim_current_support():
    program, model, graphs = _observation()
    model = _change_root(model, anchor=Unresolved("no canonical anchor", model.activations[0].entry))
    report = _report(program, model, graphs)
    assert any(row.code == "observation_anchor_support" for row in report.issues)


@pytest.mark.parametrize("case,code", (
    ("contract", "observation_contract"), ("slot", "observation_output_slot"),
    ("not-required", "observation_required_output"),
    ("binding", "observation_binding"), ("core-requirement", "observation_endpoint_requirement"),
    ("root-requirement", "observation_requirement"), ("output-value", "observation_output_value"),
    ("target", "content_target"),
))
def test_missing_or_wrong_exact_foreign_keys_are_issues(case, code):
    program, model, graphs = _observation(output=case in ("slot", "not-required", "output-value"))
    requirement = model.observation_requirements[0]
    if case == "contract":
        model = _change_requirement(model, contract=replace(requirement.contract, contract=ContractID("missing")))
    elif case in ("slot", "not-required"):
        model = _change_requirement(model, target=RequiredOutput(ValueSlotID("missing" if case == "slot" else "other")))
    elif case == "binding":
        model = _change_root(model, actual=BoundEndpoint(ResourceBindingID("missing")))
    elif case == "core-requirement":
        model = _change_requirement(model, target=replace(requirement.target, requirement=ResourceRequirementID("missing")))
    elif case == "root-requirement":
        model = _change_root(model, requirement=ObservationRequirementID("missing"))
    elif case == "output-value":
        model = _change_root(model, actual=OutputValue(ValueOccurrenceID("missing")))
    else:
        model = _change_requirement(model, target=replace(requirement.target,
            requirement=Unresolved("external endpoint", model.activations[0].entry)))
        model = _change_root(model, actual=ExternalEndpoint(InstanceTarget(ResourceInstanceID("missing"))))
    report = _report(program, model, graphs)
    assert any(row.code == code for row in report.issues), report


@pytest.mark.parametrize("output,actual,code", (
    (True, "binding", "observation_actual_kind"),
    (False, "output", "observation_actual_kind"),
    (False, "external", "observation_external_binding"),
))
def test_actual_variant_cannot_bypass_required_output_or_core_endpoint(output, actual, code):
    program, model, graphs = _observation(output=output)
    changed = (BoundEndpoint(model.requirements[0].id) if actual == "binding" else
               OutputValue(ValueOccurrenceID("activation.0.resource.handle")) if actual == "output" else
               ExternalEndpoint(model.requirements[0].target))
    report = _report(program, _change_root(model, actual=changed), graphs)
    assert any(row.code == code for row in report.issues)


def test_nonrequired_facet_does_not_become_endpoint_requirement():
    program, model, graphs = _observation(required=False)
    report = _report(program, model, graphs)
    assert any(row.code == "observation_required_facet" for row in report.issues)


def test_facet_must_be_present_in_the_exact_contract():
    program, model, graphs = _observation()
    requirement = model.observation_requirements[0]
    model = _change_requirement(model, target=replace(requirement.target, facet=ContractFacet.RNG))
    assert any(row.code == "observation_required_facet" for row in _report(program, model, graphs).issues)


@pytest.mark.parametrize("output,code", ((True, "observation_output_run"), (False, "observation_binding_run")))
def test_known_output_or_binding_from_another_run_cannot_be_observed(output, code):
    program, model, graphs = _observation(output=output)
    source = model.runs[0].source
    run = ExecutionRun(RunID("other-run"), source)
    process = ProcessInstance(ProcessInstanceID("other-process"), run.id, None, source)
    point = EvidencePoint(run.id, process.id, source)
    root = model.observation_roots[0]
    model = replace(model, runs=(*model.runs, run), processes=(*model.processes, process))
    model = _change_root(model, interval=replace(root.interval, start=point, end=point),
                         anchor=Unresolved("external observation point", point), support=())
    assert any(row.code == code for row in _report(program, model, graphs).issues)


def test_facet_label_alone_creates_no_observation_root():
    program, model, graphs = _observation()
    model = replace(model, observation_requirements=(), observation_roots=())
    assert not _report(program, model, graphs).issues
    assert not model.observation_roots


@pytest.mark.parametrize("case,code", (
    ("old-state", "stale_state"), ("missing-state", "state_support"),
    ("nonstate", "state_support"), ("reversed-interval", "content_interval_order"),
    ("anchor-operation", "point_operation"), ("output-before-producer", "observation_output_before_definition"),
))
def test_observation_state_and_interval_remain_original_current_ports(case, code):
    program, model, graphs = _observation(output=case == "output-before-producer")
    root = model.observation_roots[0]
    if case in ("old-state", "missing-state", "nonstate"):
        name = {"old-state": "activation.0.resource.initial", "missing-state": "missing",
                "nonstate": "activation.0.resource.handle"}[case]
        model = _change_root(model, support=(ValueOccurrenceID(name),))
    elif case == "reversed-interval":
        model = _change_root(model, interval=replace(root.interval, start=root.interval.end, end=root.interval.start))
    elif case == "anchor-operation":
        model = _change_root(model, anchor=OccurrencePoint(OperationOccurrenceID("missing"), OccurrencePhase.BEFORE))
    else:
        before = OccurrencePoint(model.operations[0].id, OccurrencePhase.BEFORE)
        model = _change_root(model, interval=replace(root.interval, start=before))
    report = _report(program, model, graphs)
    assert any(row.code == code for row in report.issues), report


def test_missing_semantic_snapshot_is_gap_but_wrong_supplied_snapshot_is_issue():
    program, model, graphs = _observation()
    missing = _report(program, model, {})
    assert not missing.issues
    assert any(row.code == "external_graph_unavailable" for row in missing.gaps)
    semantic = next(iter(graphs.values()))
    semantic.contracts[ContractID("required")].name = "changed after digest"
    assert any(row.code == "external_snapshot" for row in _report(program, model, graphs).issues)


def test_records_are_frozen_exact_and_revalidate_mutated_nested_records():
    _, model, _ = _observation()
    root, requirement = model.observation_roots[0], model.observation_requirements[0]
    assert not hasattr(root, "__dict__")
    assert tuple(field.name for field in fields(root)) == (
        "id", "requirement", "actual", "interval", "anchor", "support", "source")
    with pytest.raises(FrozenInstanceError):
        root.support = ()
    with pytest.raises(TypeError):
        replace(requirement.target, facet="external")
    with pytest.raises(TypeError):
        replace(root, support=list(root.support))
    with pytest.raises(TypeError):
        replace(root, actual={"binding": model.requirements[0].id})
    with pytest.raises(TypeError):
        replace(root, id=ObservationRequirementID("wrong-family"))
    object.__setattr__(root.interval, "protocol", "untyped")
    with pytest.raises(TypeError):
        replace(root)


def test_strict_nested_ids_do_not_accept_subclass_or_bool_payloads():
    class DerivedValue(ValueOccurrenceID):
        pass

    with pytest.raises(TypeError):
        OutputValue(DerivedValue("not-exact"))
    value = ValueOccurrenceID("observed")
    object.__setattr__(value, "value", True)
    with pytest.raises((TypeError, ValueError)):
        OutputValue(value)
