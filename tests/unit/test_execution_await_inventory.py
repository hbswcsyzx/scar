"""No captured execution may erase an original await acquisition obligation."""
from dataclasses import replace
from copy import deepcopy

import pytest

from scar.ir.execution.model import ExecutionModel
from scar.ir.execution.query import ExecutionIndex
from scar.ir.execution.snapshot import snapshot_for
from scar.ir.program.ids import ProtocolScopeID
from scar.ir.program.protocol_await_records import AwaitAcquisition
from scar.ir.program.protocols import (
    OperationSiteSubject, ProtocolClause, ProtocolOperation, ProtocolProfile,
    ProtocolScope, StaticGapReason, StaticProtocolGap,
)
from tests.fixtures.program_continuation_graphs import continuation_site_program


def _uncaptured_acquisition(*, rows):
    graph, details = continuation_site_program(kind='await')
    stage = details['lookup']
    owner = stage['operation'].id
    gap = StaticProtocolGap(StaticGapReason.NATIVE_APPLICABILITY_UNPROVEN)
    scope = ProtocolScope(ProtocolScopeID('uncaptured.acquisition'),
        ProtocolProfile.AWAIT_ACQUISITION_V1,
        OperationSiteSubject(graph.root, owner), gap)
    expected_value = details['root_inputs'][0]
    expected = next(value.origin for value in graph.values if value.id == expected_value)
    attached = tuple(ProtocolOperation(scope.id, ProtocolClause.AWAIT_ACQUISITION,
        owner, port.edge.successor_index, AwaitAcquisition(stage['receiver'], expected,
            port, stage['state_sites'], gap), gap) for port in stage['ports'])
    # This is a declared opaque primitive in a supplied graph, not evidence of
    # an actual native operation or recovered source. Labels carry no authority.
    graph = replace(graph, protocol_scopes=(scope,),
        protocol_operations=attached if rows else (), protocol_call_inputs=(),
        protocol_result_consumers=(), protocol_bindings=())
    return graph, scope, owner


@pytest.mark.parametrize('rows', (False, True))
@pytest.mark.parametrize('budget', (1, 65536))
def test_wholly_missing_capture_preserves_source_and_never_invents_a_drive(rows, budget):
    graph, scope, owner = _uncaptured_acquisition(rows=rows)
    model = ExecutionModel(snapshot_for(graph))
    index = ExecutionIndex(model, graph)
    original_receipt = deepcopy(index.report)
    report = index.await_body_links(scope.id, budget=budget)

    assert report['inventory']['source_count'] == 1
    assert report['job_count'] == 1
    job = report['jobs'][0]
    assert job['source_operation'] == owner
    assert job['source_occurrence_count'] == 0
    assert job['checked_source_occurrence_count'] == 0
    assert job['pending_source_occurrence_count'] == 0
    assert job['occurrences'] == ()
    assert 'await_advance_occurrence_missing' in job['gaps']
    assert report['status'] == 'PARTIAL'
    assert report['issues'] == ()
    assert report['source_runtime_verified'] is False
    assert report['runtime_identity_verified'] is False
    assert report['value_identity_verified'] is False
    assert report['transformation_authorized'] is False
    assert report['budget']['used'] <= budget
    # No captured source/advance means there is no derived path search to
    # truncate. One job projection fits even in budget=1; missing capture is
    # still PARTIAL and must not be misreported as budget exhaustion.
    assert report['budget']['truncated'] is False
    assert report['cursor'] is None
    assert not model.operations and not model.body_drive_executions
    assert index.report == original_receipt
