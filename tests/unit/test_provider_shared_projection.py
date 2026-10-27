"""Provider producer inference counts CFG predecessors, not tuple iteration order."""
from dataclasses import replace

from scar.ir.program.control import PendingDispatchTerminator, PendingPayload
from scar.ir.program.ids import RegionID, ValueID
from scar.ir.program.queries import ProgramIndex
from scar.ir.program.validation import validate

from tests.fixtures.program_provider_pending_graphs import shared_pending_projection_graph


def _provider_judgment(graph):
    return tuple((issue.code, issue.path, issue.message)
                 for issue in validate(graph) if issue.code.startswith("provider_"))


def test_distinct_pending_payload_projections_to_one_shim_ignore_operation_tuple_order():
    graph = shared_pending_projection_graph()
    assert validate(graph) == ()

    blocks = {block.id: block for region in graph.regions for block in region.blocks}
    exit_value = next(value for value in graph.values if value.id == ValueID("provider.pending.exit_value"))
    exit_block = blocks[exit_value.origin.block]
    dispatchers = tuple(operation for operation in graph.operations
                        if isinstance(operation.terminator, PendingDispatchTerminator))
    assert len(dispatchers) == 2
    assert {edge.block for operation in dispatchers for edge in operation.terminator.successors} == {
        exit_block.id,
    }

    pending_inputs = []
    for operation in dispatchers:
        pending_use = next(use for use in operation.uses
                           if use.id == operation.terminator.pending)
        pending_inputs.append(pending_use.value)
        edge = operation.terminator.successors[0]
        assert len(edge.arguments) == len(exit_block.arguments) == 2
        assert type(edge.arguments[0]) is PendingPayload
        assert edge.arguments[1] in {use.id for use in operation.uses}
    assert len(set(pending_inputs)) == 2

    reordered = replace(graph, operations=tuple(reversed(graph.operations)))
    assert validate(reordered) == ()
    assert _provider_judgment(graph) == _provider_judgment(reordered) == ()

    # The public query returns only the same declaration and existing ValueID;
    # reversing record order cannot change the inferred provenance.
    original_sources = ProgramIndex(graph).provider_sources(exit_value.id)
    reordered_sources = ProgramIndex(reordered).provider_sources(exit_value.id)
    assert original_sources == reordered_sources == (
        next(row for row in graph.provider_bindings if row.target == exit_value.id),
    )
