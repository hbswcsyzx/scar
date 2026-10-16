"""Provider result origins include canonical edge projections, not all phis."""
from dataclasses import replace

import pytest

from scar.ir.program import dumps
from scar.ir.program.ids import OperationID, UseID, ValueID
from scar.ir.program.providers import (
    ProviderBinding, ProviderElement, ProviderElementKind as K, ProviderPathIndex,
    ProviderPathKey, ProviderRegion, ProviderRegionRelation,
)
from scar.ir.program.validation import validate
from tests.fixtures.program_control_graphs import shared_pending_graph
from tests.fixtures.program_provider_graphs import _envelope
from tests.unit.test_program_completions_adversarial import _invoke_graph, _forward_slot


def _attach(graph, operation, external_key, value, kind, path):
    envelope = _envelope("completion-provenance")
    return replace(graph, provider_envelopes=(envelope,), provider_regions=(
        ProviderRegion(envelope.id, "body", graph.root,
                       ProviderRegionRelation.DEFINES_REPRESENTATION),),
        provider_bindings=(ProviderBinding(envelope.id, graph.root,
            ProviderElement(K.OPERATION, external_key), operation),
            ProviderBinding(envelope.id, graph.root,
                ProviderElement(kind, external_key, path), value)))


@pytest.mark.parametrize("suffix,kind", [
    ("normal.value", K.REFERENCE_VALUE), ("raise.value", K.REFERENCE_VALUE),
    ("normal.world", K.STATE_VALUE), ("raise.world", K.STATE_VALUE),
])
def test_direct_completion_projection_uses_the_actual_invoke_producer(suffix, kind):
    core = _invoke_graph()
    path = (ProviderPathKey(suffix.split(".")[0]), ProviderPathIndex(0))
    good = _attach(core, OperationID("main.invoke"), "call", ValueID("main." + suffix), kind, path)
    assert validate(good) == ()
    bad = _attach(core, OperationID("main.normal.done"), "other", ValueID("main." + suffix), kind, path)
    assert any(issue.code == "provider_binding_owner" for issue in validate(bad))
    with pytest.raises(ValueError):
        dumps(bad)


def test_direct_completion_projection_cannot_omit_result_path():
    graph = _attach(_invoke_graph(), OperationID("main.invoke"), "call",
                    ValueID("main.normal.value"), K.REFERENCE_VALUE, ())
    assert any(issue.code == "provider_result_projection" for issue in validate(graph))


def test_forwarded_completion_argument_does_not_acquire_a_new_producer():
    from scar.ir.program import ExitKind
    core = _forward_slot(_invoke_graph(), ExitKind.NORMAL, 0)
    graph = _attach(core, OperationID("main.normal.done"), "formal-coordinate",
                    ValueID("main.normal.value"), K.REFERENCE_VALUE, ())
    assert validate(graph) == ()


def test_pending_payload_projection_requires_its_dispatch_source():
    core = shared_pending_graph()
    from scar.ir.program import ReferenceValue
    from scar.ir.program.control import PendingPayload
    from scar.ir.program.model import BlockArgument
    edge = next(edge for operation in core.operations if operation.terminator
                for edge in operation.terminator.successors
                if any(isinstance(argument, PendingPayload) for argument in edge.arguments))
    target = next(block for region in core.regions for block in region.blocks if block.id == edge.block)
    projected = next(value for value in core.values if isinstance(value, ReferenceValue)
                     and isinstance(value.origin, BlockArgument) and value.id in target.arguments)
    producer = next(operation for operation in core.operations if operation.terminator
                    and any(item is edge for item in operation.terminator.successors))
    graph = _attach(core, producer.id, "dispatch", projected.id, K.REFERENCE_VALUE,
                    (ProviderPathKey("payload"),))
    assert validate(graph) == ()
    wrong = _attach(core, core.operations[0].id, "other", projected.id, K.REFERENCE_VALUE,
                    (ProviderPathKey("payload"),))
    assert any(issue.code == "provider_binding_owner" for issue in validate(wrong))
