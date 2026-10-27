"""A missing original input alternative must remain in composition's denominator."""
from dataclasses import replace

from scar.ir.execution.validity_budget import ValidityBudget
from scar.ir.program.ids import UseID
from scar.ir.program.protocol_connection_flow import ConnectionContext
from scar.ir.program.queries import ProgramIndex
from scar.ir.program.validation import require_valid
from tests.fixtures.program_call_composition_graphs import duplicate_argument_composition_program


class _UseIDSubclass(UseID):
    """A typed edge-use ID accepted by the core's isinstance port contract.

    Keep equality/hash compatible with the canonical base ID so the only
    distinction exercised here is the input-origin walk's exact-kind branch.
    """

    def __eq__(self, other):
        return isinstance(other, UseID) and self.value == other.value

    def __hash__(self):
        return hash(UseID(self.value))


def _graph_with_missing_origin_branch():
    graph, details = duplicate_argument_composition_program(duplicate=False)
    selected_branch = details["guards"][1].operation
    branch = next(operation for operation in graph.operations if operation.id == selected_branch)
    edges = list(branch.terminator.successors)
    second = edges[1]
    missing_origin_use = second.arguments[0]
    edges[1] = replace(second, arguments=(
        _UseIDSubclass(missing_origin_use.value), *second.arguments[1:]))
    changed_branch = replace(branch, terminator=replace(
        branch.terminator, successors=tuple(edges)))
    graph = replace(graph, operations=tuple(
        changed_branch if operation.id == branch.id else operation
        for operation in graph.operations))
    return graph, details


def test_uninventoried_valid_incoming_origin_prevents_single_recipe_success():
    graph, details = _graph_with_missing_origin_branch()

    # Core validation accepts this typed edge port. The original reverse
    # inventory currently recognizes only exact UseID values and therefore
    # omits the second predecessor recipe while reporting its gap.
    require_valid(graph)
    index = ProgramIndex(graph)
    context = ConnectionContext(graph, index=index, budget=ValidityBudget(50000))
    origins = context.origins(details["actual"])
    report = context.bind(details["expected"], details["actual"])

    assert any(route["match"] is True for route in report["routes"]), report
    assert any(gap.get("code") == "cfg_source_kind_unresolved"
               for gap in report["gaps"] if type(gap) is dict), report
    assert report["source_inventory_complete"] is False, report
    assert any(gap.get("code") == "cfg_source_kind_unresolved"
               for gap in report["missing_origin_routes"]), report
    assert origins["source_inventory_complete"] is False, origins
    assert origins["missing_origin_routes"], origins
    known_recipe_context = context.recipe_context(origins["recipes"][0])
    assert known_recipe_context["match"] is None, known_recipe_context
    assert report["match"] is None, report


def test_availability_keeps_a_missing_origin_route_unresolved():
    graph, details = _graph_with_missing_origin_branch()
    require_valid(graph)
    index = ProgramIndex(graph)
    context = ConnectionContext(graph, index=index, budget=ValidityBudget(50000))

    report = context.available(details["expected"], details["actual"].operation)

    assert report["match"] is None, report
    assert any(gap.get("code") == "cfg_source_kind_unresolved"
               for gap in report["gaps"] if type(gap) is dict), report
