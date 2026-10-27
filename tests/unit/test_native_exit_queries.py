"""Logical ports retain completion paths and their actual state/Use occurrences."""
from dataclasses import fields, is_dataclass, replace

import pytest

from scar.ir.program import EntryPortRef, ExitKind, ExitPort, ExitPortRef, RegionID, UseID, ValueID
from scar.ir.program.queries import ProgramIndex
from scar.ir.program.validation import validate
from scar.ir.v2.ids import Identifier
from tests.fixtures.program_graphs import branch_state_program, shared_body_calls_program
from tests.fixtures.program_native_graphs import native_boundary_graph


def test_raise_port_retains_its_own_state_instead_of_the_normal_write():
    graph = branch_state_program()
    index = ProgramIndex(graph)
    normal = index.exit_port_uses(ExitPortRef(graph.root, "normal", 1))
    raised = index.exit_port_uses(ExitPortRef(graph.root, "failure", 1))
    assert tuple(site.use.value for site in normal) == (ValueID("buffer.updated"),)
    assert tuple(site.use.value for site in raised) == (ValueID("buffer.failure"),)
    assert raised[0].use.id == UseID("fail.buffer")
    # Every lookup returns the existing Use, including its role, not a new value.
    assert raised[0] == index.use_site(UseID("fail.buffer"))


def test_declared_exit_without_a_terminal_is_rejected_without_inventing_a_producer():
    graph = branch_state_program()
    root = graph.regions[0]
    unused = ExitPort("unused", ExitKind.NORMAL, root.exits[0].types)
    graph = replace(graph, regions=(replace(root, exits=(*root.exits, unused)),))
    with pytest.raises(ValueError, match="unbound_exit"):
        ProgramIndex(graph)
    # A native port declaration cannot bypass this existing core requirement.


def test_entry_lookup_does_not_accept_an_internal_phi_or_computed_value():
    graph = branch_state_program()
    index = ProgramIndex(graph)
    assert index.entry_port(EntryPortRef(graph.root, ValueID("input"))) is index.values[ValueID("input")]
    for value in (ValueID("buffer.normal"), ValueID("sum.value")):
        with pytest.raises(KeyError):
            index.entry_port(EntryPortRef(graph.root, value))


@pytest.mark.parametrize("port", [
    ExitPortRef(RegionID("other"), "normal", 0),
    ExitPortRef(RegionID("root"), "not-an-exit", 0),
    ExitPortRef(RegionID("root"), "failure", 3),
])
def test_exit_query_rejects_nonexistent_region_name_and_slot(port):
    with pytest.raises(KeyError):
        ProgramIndex(branch_state_program()).exit_port_uses(port)


def test_port_query_rechecks_record_types_after_out_of_band_tampering():
    graph = branch_state_program()
    index = ProgramIndex(graph)
    port = ExitPortRef(graph.root, "normal", 0)
    object.__setattr__(port, "index", False)
    with pytest.raises(TypeError):
        index.exit_port_uses(port)
    with pytest.raises(TypeError):
        index.entry_port(ValueID("input"))
    with pytest.raises(TypeError):
        index.exit_port_uses(EntryPortRef(graph.root, ValueID("input")))


def _replace_legacy_id(record, old, new):
    if isinstance(record, Identifier):
        return new if record == old else record
    if type(record) is tuple:
        return tuple(_replace_legacy_id(item, old, new) for item in record)
    if is_dataclass(record):
        return replace(record, **{field.name: _replace_legacy_id(getattr(record, field.name), old, new)
                                  for field in fields(record)})
    return record


@pytest.mark.parametrize("factory", [shared_body_calls_program, native_boundary_graph])
@pytest.mark.parametrize("id_type,name", [(ValueID, "caller.input"), (RegionID, "caller")])
def test_new_port_indexes_preserve_validator_valid_legacy_ids_in_unrelated_core(factory, id_type, name):
    class DerivedID(id_type):
        pass

    old, new = id_type(name), DerivedID(name)
    graph = _replace_legacy_id(factory(), old, new)
    assert validate(graph) == ()
    index = ProgramIndex(graph)
    if id_type is ValueID:
        assert index.values[new].id is new
        assert index.consumers(new)
        # The new strict declaration must not normalize a subtype to a base ID.
        with pytest.raises(TypeError):
            EntryPortRef(graph.root, new)
    else:
        assert index.entry_arguments(new)
        assert index.regions[new].id is new
    if graph.native_boundaries:
        boundary = graph.native_boundaries[-1]
        assert tuple(len(sites) for sites in index.native_output_uses(boundary.id)) == (2, 2, 1)
