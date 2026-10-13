from dataclasses import replace

import pytest

from scar.analysis.execution_occurrences_v2 import (
    OccurrenceOriginStatus, query_execution_result_use,
)
from scar.ir.v2 import (
    EvidenceClaim, EvidenceEdge, EvidenceEndpoint, EvidenceGraph, EvidenceKind,
    EvidenceNodeKind as N, EvidenceRelation as R, IRBundle, LogicalValue,
    LogicalValueID, OperationDefinition, OperationDefinitionID, OperationInstance,
    OperationInstanceID, OperationKind, SemanticGraph, ValueGraph,
    ValueObservation, ValueVersion, ValueVersionID,
)


def fixture():
    sg, eeg, values = SemanticGraph(), EvidenceGraph(), ValueGraph()
    definition = OperationDefinitionID("fixture-operation")
    sg.add_definition(OperationDefinition(definition, OperationKind.FUNCTION, "fixture"))
    version = ValueVersionID(LogicalValueID("shared-reference"), 1)
    values.add_logical_value(LogicalValue(version.logical_value, "python.object_reference"))
    values.add_version(ValueVersion(version))
    pairs = []
    for index in range(2):
        producer, consumer = (OperationInstanceID(f"{role}-{index}") for role in ("producer", "consumer"))
        for instance in (producer, consumer):
            eeg.add_instance(OperationInstance(instance, definition, 1, 1, control_scope="capture"))
        observation = f"result-{index}"
        eeg.add_observation(ValueObservation(observation, version, operation=producer))
        for relation, instance, role in ((R.PRODUCES, producer, "producer"),
                                         (R.OBSERVED_READ, consumer, "read")):
            eeg.add_edge(EvidenceEdge(f"{role}-{index}", relation,
                EvidenceEndpoint(N.OPERATION_INSTANCE, instance),
                EvidenceEndpoint(N.VALUE_OBSERVATION, observation),
                EvidenceClaim(EvidenceKind.INFERRED, (f"runtime-{index}",), scope="capture")))
        pairs.append((producer, consumer, observation))
    bundle = IRBundle(sg, eeg, values)
    bundle.assert_valid()
    return bundle, pairs


def test_shared_value_keeps_each_result_occurrence_separate():
    bundle, pairs = fixture()
    for producer, consumer, observation in pairs:
        result = query_execution_result_use(bundle, consumer, observation, scope="capture")
        assert result.status is OccurrenceOriginStatus.LOCATED_IN_EVIDENCE
        assert result.producers == (producer,)
        assert not result.gaps


def test_missing_specific_read_does_not_fall_back_to_other_consumer_same_value():
    bundle, pairs = fixture()
    result = query_execution_result_use(bundle, pairs[1][1], pairs[0][2], scope="capture")
    assert result.status is OccurrenceOriginStatus.UNRESOLVED
    assert result.read_edges == ()


def test_logical_value_producer_is_not_result_occurrence_producer():
    bundle, pairs = fixture()
    edge = bundle.evidence.edges["producer-0"]
    version = bundle.evidence.observations[pairs[0][2]].version
    bundle.evidence.edges[edge.edge_id] = replace(edge, target=EvidenceEndpoint(N.VALUE_VERSION, version))
    result = query_execution_result_use(bundle, pairs[0][1], pairs[0][2], scope="capture")
    assert result.status is OccurrenceOriginStatus.UNRESOLVED
    assert not result.producers


def test_multiple_recorded_producers_are_ambiguous_even_for_one_shared_value():
    bundle, pairs = fixture()
    original = bundle.evidence.edges["producer-0"]
    bundle.evidence.add_edge(replace(original, edge_id="extra-producer",
        source=EvidenceEndpoint(N.OPERATION_INSTANCE, pairs[1][0])))
    result = query_execution_result_use(bundle, pairs[0][1], pairs[0][2], scope="capture")
    assert result.status is OccurrenceOriginStatus.AMBIGUOUS
    assert set(result.producers) == {pairs[0][0], pairs[1][0]}


@pytest.mark.parametrize("edge_id", ["read-0", "producer-0"])
@pytest.mark.parametrize("claim", [
    EvidenceClaim(EvidenceKind.INFERRED, ("event",), scope="other"),
    EvidenceClaim(EvidenceKind.UNKNOWN, ("event",), scope="capture"),
    EvidenceClaim(EvidenceKind.DECLARED, ("assertion",), scope="capture"),
    EvidenceClaim(EvidenceKind.INFERRED, (), scope="capture"),
])
def test_query_requires_scoped_runtime_evidence(claim, edge_id):
    bundle, pairs = fixture()
    edge = bundle.evidence.edges[edge_id]
    bundle.evidence.edges[edge.edge_id] = replace(edge, evidence=claim)
    result = query_execution_result_use(bundle, pairs[0][1], pairs[0][2], scope="capture")
    assert result.status is OccurrenceOriginStatus.UNRESOLVED


@pytest.mark.parametrize("owner", [None, OperationInstanceID("producer-1")])
def test_observation_owner_must_match_the_recorded_producer(owner):
    bundle, pairs = fixture()
    bundle.evidence.observations[pairs[0][2]].operation = owner
    result = query_execution_result_use(bundle, pairs[0][1], pairs[0][2], scope="capture")
    assert result.status is OccurrenceOriginStatus.UNRESOLVED


@pytest.mark.parametrize("edge_id", ["read-0", "producer-0"])
def test_duplicate_edges_preserve_ambiguity_and_a_specific_gap(edge_id):
    bundle, pairs = fixture()
    bundle.evidence.add_edge(replace(bundle.evidence.edges[edge_id], edge_id="duplicate"))
    result = query_execution_result_use(bundle, pairs[0][1], pairs[0][2], scope="capture")
    assert result.status is OccurrenceOriginStatus.AMBIGUOUS
    assert result.gaps


def test_query_does_not_certify_arbitrary_eeg_records_or_transform_legality():
    bundle, pairs = fixture()
    result = query_execution_result_use(bundle, pairs[0][1], pairs[0][2], scope="capture")
    # This fixture is manually declared evidence. Location is a graph lookup,
    # not a collector attestation, purity certificate, or consumer closure.
    assert result.status.value == "LOCATED_IN_EVIDENCE"
    assert not hasattr(result, "proven")
    assert not hasattr(result, "guard")


def test_missing_query_endpoints_rejected():
    bundle, pairs = fixture()
    with pytest.raises(ValueError, match="absent"):
        query_execution_result_use(bundle, pairs[0][1], "missing", scope="capture")
