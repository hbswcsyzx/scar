import pytest

from scar.ir.execution.common import EvidencePoint, MissingEvidence, Unresolved
from scar.ir.execution.coordinates import (
    AccessRef,
    BlockVisit,
    CaptureIngress,
    ControlTransfer,
    ExecutionRun,
    ExecutionSegment,
    HostThreadInstance,
    InitialEntry,
    OperationOccurrence,
    OccurrencePhase,
    OccurrencePoint,
    ProcessInstance,
    ProgramSnapshot,
    RegionActivation,
    ResumeIngress,
    UnresolvedHostThread,
    UseOccurrence,
    UseRef,
    ValueOccurrence,
)
from scar.ir.execution.ids import (
    BlockVisitID,
    ExecutionSegmentID,
    HostThreadInstanceID,
    OperationOccurrenceID,
    ProcessInstanceID,
    RegionActivationID,
    ResourceAccessID,
    ResourceBindingID,
    ResourceInstanceID,
    RunID,
    ValueOccurrenceID,
)
from scar.ir.program.ids import BlockID, OperationID, RegionID, UseID, ValueID
from scar.ir.program.providers import ProviderArtifact, ProviderFactReference
from scar.ir.record_codec import decode, encode


def _artifact():
    return ProviderArtifact("mem://execution", "a" * 64, 0, "test-evidence")


def _source():
    return ProviderFactReference(_artifact(), "manifest:1")


def _point(process=None):
    return EvidencePoint(
        RunID("run-1"), process, ProviderFactReference(_artifact(), "event:1"))


def test_distinct_execution_id_namespaces_and_basic_coordinate_chain():
    assert RunID("x").wire == "exec_run:x"
    assert ProcessInstanceID("x").wire == "exec_process_instance:x"
    assert ResourceInstanceID("x").wire == "exec_resource_instance:x"
    assert ResourceBindingID("x").wire != ResourceAccessID("x").wire

    run = ExecutionRun(RunID("run-1"), _source())
    process = ProcessInstance(ProcessInstanceID("p-1"), run.id, 0, _source())
    thread = HostThreadInstance(HostThreadInstanceID("t-1"), process.id, 0, _source())
    activation = RegionActivation(
        RegionActivationID("a-1"), RegionID("function"), process.id,
        _point(process.id))
    segment = ExecutionSegment(
        ExecutionSegmentID("s-1"), activation.id, thread.id, InitialEntry(_point(process.id)))
    visit = BlockVisit(BlockVisitID("b-visit-1"), segment.id, BlockID("entry"))
    operation = OperationOccurrence(
        OperationOccurrenceID("op-1"), visit.id, OperationID("op"))
    value = ValueOccurrence(ValueOccurrenceID("value-1"), ValueID("value"), operation.id)
    use = UseOccurrence(operation.id, UseID("x-use"), value.id)
    transfer = ControlTransfer(operation.id, 0, visit.id)
    access = AccessRef(operation.id, 0)
    use_ref = UseRef(operation.id, use.use)
    before = OccurrencePoint(operation.id, OccurrencePhase.BEFORE)
    edge = OccurrencePoint(operation.id, OccurrencePhase.EDGE, 0)

    assert (process.pid, thread.tid) == (0, 0)
    assert use.value == value.id
    assert transfer.successor_index == access.index == 0
    assert use_ref.use == use.use
    assert before.successor_index is None
    assert edge.phase is OccurrencePhase.EDGE


def test_explicit_gaps_keep_evidence_points_without_fabricated_identity():
    missing = MissingEvidence("thread ID was not collected")
    point = EvidencePoint(RunID("run"), None, missing)
    unknown_thread = UnresolvedHostThread("thread incarnation unknown", point)
    segment = ExecutionSegment(
        ExecutionSegmentID("segment"), RegionActivationID("activation"),
        unknown_thread, CaptureIngress(point, "captured block entry"))
    unresolved_value = Unresolved("reaching definition was outside the trace", point)
    occurrence = UseOccurrence(
        OperationOccurrenceID("operation"), UseID("use"), unresolved_value)

    assert segment.host_thread is unknown_thread
    assert occurrence.value is unresolved_value


def test_provider_fact_reference_and_snapshot_roundtrip_through_strict_codec():
    snapshot = ProgramSnapshot(_artifact(), 14)
    point = _point(ProcessInstanceID("p"))
    records = (
        ExecutionRun(RunID("run"), _source()),
        snapshot,
        point,
        ResumeIngress(OperationOccurrenceID("suspend"), 1, point),
        OccurrencePoint(OperationOccurrenceID("operation"), OccurrencePhase.EDGE, 1),
        UseRef(OperationOccurrenceID("operation"), UseID("use")),
        Unresolved("source gap", point),
    )
    for record in records:
        restored = decode(type(record), encode(record))
        assert restored == record


@pytest.mark.parametrize("field,value", [
    ("schema_version", True),
    ("schema_version", 0),
])
def test_snapshot_rejects_boolean_or_nonpositive_schema_version(field, value):
    fields = {"artifact": _artifact(), "schema_version": 14}
    fields[field] = value
    with pytest.raises((TypeError, ValueError)):
        ProgramSnapshot(**fields)


@pytest.mark.parametrize("factory", [
    lambda: ProcessInstance(ProcessInstanceID("p"), RunID("r"), True, _source()),
    lambda: HostThreadInstance(HostThreadInstanceID("t"), ProcessInstanceID("p"), False, _source()),
    lambda: ResumeIngress(OperationOccurrenceID("s"), True, _point()),
    lambda: ControlTransfer(OperationOccurrenceID("o"), False, BlockVisitID("b")),
    lambda: AccessRef(OperationOccurrenceID("o"), True),
])
def test_integer_coordinates_reject_bool(factory):
    with pytest.raises(TypeError):
        factory()


def test_nested_records_and_union_variants_are_exact_and_revalidated():
    class ChildRunID(RunID):
        pass

    with pytest.raises(TypeError):
        ExecutionRun(ChildRunID("r"), _artifact())
    with pytest.raises(TypeError):
        ExecutionSegment(
            ExecutionSegmentID("s"), RegionActivationID("a"),
            "thread", InitialEntry(_point()))
    with pytest.raises(TypeError):
        ValueOccurrence(ValueOccurrenceID("v"), ValueID("value"), UseID("wrong-origin"))
    with pytest.raises(TypeError):
        UseOccurrence(OperationOccurrenceID("op"), UseID("use"), "value")
    with pytest.raises(TypeError):
        RegionActivation(
            RegionActivationID("a"), RegionID("r"), ProcessInstanceID("p"),
            "not an evidence point")

    corrupted = _artifact()
    object.__setattr__(corrupted, "schema", "")
    with pytest.raises(ValueError):
        ProgramSnapshot(corrupted, 14)


def test_provider_reference_is_rechecked_after_nested_mutation():
    artifact = _artifact()
    reference = ProviderFactReference(artifact, "fact:1")
    object.__setattr__(reference, "locator", "")
    with pytest.raises(ValueError):
        EvidencePoint(RunID("run"), None, reference)


@pytest.mark.parametrize("phase,index", [
    (OccurrencePhase.BEFORE, 0),
    (OccurrencePhase.AFTER, 0),
    (OccurrencePhase.EDGE, None),
    (OccurrencePhase.EDGE, True),
    (OccurrencePhase.EDGE, -1),
])
def test_occurrence_point_requires_index_only_for_edge(phase, index):
    with pytest.raises((TypeError, ValueError)):
        OccurrencePoint(OperationOccurrenceID("op"), phase, index)

