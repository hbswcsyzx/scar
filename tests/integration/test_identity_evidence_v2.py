from dataclasses import replace
from pathlib import Path

import pytest

from scar.analysis.execution_occurrences_v2 import (
    OccurrenceOriginStatus, query_execution_result_use,
)
from scar.analysis.regions_v2 import build_regions
from scar.ir.identity_execution_v2 import IdentityExecutionSnapshot
from scar.ir.v2 import EvidenceEndpoint, EvidenceNodeKind, EvidenceRelation
from scar.trace.identity_v2 import IdentityExecutionObserver


FIXTURE = Path(__file__).resolve().parents[2] / "testcases/reference_identity/program.py"


def load_fixture():
    code = compile(FIXTURE.read_text(), str(FIXTURE), "exec", dont_inherit=True, optimize=0)
    namespace = {"__name__": "external_reference_test", "__file__": str(FIXTURE)}
    exec(code, namespace)
    return namespace, code


class Box:
    pass


def test_real_calls_connect_exact_return_occurrences_to_existing_regions():
    namespace, code = load_fixture()
    left, right = Box(), Box()
    observer = IdentityExecutionObserver(namespace["relate"])
    try:
        assert observer.call(left, left) is True
        assert observer.call(right, right) is True
        first, second = observer.calls
        assert first.result_occurrence.handle == second.result_occurrence.handle
        assert first.result_occurrence.observation_id != second.result_occurrence.observation_id
        assert first.operands[0].handle != second.operands[0].handle
        for call in observer.calls:
            query = query_execution_result_use(observer.bundle, call.return_instance,
                call.result_occurrence.observation_id, scope=observer.snapshot().scope)
            assert query.status is OccurrenceOriginStatus.LOCATED_IN_EVIDENCE
            assert query.producers == (call.operator_instance,)
            assert tuple(operand.index for operand in call.operands) == (0, 1)
            assert all(operand.evidence.kind.value == "Inferred" for operand in call.operands)
        materialization = observer.bundle.values.materializations[first.result_occurrence.handle.materialization]
        assert materialization.producer is None
        regions = build_regions(observer.bundle, view="execution",
            roots=tuple(call.function_instance for call in observer.calls), max_depth=1)
        assert regions.assert_valid()["valid"]
        for call in observer.calls:
            assert any(call.operator_instance in region.instances
                       and call.return_instance in region.instances
                       for region in regions.graph.regions.values())
        assert observer.validate()["valid"] and observer.attest()
    finally:
        observer.close()


def test_cross_call_same_bool_return_rewire_cannot_pass_capture_attestation():
    namespace, code = load_fixture()
    item = Box()
    observer = IdentityExecutionObserver(namespace["relate"])
    try:
        observer.call(item, item)
        observer.call(item, item)
        first, second = observer.calls
        edges = observer.bundle.evidence.edges
        matches = [edge for edge in edges.values()
                   if edge.relation is EvidenceRelation.OBSERVED_READ
                   and edge.source.reference == second.return_instance
                   and edge.target.reference == second.result_occurrence.observation_id]
        assert len(matches) == 1
        edge = matches[0]
        edges[edge.edge_id] = replace(edge, target=EvidenceEndpoint(
            EvidenceNodeKind.VALUE_OBSERVATION, first.result_occurrence.observation_id))
        # A graph lookup reports what the forged graph says; truth must come
        # from independently held capture records, not an OBSERVED label.
        lookup = query_execution_result_use(observer.bundle, second.return_instance,
            first.result_occurrence.observation_id, scope=observer.snapshot().scope)
        assert lookup.producers == (first.operator_instance,)
        assert not observer.attest()
    finally:
        observer.close()


def test_bool_input_result_and_historical_roundtrip_keep_distinct_roles():
    namespace, code = load_fixture()
    observer = IdentityExecutionObserver(namespace["relate"])
    try:
        assert observer.call(True, True) is True
        call, = observer.calls
        assert call.operands[0].handle == call.result_occurrence.handle
        assert call.operands[0].entry_observation_id != call.result_occurrence.observation_id
        assert observer.validate()["valid"] and observer.attest()
        loaded = IdentityExecutionSnapshot.from_json(observer.snapshot().to_json())
        assert loaded.to_dict() == observer.snapshot().to_dict()
        assert not hasattr(loaded, "attest") and not hasattr(loaded, "identity_guard")
    finally:
        observer.close()
    assert not observer.attest()


def test_two_occurrences_of_the_same_parameter_survive_fused_load():
    namespace, code = load_fixture()
    observer = IdentityExecutionObserver(namespace["repeated_read"])
    try:
        assert observer.call(Box()) is True
        left, right = observer.calls[0].operands
        assert left.handle == right.handle and left.slot == right.slot
        assert left.read_instance != right.read_instance
        assert (left.load_offset, left.load_subindex) != (right.load_offset, right.load_subindex)
        assert observer.attest()
    finally:
        observer.close()


def test_tensor_foreign_write_changes_no_reference_identity_and_samples_no_contents(monkeypatch):
    import numpy as np
    import torch
    namespace, code = load_fixture()
    array = np.zeros(4, dtype=np.float32)
    tensor = torch.from_numpy(array)
    def forbidden(*args, **kwargs):
        raise AssertionError("ordinary reference capture touched Tensor contents")
    for name in ("cpu", "numpy", "tolist", "item", "clone", "data_ptr"):
        monkeypatch.setattr(torch.Tensor, name, forbidden)
    observer = IdentityExecutionObserver(namespace["relate"])
    try:
        observer.call(tensor, tensor)
        array[:] = 4
        observer.call(tensor, tensor)
        first, second = observer.calls
        assert first.operands[0].handle == second.operands[0].handle
        assert observer.attest()
        assert not observer.bundle.values.allocations and not observer.bundle.values.regions
        assert all(value.semantic_type == "python.object_reference"
                   for value in observer.bundle.values.logical_values.values())
    finally:
        observer.close()


def test_external_measurement_has_real_queries_and_no_rewrite_claim():
    from scripts.measure_identity_evidence_v2 import identity_evidence_report
    report = identity_evidence_report(FIXTURE, "relate", warmup=0, repetitions=1, include_torch=False)
    assert len(report["cases"]) == 4
    assert len(report["evidence"]["return_queries"]) == 4
    assert report["evidence"]["active_capture_attested"]
    assert report["decision"] == {"reuse": "NOT_YET_SUPPORTED", "selection": "NOT_SELECTED", "applied": False}
