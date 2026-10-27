"""Cross-record content associations retain canonical ports and scoped facts."""
from copy import deepcopy
from dataclasses import replace

import pytest

from scar.ir.execution.common import EvidencePoint, MissingEvidence
from scar.ir.execution.content import (
    ContentRead, DataIdentity, EvidenceEdgeRef, HostConsumer, NativeInputRef,
    NativeOutputRef, ObjectIdentity, ObjectRef, ProtocolInterval, ResourceConsumer,
    StorageContent, ValueDenotation,
)
from scar.ir.execution.coordinates import (
    ExecutionRun, OccurrencePhase, OccurrencePoint, ProcessInstance,
)
from scar.ir.execution.coverage import RegionRef
from scar.ir.execution.ids import DenotationID, ProcessInstanceID, RunID
from scar.ir.execution.model import LegacyOperationRef
from scar.ir.execution.query import ExecutionIndex
from scar.ir.execution.snapshot import external_artifact
from scar.ir.execution.validation import validate
from scar.ir.execution.work import MaterializationRef
from scar.ir.program.model import TerminatorKind
from scar.ir.v2.ids import ObjectID, OperationInstanceID
from tests.fixtures.execution_content_graphs import (
    content_connection_fixture,
    native_content_fixture,
)


def _check(program, model, values, evidence, semantic=None):
    return validate(model, program, value_graphs=values, evidence_graphs=evidence,
                    semantic_graphs={} if semantic is None else semantic)


def _codes(report):
    return {row.code for row in report.issues}


def _one(rows, identity):
    return next(row for row in rows if row.id == identity)


@pytest.mark.parametrize("options", [
    {},
    {"kind": "reference"},
    {"consumer": "work", "duplicate_use": True},
    {"observation": True},
])
def test_valid_content_connections_keep_their_own_scope_and_explicit_gaps(options):
    program, model, values, evidence, details = content_connection_fixture(**options)
    report = _check(program, model, values, evidence, details["semantic_graphs"])
    assert report.valid
    assert "content_exact_port_unresolved" in {row.code for row in report.gaps}
    if options.get("observation"):
        assert not model.submissions
        assert type(model.content_reads[0].consumer).__name__ == "ObservationConsumer"
    if options.get("consumer") == "work":
        assert len(model.submissions) == len(model.work_evidence_bindings) == 2
        assert len({row.consumer.subject.use for row in model.content_reads}) == 2
        assert len({row.consumer.read.ticket for row in model.content_reads}) == 2
        assert len({row.instance for row in model.work_evidence_bindings}) == 2


def test_equal_value_uses_remain_distinct_even_when_eeg_has_no_port_ordinal():
    program, model, values, evidence, details = content_connection_fixture(duplicate_use=True)
    read = model.content_reads
    assert len(read) == 2
    assert read[0].consumer.subject != read[1].consumer.subject
    assert read[0].consumer.subject.use != read[1].consumer.subject.use
    assert read[0].consumer.subject.operation == read[1].consumer.subject.operation
    actual_uses = [
        next(row for row in model.uses
             if row.operation == item.consumer.subject.operation
             and row.use == item.consumer.subject.use)
        for item in read
    ]
    assert actual_uses[0].value == actual_uses[1].value
    report = _check(program, model, values, evidence)
    assert report.valid
    assert sum(row.code == "content_exact_port_unresolved" for row in report.gaps) >= 1


def test_partial_source_pairing_stays_a_gap_and_never_fabricates_a_match():
    program, model, values, evidence, details = content_connection_fixture(wrong_source="producer")
    report = _check(program, model, values, evidence)
    assert report.valid
    assert "content_operation_source_unresolved" in {row.code for row in report.gaps}
    index = ExecutionIndex(model, program, value_graphs=values, evidence_graphs=evidence)
    denotation = index.denotation(details["data_value"])
    assert denotation["association"]["basis"]["correspondence"] == ()

    program, model, values, evidence, details = content_connection_fixture(
        consumer="work", wrong_source="read")
    report = _check(program, model, values, evidence)
    assert report.valid
    assert "content_work_source_unresolved" in {row.code for row in report.gaps}
    index = ExecutionIndex(model, program, value_graphs=values, evidence_graphs=evidence)
    result = index.content_read(details["read"])
    assert result["consumer_input"]["correspondence"] == ()

    model = replace(model, work_evidence_bindings=())
    report = _check(program, model, values, evidence)
    assert report.valid
    assert "content_work_source_unresolved" in {row.code for row in report.gaps}
    assert ExecutionIndex(model, program, value_graphs=values,
                          evidence_graphs=evidence).content_read(details["read"])[
                              "consumer_input"]["correspondence"] == ()


def test_data_version_and_storage_selector_are_exactly_scoped():
    program, model, values, evidence, details = content_connection_fixture()
    denotation = _one(model.denotations, DenotationID("content.denotation.data"))
    wrong_version = replace(denotation, identity=DataIdentity(details["other_version"]))
    bad_version_model = replace(model, denotations=(wrong_version,))
    report = _check(program, bad_version_model, values, evidence)
    assert {"content_source_version", "content_denotation_materialization"} & _codes(report)

    read = _one(model.content_reads, details["read"])
    wrong_region = RegionRef(details["value_graph_artifact"], details["other_region"])
    bad_placement = replace(read, placement=StorageContent(details["materialization"], wrong_region))
    bad_selector_model = replace(model, content_reads=(bad_placement,))
    report = _check(program, bad_selector_model, values, evidence)
    assert "content_selector_allocation" in _codes(report)


def test_missing_source_foreign_keys_and_known_process_conflict_are_issues():
    program, model, values, evidence, details = content_connection_fixture()
    denotation = model.denotations[0]
    missing_edge = replace(denotation,
        basis=EvidenceEdgeRef(details["evidence_artifact"], "content.edge.absent"))
    report = _check(program, replace(model, denotations=(missing_edge,)), values, evidence)
    assert "content_evidence_edge" in _codes(report)

    program, model, values, evidence, details = content_connection_fixture(kind="reference")
    reference = model.denotations[0]
    missing_object = replace(reference,
        identity=ObjectIdentity(ObjectRef(details["evidence_artifact"], ObjectID("content.object.absent"))))
    report = _check(program, replace(model, denotations=(missing_object,)), values, evidence)
    assert "content_object" in _codes(report)

    program, model, values, evidence, details = content_connection_fixture(consumer="work")
    old_artifact = details["evidence_artifact"]
    graph = deepcopy(evidence[old_artifact.sha256])
    ticket_binding = model.work_evidence_bindings[0]
    instance = graph.instances[ticket_binding.instance]
    graph.instances[ticket_binding.instance] = replace(instance, process_id=999)
    new_artifact = external_artifact(graph, "memory:content-evidence-wrong-process")
    evidence = {new_artifact.sha256: graph}

    def remap_artifact(artifact):
        return new_artifact if artifact == old_artifact else artifact

    evidence_bindings = tuple(replace(row,
        legacy=replace(row.legacy, artifact=remap_artifact(row.legacy.artifact)))
        for row in model.evidence_bindings)
    work_bindings = tuple(replace(row, artifact=remap_artifact(row.artifact))
                          for row in model.work_evidence_bindings)
    denotations = tuple(replace(row, basis=replace(row.basis,
        artifact=remap_artifact(row.basis.artifact))) for row in model.denotations)
    reads = []
    for row in model.content_reads:
        consumer = row.consumer
        if type(consumer) is ResourceConsumer:
            consumer = replace(consumer, input=replace(consumer.input,
                artifact=remap_artifact(consumer.input.artifact)))
        reads.append(replace(row, consumer=consumer,
            basis=replace(row.basis, artifact=remap_artifact(row.basis.artifact))))
    model = replace(model, evidence_bindings=evidence_bindings,
                    work_evidence_bindings=work_bindings, denotations=denotations,
                    content_reads=tuple(reads))
    report = _check(program, model, values, evidence)
    assert "content_work_process" in _codes(report)


def test_reference_read_keeps_exact_effect_and_current_state_support():
    program, model, values, evidence, details = content_connection_fixture(kind="reference")
    read = _one(model.content_reads, details["read"])
    assert read.effect is not None
    report = _check(program, model, values, evidence)
    assert report.valid
    assert "content_state_version_unverified" in {row.code for row in report.gaps}

    missing_before = replace(read, support=())
    report = _check(program, replace(model, content_reads=(missing_before,)), values, evidence)
    assert "content_missing_state_support" in _codes(report)

    # A ReferenceValue remains an object identity; the same content-version
    # association used for DataValue is structurally invalid.
    ref_value = read.consumer.subject
    ref_denotation = model.denotations[0]
    bad_identity = replace(ref_denotation, identity=DataIdentity(details["version"]))
    report = _check(program, replace(model, denotations=(bad_identity,)), values, evidence)
    assert "content_denotation_kind" in _codes(report)


def test_host_interval_must_match_subject_run_and_operation():
    program, model, values, evidence, details = content_connection_fixture()
    read = _one(model.content_reads, details["read"])
    missing = MissingEvidence("second run is a typed fixture point only")
    other_run, other_process = RunID("content.other.run"), ProcessInstanceID("content.other.process")
    point = EvidencePoint(other_run, other_process, missing)
    interval = ProtocolInterval(point, point, read.consumer.interval.protocol, missing)
    model = replace(model,
        runs=(*model.runs, ExecutionRun(other_run, missing)),
        processes=(*model.processes, ProcessInstance(other_process, other_run, 12, missing)),
        content_reads=(replace(read, consumer=HostConsumer(read.consumer.subject, interval)),))
    report = _check(program, model, values, evidence)
    assert "content_interval_subject_scope" in _codes(report)

    program, model, values, evidence, details = content_connection_fixture()
    read = _one(model.content_reads, details["read"])
    producer = next(row.id for row in model.operations
                    if row.operation.value == "content.produce")
    interval = ProtocolInterval(
        OccurrencePoint(producer, OccurrencePhase.BEFORE),
        OccurrencePoint(producer, OccurrencePhase.AFTER),
        read.consumer.interval.protocol, read.consumer.interval.source)
    model = replace(model, content_reads=(replace(read,
        consumer=HostConsumer(read.consumer.subject, interval)),))
    report = _check(program, model, values, evidence)
    assert "content_interval_subject_order" in _codes(report)


@pytest.mark.parametrize("completion", ("return", "raise"))
def test_native_basis_selects_exact_initial_entry_and_completion_slot(completion):
    program, model, values, evidence, details = native_content_fixture(completion=completion)
    report = _check(program, model, values, evidence)
    assert report.valid
    assert "content_native_correspondence_unverified" in {row.code for row in report.gaps}
    input_row = next(row for row in model.denotations if isinstance(row.basis, NativeInputRef))
    output_row = next(row for row in model.denotations if isinstance(row.basis, NativeOutputRef))
    assert input_row.basis.entry == details["entry"]
    assert output_row.basis.operation == details["operation"]
    term = next(row.terminator for row in program.operations
                if row.id == next(item.operation for item in model.operations
                                  if item.id == details["operation"]))
    assert term.kind is (TerminatorKind.RETURN if completion == "return" else TerminatorKind.RAISE)

    bad_output = replace(output_row, basis=replace(output_row.basis, position=99))
    bad_model = replace(model, denotations=tuple(
        bad_output if row.id == output_row.id else row for row in model.denotations))
    report = _check(program, bad_model, values, evidence)
    assert "content_native_position" in _codes(report)


def test_native_duplicate_output_positions_keep_distinct_uses_for_the_same_value():
    program, model, values, evidence, details = native_content_fixture(completion="return")
    output_row = next(row for row in model.denotations if isinstance(row.basis, NativeOutputRef))
    occurrence = next(row for row in model.operations if row.id == details["operation"])
    static_operation = next(row for row in program.operations if row.id == occurrence.operation)
    assert static_operation.terminator.values[0] != static_operation.terminator.values[1]
    second_use_id = static_operation.terminator.values[1]
    second_use = next(row for row in model.uses
                      if row.operation == occurrence.id and row.use == second_use_id)
    assert second_use.value == output_row.value
    duplicate = replace(output_row, value=second_use.value,
                        basis=replace(output_row.basis, position=1))
    model = replace(model, denotations=tuple(
        duplicate if row.id == output_row.id else row for row in model.denotations))
    report = _check(program, model, values, evidence)
    assert report.valid

    state_use_id = static_operation.terminator.values[2]
    state_value = next(row.value for row in model.uses
                       if row.operation == occurrence.id and row.use == state_use_id)
    wrong_actual = replace(duplicate, value=state_value,
                           basis=replace(duplicate.basis, position=0))
    wrong_actual_model = replace(model, denotations=tuple(
        wrong_actual if row.id == duplicate.id else row for row in model.denotations))
    report = _check(program, wrong_actual_model, values, evidence)
    assert "content_native_actual" in _codes(report)

    wrong_port = replace(duplicate, basis=replace(duplicate.basis, position=2))
    model = replace(model, denotations=tuple(
        wrong_port if row.id == duplicate.id else row for row in model.denotations))
    report = _check(program, model, values, evidence)
    assert "content_native_exit" in _codes(report)


def test_native_input_cannot_be_replaced_by_a_later_visit():
    program, model, values, evidence, details = native_content_fixture(completion="raise")
    input_row = next(row for row in model.denotations if isinstance(row.basis, NativeInputRef))
    later_visit = model.visits[-1].id
    assert later_visit != details["entry"]
    bad_input = replace(input_row, basis=replace(input_row.basis, entry=later_visit))
    model = replace(model, denotations=tuple(
        bad_input if row.id == input_row.id else row for row in model.denotations))
    report = _check(program, model, values, evidence)
    assert "content_native_entry" in _codes(report)
