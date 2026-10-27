"""A tiny query budget must stop before deriving return-port joins."""

from scar.ir.program.queries import ProgramIndex
from scar.ir.program.validation import require_valid
from tests.fixtures.program_call_return_graphs import call_return_program


class _ForbiddenReturnPortJoin:
    def __getitem__(self, key):
        raise AssertionError(f"query eagerly joined callee exit ports: {key!r}")

    def __iter__(self):
        raise AssertionError("query eagerly enumerated callee exit ports")

    def __len__(self):
        raise AssertionError("query eagerly counted callee exit ports")


def test_budget_one_stops_before_query_time_callee_return_join():
    graph, details = call_return_program(depth=2)
    require_valid(graph)
    index = ProgramIndex(graph)
    assert index._exit_ports

    # ProgramIndex preparation has completed. The bounded query may use the
    # prepared original call/formal inventory, but it must not derive every
    # callee exit-to-caller result association before its first query charge.
    index._exit_ports = _ForbiddenReturnPortJoin()
    report = index.copy_consumers(details["expected"], budget=1)

    assert report["budget"]["limit"] == 1
    assert report["budget"]["used"] <= 1
    assert report["budget"]["truncated"] is True
    assert report["inventory"]["known_inventory_complete"] is False
    assert report["inventory"]["frames_total"] is None
    assert report["inventory"]["consumers_total"] is None
    assert report["cursor"] is not None
