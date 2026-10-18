from dataclasses import FrozenInstanceError, replace

import pytest

from scar.ir.execution.common import EvidencePoint, MissingEvidence, Unresolved
from scar.ir.execution.content import (
    ContentRead,
    DataIdentity,
    EndpointContent,
    EvidenceEdgeRef,
    EvidenceObservationRef,
    HostConsumer,
    NativeInputRef,
    NativeOutputRef,
    NativeWorkRead,
    ObjectIdentity,
    ObjectRef,
    ObservationConsumer,
    ProtocolInterval,
    ProtocolSelector,
    ResourceConsumer,
    StorageContent,
    ValueDenotation,
    VersionRef,
    WholeWorkRead,
    WorkEvidenceBinding,
)
from scar.ir.execution.coordinates import (
    AccessRef,
    BlockVisitID,
    OccurrencePhase,
    OccurrencePoint,
    OperationOccurrenceID,
    UseRef,
    ValueOccurrenceID,
)
from scar.ir.execution.coverage import RegionRef
from scar.ir.execution.ids import (
    ContentReadID,
    DenotationID,
    ObservationRootID,
    ProcessInstanceID,
    RunID,
    WorkEvidenceBindingID,
    WorkTicketID,
)
from scar.ir.execution.resources import InstanceTarget
from scar.ir.execution.work import MaterializationRef
from scar.ir.program.ids import NativeBoundaryID, UseID
from scar.ir.program.providers import ProviderArtifact, ProviderFactReference
from scar.ir.v2.ids import (
    LogicalValueID,
    MaterializationID,
    ObjectID,
    OperationInstanceID,
    StorageRegionID,
    ValueVersionID,
)


def _artifact(uri="memory://content"):
    return ProviderArtifact(uri, "a" * 64, 3, "content-test-v1")


def _fact(locator="/fact"):
    return ProviderFactReference(_artifact(), locator)


def _point(label="point"):
    return EvidencePoint(RunID("run"), ProcessInstanceID("process"), _fact("/" + label))


def _value_version(version=0):
    return ValueVersionID(LogicalValueID("logical"), version)


def _version_ref(version=0):
    return VersionRef(_artifact("memory://values"), _value_version(version))


def _denotation(identity=None, basis=None):
    return ValueDenotation(
        DenotationID("denotation"),
        ValueOccurrenceID("value-occurrence"),
        identity or DataIdentity(_version_ref()),
        basis or EvidenceObservationRef(_artifact("memory://evidence"), "obs-1"),
        _fact("/denotation"),
    )


def _content_read(*, consumer=None, placement=None, effect=None, anchor=None, basis=None):
    return ContentRead(
        ContentReadID("content-read"),
        consumer or HostConsumer(
            UseRef(OperationOccurrenceID("op-occurrence"), UseID("value-use")),
            ProtocolInterval(_point("start"), _point("end"), _fact("/read-protocol"),
                             _fact("/read-interval")),
        ),
        placement or StorageContent(
            MaterializationRef(_artifact("memory://values"), MaterializationID("mat")),
            RegionRef(_artifact("memory://values"), StorageRegionID("region")),
        ),
        effect,
        anchor or OccurrencePoint(OperationOccurrenceID("op-occurrence"), OccurrencePhase.BEFORE),
        (ValueOccurrenceID("state"),),
        basis or EvidenceEdgeRef(_artifact("memory://evidence"), "edge-1"),
        _fact("/content-read"),
    )


def test_scoped_denotations_keep_data_versions_and_object_identity_distinct():
    data = _denotation()
    ref = _denotation(
        identity=ObjectIdentity(ObjectRef(_artifact("memory://objects"), ObjectID("object"))),
        basis=EvidenceEdgeRef(_artifact("memory://edges"), "edge-ref"),
    )
    unresolved = _denotation(
        identity=Unresolved("version association absent", _point()),
        basis=Unresolved("no typed source port", _point()),
    )
    assert type(data.identity) is DataIdentity
    assert data.identity.version.version == _value_version()
    assert type(ref.identity) is ObjectIdentity
    assert ref.identity.object.object == ObjectID("object")
    assert type(unresolved.identity) is Unresolved

    # Equal bare IDs in distinct artifacts remain distinct scoped references.
    assert _version_ref() != VersionRef(_artifact("memory://other-values"), _value_version())
    assert ObjectRef(_artifact("memory://objects"), ObjectID("same")) != ObjectRef(
        _artifact("memory://other-objects"), ObjectID("same"))


def test_content_read_preserves_exact_use_access_and_consumer_variants():
    use = UseRef(OperationOccurrenceID("op-occurrence"), UseID("repeat-operand-2"))
    host = _content_read(consumer=HostConsumer(use, ProtocolInterval(
        _point("read-start"), _point("read-end"), _fact("/host-protocol"), _fact("/host-read"))))
    access = AccessRef(OperationOccurrenceID("write-op"), 1)
    work = _content_read(consumer=ResourceConsumer(
        access,
        NativeWorkRead(WorkTicketID("work-2"), ProtocolInterval(
            _point("kernel-start"), _point("kernel-end"), _fact("/kernel-protocol"),
            _fact("/kernel-read"))),
        NativeInputRef(NativeBoundaryID("native"), BlockVisitID("entry"), 2),
    ))
    operation_evidence = _content_read(consumer=ResourceConsumer(
        use, WholeWorkRead(WorkTicketID("work-1")),
        EvidenceEdgeRef(_artifact("memory://evidence"), "operation-read-edge"),
    ))
    observation = _content_read(consumer=ObservationConsumer(ObservationRootID("output-root")))
    effect_read = _content_read(effect=access)
    unresolved_effect = _content_read(effect=Unresolved("effect source absent", _point()))
    no_effect_intrinsic = _content_read(effect=None)

    assert host.consumer.subject == use
    assert work.consumer.read.ticket == WorkTicketID("work-2")
    assert work.consumer.input.position == 2
    assert operation_evidence.consumer.input.edge == "operation-read-edge"
    assert observation.consumer.root == ObservationRootID("output-root")
    assert effect_read.effect == access
    assert type(unresolved_effect.effect) is Unresolved
    assert no_effect_intrinsic.effect is None


def test_native_output_ref_retains_actual_occurrence_and_native_slot_position():
    ref = NativeOutputRef(
        NativeBoundaryID("boundary"), OperationOccurrenceID("raise-occurrence"), 1)
    assert ref.operation == OperationOccurrenceID("raise-occurrence")
    assert ref.position == 1
    assert ref != NativeOutputRef(
        NativeBoundaryID("boundary"), OperationOccurrenceID("return-occurrence"), 1)


def test_work_evidence_binding_is_ticket_scoped_not_just_host_operation_scoped():
    first = WorkEvidenceBinding(
        WorkEvidenceBindingID("binding-1"), WorkTicketID("kernel-a"),
        _artifact("memory://trace"), OperationInstanceID("host-op"), _fact("/bind-1"))
    second = WorkEvidenceBinding(
        WorkEvidenceBindingID("binding-2"), WorkTicketID("kernel-b"),
        _artifact("memory://trace"), OperationInstanceID("host-op"), _fact("/bind-2"))
    assert first.instance == second.instance
    assert first.ticket != second.ticket
    assert first.id != second.id


@pytest.mark.parametrize("factory", [
    lambda: VersionRef(_artifact(), ValueVersionID(LogicalValueID("lv"), True)),
    lambda: VersionRef(_artifact(), ValueVersionID("lv", 0)),
    lambda: VersionRef(_artifact(), ValueVersionID(LogicalValueID("lv"), -1)),
    lambda: ObjectRef(_artifact(), "object"),
    lambda: EvidenceEdgeRef(_artifact(), ""),
    lambda: EvidenceObservationRef(_artifact(), 9),
    lambda: NativeInputRef(NativeBoundaryID("b"), BlockVisitID("entry"), True),
    lambda: NativeOutputRef(NativeBoundaryID("b"), BlockVisitID("not-op"), 0),
    lambda: ValueDenotation(DenotationID("d"), ValueOccurrenceID("v"),
                            object(), EvidenceEdgeRef(_artifact(), "e"), _fact()),
    lambda: ValueDenotation(DenotationID("d"), ValueOccurrenceID("v"),
                            DataIdentity(_version_ref()), object(), _fact()),
    lambda: WorkEvidenceBinding(WorkEvidenceBindingID("w"), WorkTicketID("t"),
                                _artifact(), "instance", _fact()),
    lambda: ProtocolInterval("start", _point(), _fact(), _fact()),
    lambda: WholeWorkRead("ticket"),
    lambda: NativeWorkRead(WorkTicketID("t"), _fact()),
    lambda: HostConsumer(WorkTicketID("t"), ProtocolInterval(
        _point(), _point(), _fact(), _fact())),
    lambda: ResourceConsumer(UseRef(OperationOccurrenceID("op"), UseID("u")),
                             WorkTicketID("t"), Unresolved("gap", _point())),
    lambda: ObservationConsumer(WorkTicketID("not-root")),
    lambda: ProtocolSelector(_artifact()),
    lambda: StorageContent(MaterializationRef(_artifact(), MaterializationID("m")), _fact()),
    lambda: EndpointContent(MaterializationRef(_artifact(), MaterializationID("m")),
                            _fact(), Unresolved("gap", _point())),
    lambda: ContentRead(ContentReadID("r"), HostConsumer(
        UseRef(OperationOccurrenceID("op"), UseID("u")),
        ProtocolInterval(_point(), _point(), _fact(), _fact())),
        _fact(), None, OccurrencePoint(OperationOccurrenceID("op"), OccurrencePhase.BEFORE),
        (), EvidenceEdgeRef(_artifact(), "e"), _fact()),
])
def test_content_records_reject_wrong_variants_and_noncanonical_scalars(factory):
    with pytest.raises((TypeError, ValueError)):
        factory()


def test_records_are_frozen_slotted_and_revalidate_poisoned_nested_values():
    denotation = _denotation()
    content = _content_read()
    binding = WorkEvidenceBinding(
        WorkEvidenceBindingID("binding"), WorkTicketID("work"), _artifact(),
        OperationInstanceID("instance"), _fact())
    assert not hasattr(content, "__dict__")
    with pytest.raises(FrozenInstanceError):
        denotation.id = DenotationID("changed")

    poisoned_artifact = _artifact()
    object.__setattr__(poisoned_artifact, "sha256", "not-a-digest")
    with pytest.raises((TypeError, ValueError)):
        replace(VersionRef(_artifact(), _value_version()), artifact=poisoned_artifact)

    poisoned_version = _value_version()
    object.__setattr__(poisoned_version, "version", True)
    with pytest.raises((TypeError, ValueError)):
        replace(VersionRef(_artifact(), _value_version()), version=poisoned_version)

    poisoned_interval = ProtocolInterval(_point(), _point(), _fact(), _fact())
    object.__setattr__(poisoned_interval, "protocol", "foreign")
    with pytest.raises((TypeError, ValueError)):
        replace(HostConsumer(
            UseRef(OperationOccurrenceID("op"), UseID("u")),
            ProtocolInterval(_point(), _point(), _fact(), _fact())), interval=poisoned_interval)

    poisoned_source = _fact()
    object.__setattr__(poisoned_source, "locator", "")
    with pytest.raises((TypeError, ValueError)):
        replace(binding, source=poisoned_source)
