"""Symbolic resource interfaces preserve identities and never assert execution."""
from dataclasses import replace

from scar.analysis.build_resources import BuildResourceProvider, attach_build_resources
from scar.ir.program.dependencies import DependencyPoint, GraphNamespace, DependencyStrength
from scar.ir.program.ids import OperationID, ValueID, RegionID
from scar.ir.program.model import Operation, Behavior
from scar.ir.program.providers import ProviderArtifact
from scar.ir.program.source_references import SourceArtifactLocator
from scar.ir.program.resources import ResourceDefinition, ResourceRequirement, ResourceKind


class View:
    def __init__(self):
        self.providers = []

    def register(self, provider):
        self.providers.append(provider)


def operation():
    artifact = ProviderArtifact('/tmp/resource-test.json', '1' * 64, 1, 'test')
    locator = SourceArtifactLocator(artifact, artifact.sha256, 1, 'canonical-json')
    namespace = GraphNamespace(locator, 'test', RegionID('root'))
    point = DependencyPoint(namespace, OperationID('original'), None)
    value = DependencyPoint(namespace, ValueID('original-value'), None)
    return point, value, Operation(point.node, 'torch.save .to cuda', (Behavior.COMPUTE,))


def test_labels_do_not_select_device_or_file_effects_and_original_ports_survive():
    point, value, original = operation()
    provider = attach_build_resources(View(), operations=((point, (value,), original),))
    requirements = [r for r in provider.records.values() if type(r) is ResourceRequirement]
    assert {r.kind for r in requirements} == {ResourceKind.CPU, ResourceKind.MEMORY}
    assert all(r.owner == point.node for r in requirements)
    assert any(e.target == point for e in provider.edges)
    assert any(e.target == value for e in provider.edges)
    assert all(e.strength is DependencyStrength.MAY for e in provider.edges
               if type(provider.records.get(e.source)) is ResourceDefinition)
    assert any(f.kind == 'UNRESOLVED_EXTERNAL_RESOURCE_INTERFACE' for f in provider.frontiers)
    assert provider.payload()['actual_events'] == []
    assert not provider.payload()['transfers_observed']


def test_explicit_interface_hints_are_guarded_and_storage_candidates_remain_symbolic():
    point, value, original = operation()
    provider = attach_build_resources(View(), operations=((point, (value,), original),),
                                      resource_hints={point: ('file', 'gpu')})
    requirements = [r for r in provider.records.values() if type(r) is ResourceRequirement]
    assert {r.kind for r in requirements} >= {ResourceKind.FILE, ResourceKind.STORAGE, ResourceKind.GPU}
    for edge in provider.edges:
        record = provider.records.get(edge.source)
        if type(record) is ResourceRequirement and record.kind in (
                ResourceKind.FILE, ResourceKind.GPU, ResourceKind.STORAGE):
            assert edge.conditions and edge.strength is DependencyStrength.MAY
    assert len(provider.frontiers) == 1


def test_payload_roundtrip_and_lazy_repeated_body_admission():
    point, value, original = operation()
    provider = attach_build_resources(View())
    provider.add_operations(((point, (value,), original),))
    before = provider.payload()
    provider.add_operations(((point, (value,), original),))
    assert provider.payload() == before
    restored = BuildResourceProvider.from_payload(View(), before)
    assert restored.payload() == before
    assert restored.incoming(point) == provider.incoming(point)
    assert restored.outgoing(value) == provider.outgoing(value)
    requirement = next(p for p, r in restored.records.items() if type(r) is ResourceRequirement)
    assert restored.describe(requirement).owner == point
    assert restored.original(requirement).owner == point.node
    restored.add_operations(((point, (value,), original),))
    assert restored.payload() == before


def test_behavior_candidates_connect_device_and_file_ports_without_new_demands():
    point, value, original = operation()
    original = replace(original, behaviors=(Behavior.COMPUTE, Behavior.READ))
    provider = attach_build_resources(View())
    provider.add_operation(point, (value,), original, candidates=True)
    requirements = [r for r in provider.records.values() if type(r) is ResourceRequirement]
    assert {r.kind for r in requirements} == {ResourceKind.CPU, ResourceKind.MEMORY}
    candidate_edges = [e for e in provider.edges if '.possible-' in e.evidence[0].rule]
    assert len(candidate_edges) == 10  # Five resources, each attached to op and data port.
    assert {provider.records[e.source].origin.port for e in candidate_edges} == {
        'symbolic:gpu', 'symbolic:device-memory', 'symbolic:file', 'symbolic:ssd', 'symbolic:nvme'}
    assert {e.target for e in candidate_edges} == {point, value}
    assert all(e.strength is DependencyStrength.MAY and e.conditions for e in candidate_edges)
    assert all('host-value' not in e.evidence[0].rule for e in candidate_edges)
    assert any(f.kind == 'RESOURCE_CANDIDATES_REQUIRE_INTERFACE_RESOLUTION' for f in provider.frontiers)
    before = provider.payload()
    provider.add_operation(point, (value,), original, candidates=True)
    assert provider.payload() == before
    restored = BuildResourceProvider.from_payload(View(), before)
    restored.add_operation(point, (value,), original, candidates=True)
    assert restored.payload() == before


def test_candidates_are_opt_in_and_can_be_attached_after_demands():
    point, value, original = operation()
    provider = attach_build_resources(View(), operations=((point, (value,), original),))
    assert not any('.possible-' in edge.evidence[0].rule for edge in provider.edges)
    provider.add_candidates(point, (value,), original)
    conditions = {condition.name for edge in provider.edges for condition in edge.conditions}
    assert 'POSSIBLE_DEVICE_DISPATCH' in conditions
    assert 'POSSIBLE_EXTERNAL_FILE_EFFECT' not in conditions
    assert provider.payload()['actual_events'] == []
