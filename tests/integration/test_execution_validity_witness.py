"""A real owned OS short write feeds a bounded, explicitly declared IR case.

Only the counts are observed here. The fixture does not claim automatic
pipe-to-byte-region, canonical-operation, native-lifetime or coherence capture.
"""
from dataclasses import replace
import fcntl
import hashlib
import json
import os

from scar.ir.execution.query import ExecutionIndex
from scar.ir.execution.snapshot import external_artifact
from tests.fixtures import execution_produced_graphs
from tests.fixtures.execution_production_queries import native_production_query_fixture


def test_owned_nonblocking_pipe_short_write_stays_partial_in_validity_query(monkeypatch):
    reader, writer = os.pipe()
    try:
        capacity = fcntl.fcntl(writer, fcntl.F_GETPIPE_SZ)
        os.set_blocking(writer, False)
        payload = b'x' * (2 * capacity)
        written = os.write(writer, payload)
        assert 0 < written < len(payload)
        received = os.read(reader, written)
        assert received == payload[:written]
    finally:
        os.close(writer)
        os.close(reader)

    # Adapt the old fixture's deliberately tiny allocation *before* its normal
    # validating artifact serializer runs. Product validation is not patched.
    def capacity_artifact(graph):
        for identity, allocation in graph.allocations.items():
            graph.allocations[identity] = replace(allocation, nbytes=max(allocation.nbytes, len(payload)))
        return external_artifact(graph)
    with monkeypatch.context() as patch:
        patch.setattr(execution_produced_graphs, 'external_artifact', capacity_artifact)
        program, model, values, evidence, raw, details = native_production_query_fixture(
            requested=len(payload), written=written)
    index = ExecutionIndex(model, program, value_graphs=values, evidence_graphs=evidence, artifact_bytes=raw)
    result = index.validity(details['read'], budget=10000)
    known = result['known_fragment_coverage']
    assert known['status'] == 'INCOMPLETE'
    assert known['geometry'].covered_intervals == ((0, written),)
    assert known['geometry'].missing_intervals == ((written, len(payload)),)
    assert result['conditional_support']['status'] == 'MISSING'
    assert not result['source_runtime_verified']
    assert not result['runtime_visibility_verified']
    assert not result['transformation_authorized']
    print(json.dumps({'observed': {'os_operation': 'nonblocking pipe write', 'pipe_capacity': capacity,
        'requested_bytes': len(payload), 'returned_bytes': written, 'received_bytes': len(received),
        'received_sha256': hashlib.sha256(received).hexdigest()},
        'verified_model_guard': {'known_coverage': known['status'],
            'covered_intervals': known['geometry'].covered_intervals,
            'missing_intervals': known['geometry'].missing_intervals,
            'conditional_support': result['conditional_support']['status']},
        'limitation': 'Real counts were inserted into a declared canonical fixture; physical pipe/core/region correspondence is not automatically recovered.'}, sort_keys=True))
