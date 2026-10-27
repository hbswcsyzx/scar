"""Exact per-query declaration snapshots, without URI or provider execution."""
from dataclasses import replace

import pytest

from scar.ir.execution.snapshot import ExternalSnapshots, SnapshotError, external_artifact
from scar.ir.v2.contracts import ContractDefinition
from scar.ir.v2.evidence import EvidenceGraph
from scar.ir.v2.ids import ContractID, StorageAllocationID
from scar.ir.v2.semantic import SemanticGraph
from scar.ir.v2.values import StorageAllocation, ValueGraph


FAMILIES = (ValueGraph, EvidenceGraph, SemanticGraph)
CATALOGS = {ValueGraph: "value_graphs", EvidenceGraph: "evidence_graphs", SemanticGraph: "semantic_graphs"}


def _mutate(graph, suffix):
    if type(graph) is ValueGraph:
        graph.add_allocation(StorageAllocation(StorageAllocationID(suffix), "cpu", 4))
    elif type(graph) is EvidenceGraph:
        graph.add_control_event(suffix)
    else:
        graph.add_contract(ContractDefinition(ContractID(suffix), suffix))


@pytest.mark.parametrize("family", FAMILIES)
def test_three_families_are_exact_detached_snapshots_and_next_query_rechecks_mutation(family):
    graph = family()
    _mutate(graph, "initial")
    artifact = external_artifact(graph)
    original = graph.to_dict()
    catalog = {artifact.sha256: graph}
    snapshots = ExternalSnapshots(**{CATALOGS[family]: catalog})
    snapshot = snapshots.graph(artifact, family)
    assert type(snapshot) is family and snapshot is not graph
    assert snapshot.to_dict() == original
    _mutate(snapshot, "returned-copy-change")
    assert graph.to_dict() == original
    assert snapshots.graph(artifact, family) is snapshot
    _mutate(graph, "caller-change")
    with pytest.raises(SnapshotError) as failure:
        ExternalSnapshots(**{CATALOGS[family]: catalog}).graph(artifact, family)
    assert failure.value.code == "external_snapshot"


@pytest.mark.parametrize("family", FAMILIES)
def test_missing_key_is_none_but_present_none_and_wrong_family_are_type_errors(family):
    artifact = external_artifact(family())
    assert ExternalSnapshots().graph(artifact, family) is None
    wrong = next(other for other in FAMILIES if other is not family)()
    for supplied in (None, wrong):
        with pytest.raises(SnapshotError) as failure:
            ExternalSnapshots(**{CATALOGS[family]: {artifact.sha256: supplied}}).graph(artifact, family)
        assert failure.value.code == "external_graph_type"


@pytest.mark.parametrize("change", ["hash", "schema", "size"])
def test_supplied_identity_mismatch_has_specific_code(change):
    graph = ValueGraph()
    artifact = external_artifact(graph)
    artifact = replace(artifact, **{"hash": {"sha256": "f" * 64},
                                    "schema": {"schema": "other-schema"},
                                    "size": {"size_bytes": artifact.size_bytes + 1}}[change])
    with pytest.raises(SnapshotError) as failure:
        ExternalSnapshots(value_graphs={artifact.sha256: graph}).graph(artifact, ValueGraph)
    assert failure.value.code == "external_snapshot"


@pytest.mark.parametrize("family,field", [(ValueGraph, "allocations"),
                                          (EvidenceGraph, "instances"),
                                          (SemanticGraph, "contracts")])
def test_malformed_supplied_graph_cannot_escape_as_attribute_error_or_missing(family, field):
    graph = family()
    artifact = external_artifact(graph)
    setattr(graph, field, [])
    with pytest.raises(SnapshotError) as failure:
        ExternalSnapshots(**{CATALOGS[family]: {artifact.sha256: graph}}).graph(artifact, family)
    assert failure.value.code == "external_graph_invalid"


@pytest.mark.parametrize("catalog_name", tuple(CATALOGS.values()))
def test_catalog_shape_and_all_keys_are_exact(catalog_name):
    class Text(str):
        pass
    class Mapping(dict):
        pass
    for catalog in ([], Mapping(), {1: ValueGraph()}, {Text("a"): ValueGraph()}):
        with pytest.raises(SnapshotError) as failure:
            ExternalSnapshots(**{catalog_name: catalog})
        assert failure.value.code == "catalog_type"


def test_only_closed_graph_classes_are_accepted_not_provider_selected_types():
    artifact = external_artifact(ValueGraph())
    class Derived(ValueGraph):
        pass
    for kind in (Derived, object, "ValueGraph", [], None):
        with pytest.raises(SnapshotError) as failure:
            ExternalSnapshots().graph(artifact, kind)
        assert failure.value.code == "external_graph_type"
    with pytest.raises(TypeError):
        external_artifact(Derived())


def test_hash_once_per_query_uri_not_identity_and_no_uri_is_opened(monkeypatch):
    import scar.ir.execution.snapshot as module
    graph = SemanticGraph()
    artifact = external_artifact(graph, uri="file:///must-not-open")
    original, calls = module.external_bytes, []

    def counted(value):
        calls.append(value)
        return original(value)

    monkeypatch.setattr(module, "external_bytes", counted)
    monkeypatch.setattr("builtins.open", lambda *args, **kwargs: pytest.fail("snapshot must not open URIs"))
    snapshots = ExternalSnapshots(semantic_graphs={artifact.sha256: graph})
    first = snapshots.graph(artifact, SemanticGraph)
    assert snapshots.graph(replace(artifact, uri="https://must-not-fetch"), SemanticGraph) is first
    assert calls == [graph]


def test_geometry_uses_bytes_checked_before_caller_changes_after_serialization(monkeypatch):
    import scar.ir.execution.snapshot as module
    graph = ValueGraph()
    allocation = StorageAllocationID("allocation")
    graph.add_allocation(StorageAllocation(allocation, "cpu", 8))
    artifact = external_artifact(graph)
    original = module.external_bytes

    def serialize_then_mutate(value):
        wire = original(value)
        value.allocations[allocation].nbytes = 16
        return wire

    monkeypatch.setattr(module, "external_bytes", serialize_then_mutate)
    snapshot = ExternalSnapshots(value_graphs={artifact.sha256: graph}).graph(artifact, ValueGraph)
    assert snapshot.allocations[allocation].nbytes == 8
    assert graph.allocations[allocation].nbytes == 16


def test_artifact_nested_private_mutation_is_not_accepted_as_valid_identity():
    artifact = external_artifact(ValueGraph())
    object.__setattr__(artifact, "size_bytes", True)
    with pytest.raises(SnapshotError) as failure:
        ExternalSnapshots().graph(artifact, ValueGraph)
    assert failure.value.code == "external_snapshot"
