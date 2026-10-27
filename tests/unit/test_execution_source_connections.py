"""Source scopes survive missing joins; declared bridges are not authority."""
from dataclasses import replace

import pytest

from scar.ir.execution.common import MissingEvidence, Unresolved
from scar.ir.execution.content import ObjectRef, VersionRef
from scar.ir.execution.ids import EvidenceInventoryID, SourceBridgeID, WriteAssociationID
from scar.ir.execution.inventory import InventoryResolver
from scar.ir.execution.query import ExecutionIndex
from scar.ir.execution.production import (
    EvidenceInventoryBinding, InventorySourceRef, RawRecordRef, SourceEndpointBridge,
    SourceEndpointRef, WriteAssociation,
)
from scar.ir.execution.snapshot import ExternalSnapshots, SnapshotError, external_artifact
from scar.ir.execution.validation import validate
from scar.ir.v2.evidence import EvidenceEndpoint, EvidenceNodeKind as N
from scar.ir.v2.values import ValueGraph
from tests.fixtures.execution_content_graphs import content_connection_fixture
from tests.fixtures.execution_inventory_sources import inventory_sources


def _fixture():
    program, model, values, evidence, details = content_connection_fixture()
    manifest, index, payloads = inventory_sources()
    resolution = InventoryResolver(ExternalSnapshots(artifact_bytes=payloads)).resolve(manifest, index)
    source = resolution.sources[0]
    fact = MissingEvidence('fixture declaration, not runtime authority')
    binding = EvidenceInventoryBinding(EvidenceInventoryID('source.fixture'), model.runs[0].id,
                                       manifest, index, fact)
    model = replace(model, source_inventories=(binding,))
    reference = InventorySourceRef(binding.id, source.key)
    endpoint = SourceEndpointRef(reference, EvidenceEndpoint(N.MATERIALIZATION,
                                next(iter(source.bundle.values.materializations))))
    return program, model, values, evidence, payloads, source, endpoint


def _report(program, model, values, evidence, payloads):
    return validate(model, program, value_graphs=values, evidence_graphs=evidence,
                    artifact_bytes=payloads)


def test_source_bundle_components_are_included_without_mutating_caller_catalogs():
    program, model, values, evidence, payloads, source, endpoint = _fixture()
    original_values, original_evidence = dict(values), dict(evidence)
    mat = source.bundle.values.materializations[endpoint.endpoint.reference]
    bridge = SourceEndpointBridge(SourceBridgeID('same.bundle'), endpoint,
        VersionRef(source.values_artifact, mat.value_version), model.source_inventories[0].source)
    model = replace(model, source_bridges=(bridge,))
    report = _report(program, model, values, evidence, payloads)
    assert report.valid, report.issues
    assert values == original_values and evidence == original_evidence
    assert source.values_artifact.sha256 not in values
    assert not report.source_runtime_verified and not report.transformation_authorized


def test_different_artifact_ids_are_explicit_conditional_bridge_not_false_conflict():
    program, model, values, evidence, payloads, source, endpoint = _fixture()
    target = model.denotations[0].identity.version
    bridge = SourceEndpointBridge(SourceBridgeID('cross.scope'), endpoint, target,
                                   model.source_inventories[0].source)
    model = replace(model, source_bridges=(bridge,))
    report = _report(program, model, values, evidence, payloads)
    assert report.valid, report.issues
    assert any(g.code == 'inventory_bridge_cross_scope_unverified' for g in report.gaps)


def test_bridge_target_must_exist_in_its_exact_original_scope():
    program, model, values, evidence, payloads, source, endpoint = _fixture()
    from scar.ir.v2.ids import ValueVersionID
    graph = source.bundle.values
    mat = graph.materializations[endpoint.endpoint.reference]
    missing = VersionRef(source.values_artifact, ValueVersionID(mat.value_version.logical_value, 99))
    bridge = SourceEndpointBridge(SourceBridgeID('absent.target'), endpoint, missing,
                                   model.source_inventories[0].source)
    report = _report(program, replace(model, source_bridges=(bridge,)), values, evidence, payloads)
    assert any(g.code == 'inventory_bridge_target' for g in report.issues)


@pytest.mark.parametrize('absent', (False, True))
def test_object_bridge_uses_the_exact_evidence_object_registry(absent):
    from scar.ir.v2.ids import ObjectID
    program, model, values, evidence, payloads, source, endpoint = _fixture()
    artifact = model.evidence_bindings[0].legacy.artifact
    target = ObjectRef(artifact, ObjectID('absent' if absent else 'content.object'))
    bridge = SourceEndpointBridge(SourceBridgeID('eeg.object'), endpoint, target,
                                   model.source_inventories[0].source)
    report = _report(program, replace(model, source_bridges=(bridge,)), values, evidence, payloads)
    if absent:
        assert any(g.code == 'inventory_bridge_target' for g in report.issues)
    else:
        assert report.valid, report.issues
        assert any(g.code == 'inventory_bridge_facet_unresolved' for g in report.gaps)


def test_bridge_cannot_contradict_two_original_versions_in_the_same_bundle():
    import json
    program, model, values, evidence, payloads, source, endpoint = _fixture()
    raw = source.raw_records[0].payload
    raw['outputs'].append({**raw['outputs'][0], 'object_id': 'second', 'storage_id': 'second'})
    manifest, index, payloads = inventory_sources(raw_streams={'two': (json.dumps(raw) + '\n').encode()})
    resolution = InventoryResolver(ExternalSnapshots(artifact_bytes=payloads)).resolve(manifest, index)
    source = resolution.sources[0]
    mats = tuple(source.bundle.values.materializations.values())
    assert len(mats) == 2 and mats[0].value_version != mats[1].value_version
    binding = replace(model.source_inventories[0], manifest=manifest, index=index)
    endpoint = SourceEndpointRef(InventorySourceRef(binding.id, source.key),
                                 EvidenceEndpoint(N.MATERIALIZATION, mats[0].id))
    bridge = SourceEndpointBridge(SourceBridgeID('same.scope.conflict'), endpoint,
        VersionRef(source.values_artifact, mats[1].value_version), binding.source)
    model = replace(model, source_inventories=(binding,), source_bridges=(bridge,))
    report = _report(program, model, values, evidence, payloads)
    assert any(g.code == 'inventory_bridge_conflict' for g in report.issues)


def test_index_rechecks_source_bytes_when_the_caller_changes_the_catalog():
    program, model, values, evidence, payloads, source, endpoint = _fixture()
    index = ExecutionIndex(model, program, value_graphs=values, evidence_graphs=evidence,
                            artifact_bytes=payloads)
    assert index.denotation(model.denotations[0].value)['kind'] == 'data'
    payloads[model.source_inventories[0].manifest.sha256] = b'changed'
    with pytest.raises(ValueError, match='external_snapshot'):
        index.denotation(model.denotations[0].value)


def test_duplicate_inventory_bindings_do_not_repeat_the_same_raw_projection(monkeypatch):
    from scar.trace import normalize_v2
    program, model, values, evidence, payloads, source, endpoint = _fixture()
    duplicate = replace(model.source_inventories[0], id=EvidenceInventoryID('duplicate'))
    model = replace(model, source_inventories=(*model.source_inventories, duplicate))
    original, calls = normalize_v2.normalize_bytes, []

    def counted(payload, **kwargs):
        calls.append(payload)
        return original(payload, **kwargs)

    monkeypatch.setattr(normalize_v2, 'normalize_bytes', counted)
    report = _report(program, model, values, evidence, payloads)
    assert report.valid, report.issues
    assert len(calls) == 1


@pytest.mark.parametrize('case,code', (
    ('inventory', 'inventory_binding'), ('stream', 'inventory_stream'),
    ('endpoint', 'inventory_endpoint'), ('raw-line', 'inventory_raw_line'),
    ('raw-hash', 'inventory_raw_digest'),
))
def test_bad_source_coordinates_are_issues(case, code):
    program, model, values, evidence, payloads, source, endpoint = _fixture()
    from scar.ir.v2.ids import MaterializationID
    if case == 'inventory':
        endpoint = replace(endpoint, source=replace(endpoint.source, inventory=EvidenceInventoryID('absent')))
    elif case == 'stream':
        endpoint = replace(endpoint, source=replace(endpoint.source, stream='absent'))
    elif case == 'endpoint':
        endpoint = replace(endpoint, endpoint=EvidenceEndpoint(N.MATERIALIZATION, MaterializationID('absent')))
    if case.startswith('raw-'):
        raw = source.raw_records[0]
        stage = RawRecordRef(endpoint.source, 999 if case == 'raw-line' else raw.line,
                             '0' * 64 if case == 'raw-hash' else raw.sha256)
        point = model.activations[0].entry
        unknown = Unresolved('deliberately unknown writer/placement', point)
        write = WriteAssociation(WriteAssociationID('raw.coordinate'), stage, unknown,
                                  unknown, unknown, (), model.source_inventories[0].source)
        model = replace(model, writes=(write,))
    else:
        bridge = SourceEndpointBridge(SourceBridgeID('bad.coordinate'), endpoint,
            model.denotations[0].identity.version, model.source_inventories[0].source)
        model = replace(model, source_bridges=(bridge,))
    report = _report(program, model, values, evidence, payloads)
    assert any(g.code == code for g in report.issues), report


def test_missing_inventory_bytes_stays_pending_instead_of_erasing_source():
    program, model, values, evidence, payloads, source, endpoint = _fixture()
    bridge = SourceEndpointBridge(SourceBridgeID('pending'), endpoint,
        model.denotations[0].identity.version, model.source_inventories[0].source)
    report = _report(program, replace(model, source_bridges=(bridge,)), values, evidence, {})
    assert report.valid
    assert any(g.code == 'inventory_source_pending' for g in report.gaps)


@pytest.mark.parametrize('missing_index', (False, True))
def test_supplied_empty_manifest_has_known_stream_membership_even_if_index_is_pending(missing_index):
    program, model, values, evidence, payloads, source, endpoint = _fixture()
    manifest, index, payloads = inventory_sources(raw_streams={})
    if missing_index:
        del payloads[index.sha256]
    binding = replace(model.source_inventories[0], manifest=manifest, index=index)
    unknown = Unresolved('no writer/placement known', model.activations[0].entry)
    stage = RawRecordRef(InventorySourceRef(binding.id, 'ghost'), 1, '0' * 64)
    write = WriteAssociation(WriteAssociationID('absent.stream'), stage, unknown, unknown,
                             unknown, (), binding.source)
    model = replace(model, source_inventories=(binding,), writes=(write,))
    report = _report(program, model, values, evidence, payloads)
    assert any(g.code == 'inventory_stream' for g in report.issues)


@pytest.mark.parametrize('bad', (None, bytearray(b'x'), 'x'))
def test_present_invalid_payload_is_not_missing(bad):
    program, model, values, evidence, payloads, source, endpoint = _fixture()
    payloads[model.source_inventories[0].manifest.sha256] = bad
    report = _report(program, model, values, evidence, payloads)
    assert any(g.code == 'external_graph_type' for g in report.issues)


def test_derived_component_does_not_hide_a_wrong_supplied_catalog():
    program, model, values, evidence, payloads, source, endpoint = _fixture()
    values[source.values_artifact.sha256] = None
    report = _report(program, model, values, evidence, payloads)
    assert any(g.code == 'external_graph_type' for g in report.issues)


def test_supported_raw_profile_cannot_be_relabelled_as_another_artifact_schema():
    import hashlib
    import json
    from scar.ir.execution.inventory import artifact_json
    from scar.ir.v2.schemas import canonical_json
    program, model, values, evidence, payloads, source, endpoint = _fixture()
    binding = model.source_inventories[0]

    def repack(artifact, document):
        wire = canonical_json(document).encode()
        result = replace(artifact, sha256=hashlib.sha256(wire).hexdigest(), size_bytes=len(wire))
        payloads[result.sha256] = wire
        return result

    manifest = json.loads(payloads[binding.manifest.sha256])
    manifest['streams'][0]['raw']['schema'] = 'scar.ir.v2.bundle'
    manifest_ref = repack(binding.manifest, manifest)
    index = json.loads(payloads[binding.index.sha256])
    index['manifest'] = artifact_json(manifest_ref)
    index_ref = repack(binding.index, index)
    model = replace(model, source_inventories=(replace(binding, manifest=manifest_ref, index=index_ref),))
    report = _report(program, model, values, evidence, payloads)
    assert any(g.code == 'inventory_invalid' and 'raw artifact schema' in g.message for g in report.issues)


def test_external_consumer_work_cannot_use_a_port_from_another_run():
    from scar.ir.execution.common import EvidencePoint
    from scar.ir.execution.coordinates import ExecutionRun
    from scar.ir.execution.ids import RunID
    from scar.ir.execution.work import DirectExecution, ExternalWorkSource
    program, model, values, evidence, details = content_connection_fixture(consumer='work')
    fact = MissingEvidence('explicit foreign run, not captured execution')
    foreign = ExecutionRun(RunID('foreign'), fact)
    point = EvidencePoint(foreign.id, None, fact)
    ticket = model.content_reads[0].consumer.read.ticket
    work = next(row for row in model.submissions if row.id == ticket)
    work = replace(work, origin=ExternalWorkSource(point, fact),
                   scheduling=DirectExecution(Unresolved('executor unknown', point), fact))
    model = replace(model, runs=(*model.runs, foreign),
                    submissions=tuple(work if row.id == ticket else row for row in model.submissions))
    report = _report(program, model, values, evidence, {})
    assert any(g.code == 'content_consumer_run' for g in report.issues), report


@pytest.mark.parametrize('pid', ('17', True, None))
def test_noninteger_raw_process_id_is_not_silently_coerced_to_provider_scope(pid):
    import json
    from scar.ir.program.providers import ProviderRunScope
    raw = {'kind': 'torch_dispatch', 'metadata': {'process_id': pid, 'thread_id': 1},
           'invocation_id': 1, 'inputs': [], 'outputs': []}
    manifest, index, payloads = inventory_sources(
        raw_streams={'pid': (json.dumps(raw) + '\n').encode()},
        scopes={'pid': ProviderRunScope('declared', 17, 'window', 'clock')})
    resolution = InventoryResolver(ExternalSnapshots(artifact_bytes=payloads)).resolve(manifest, index)
    assert any(g.code == 'inventory_process_scope_unresolved' for g in resolution.gaps)
    assert not resolution.source_runtime_verified


def test_snapshot_payload_and_derived_graph_are_detached_and_rechecked_per_resolver():
    program, model, values, evidence, payloads, source, endpoint = _fixture()
    snapshots = ExternalSnapshots(artifact_bytes=payloads)
    artifact = source.raw_artifact
    original = snapshots.payload(artifact)
    payloads[artifact.sha256] = b'changed'
    assert snapshots.payload(artifact) == original
    with pytest.raises(SnapshotError, match='bytes/hash/size'):
        ExternalSnapshots(artifact_bytes=payloads).payload(artifact)
    included = snapshots.include(source.values_artifact, source.bundle.values)
    source.bundle.values.versions.clear()
    assert included.versions
    assert snapshots.graph(source.values_artifact, ValueGraph) is included


@pytest.mark.parametrize('kind', ('values', 'evidence', 'semantic'))
def test_known_wrong_graph_schema_is_an_issue_before_a_catalog_miss(kind):
    from scar.ir.v2.evidence import EvidenceGraph
    from scar.ir.v2.semantic import SemanticGraph
    families = {'values': ValueGraph, 'evidence': EvidenceGraph, 'semantic': SemanticGraph}
    expected = families[kind]
    other = next(family for family in families.values() if family is not expected)
    artifact = external_artifact(other())
    with pytest.raises(SnapshotError) as error:
        ExternalSnapshots().graph(artifact, expected)
    assert error.value.code == 'external_snapshot'
