"""Automatic environment ports and state dependencies from ordinary source.

No test imports or executes the application module.  Runtime object identities,
cell contents and whole-program coverage are deliberately not inferred here.
"""
import ast
from dataclasses import replace

import pytest

from scar.analysis.environment_lowering import StructuredEnvironmentBuilder, captured_cell_slot
from scar.analysis.program_lowering import SourceProgram, lower_source, prepare_source
from scar.ir.program.environments import EnvironmentRole
from scar.ir.program.functions import BodyLoweringProfile
from scar.ir.program.model import (
    Behavior, BlockArgument, LocalBindingValue, ReferenceValue, StateVersionValue,
    TerminatorKind,
)
from scar.ir.program.state_addresses import (
    AddressCoverage, CellContent, NamespaceKey, ReferenceOwner,
)
from scar.ir.program.structured import PythonProtocolKind
from scar.ir.program.validation import require_valid


def _lower(tmp_path, text, name):
    path = tmp_path / "application.py"
    path.write_text(text)
    context = prepare_source(path)
    nodes = [node for node in ast.walk(context.tree)
             if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name]
    assert len(nodes) == 1
    node = nodes[0]
    matches = [atom.reference for atom in context.semantic.source_atoms.values()
               if atom.kind == type(node).__name__
               and (atom.reference.start_line, atom.reference.end_line,
                    atom.reference.start_column, atom.reference.end_column)
               == (node.lineno, node.end_lineno, node.col_offset, node.end_col_offset)]
    assert len(matches) == 1
    result = StructuredEnvironmentBuilder(context, name, source=matches[0]).run()
    return result, context


def _indexes(body):
    graph = body.graph
    assert graph is not None
    require_valid(graph)
    return ({operation.id: operation for operation in graph.operations},
            {value.id: value for value in graph.values},
            {protocol.operation: protocol.kind for protocol in body.structured.protocols})


def _protocol_operations(body, kind):
    operations = {operation.id: operation for operation in body.graph.operations}
    return [operations[protocol.operation] for protocol in body.structured.protocols if protocol.kind is kind]


def _reference_uses(operation, values):
    return [use for use in operation.uses if isinstance(values[use.value], ReferenceValue)]


def test_environment_entry_is_complete_and_free_cells_have_their_own_interface_slots(tmp_path):
    body, context = _lower(tmp_path,
        "must_never_execute_source()\n"
        "def outer(z, a):\n"
        "    def inner(x):\n"
        "        return z + a + x\n"
        "    return inner\n", "inner")
    _, values, _ = _indexes(body)
    environment, = body.graph.environments
    layout, = body.graph.function_entries
    assert tuple(member.role for member in environment.members[:5]) == (
        EnvironmentRole.FUNCTION_OBJECT, EnvironmentRole.GLOBALS_NAMESPACE,
        EnvironmentRole.BUILTINS_NAMESPACE, EnvironmentRole.DEFAULTS,
        EnvironmentRole.KEYWORD_DEFAULTS)
    cells = environment.members[5:]
    assert tuple(member.cell_slot for member in cells) == tuple(
        captured_cell_slot(body.interface.definition, name) for name in ("a", "z"))
    assert tuple(member.cell_position for member in cells) == (0, 1)
    outer_slots = {slot.slot_id for slot in context.semantic.slots.values() if slot.name in {"a", "z"}}
    assert not outer_slots.intersection(member.cell_slot for member in cells)
    region, = body.graph.regions
    entry = next(block for block in region.blocks if block.id == region.entry)
    assert entry.arguments == tuple(member.reference for member in environment.members) + (
        body.interface.parameters[0].value, body.interface.world)
    assert layout.parameters == body.interface.parameters
    for index, identity in enumerate(entry.arguments):
        assert values[identity].origin == BlockArgument(entry.id, index)
    frame_enter, = _protocol_operations(body, PythonProtocolKind.FRAME_ENTER)
    assert tuple(use.value for use in _reference_uses(frame_enter, values)) == entry.arguments[:-1]
    assert all(member.locations == (values[body.interface.world].location,) for member in environment.members)


def test_free_cell_reads_keep_owner_world_and_exception_paths(tmp_path):
    body, _ = _lower(tmp_path,
        "def outer(shared):\n"
        "    def inner(mutate):\n"
        "        return shared + mutate() + shared\n"
        "    return inner\n", "inner")
    _, values, _ = _indexes(body)
    reads = _protocol_operations(body, PythonProtocolKind.READ_FREE_CELL)
    assert len(reads) == 2
    owner = body.graph.environments[0].members[5].reference
    addresses = {row.site.operation: row for row in body.graph.state_address_refinements}
    before_values = []
    for operation in reads:
        assert operation.uses[0].value == owner
        assert operation.terminator.kind is TerminatorKind.INVOKE
        assert {signature.kind.value for signature in operation.completions} == {"NORMAL", "RAISE"}
        assert not operation.effects_complete
        address = addresses[operation.id]
        assert address.coverage is AddressCoverage.PARTIAL
        assert address.site.state_use == operation.uses[-1].id
        effect, = address.effects
        assert effect.owner == ReferenceOwner(operation.uses[0].id)
        assert effect.path == (CellContent(),)
        assert isinstance(values[operation.uses[-1].value], StateVersionValue)
        before_values.append(operation.uses[-1].value)
    assert before_values[0] != before_values[1]
    assert not _protocol_operations(body, PythonProtocolKind.LOOKUP_GLOBAL)


def test_nonlocal_write_uses_the_captured_cell_instead_of_a_local_token(tmp_path):
    body, _ = _lower(tmp_path,
        "def outer(shared):\n"
        "    def inner(value):\n"
        "        nonlocal shared\n"
        "        shared = value\n"
        "        return shared\n"
        "    return inner\n", "inner")
    _, values, _ = _indexes(body)
    store, = _protocol_operations(body, PythonProtocolKind.STORE_CELL)
    read, = _protocol_operations(body, PythonProtocolKind.READ_FREE_CELL)
    cell = body.graph.environments[0].members[5].reference
    assert store.uses[0].value == read.uses[0].value == cell
    assert store.uses[1].value != cell
    assert not _protocol_operations(body, PythonProtocolKind.STORE_GLOBAL)
    assert len(next(signature for signature in store.completions if signature.kind.value == "NORMAL").types) == 1
    assert all(not isinstance(value, LocalBindingValue) or value.slot != captured_cell_slot(
        body.interface.definition, "shared") for value in values.values())
    assert all(link.source.start_line != 3 for link in body.metadata.operation_links)


def test_global_lookup_uses_saved_builtins_and_explicit_name_key(tmp_path):
    body, _ = _lower(tmp_path,
        "G = 1\n"
        "def f(x):\n"
        "    global G\n"
        "    G = x\n"
        "    return len(G)\n", "f")
    _, values, _ = _indexes(body)
    environment = body.graph.environments[0]
    globals_ref, builtins_ref = environment.members[1].reference, environment.members[2].reference
    lookups = _protocol_operations(body, PythonProtocolKind.LOOKUP_GLOBAL)
    assert len(lookups) == 2
    assert {values[operation.uses[2].value].origin.value for operation in lookups} == {"len", "G"}
    rows = {row.site.operation: row for row in body.graph.state_address_refinements}
    for operation in lookups:
        assert tuple(use.value for use in operation.uses[:2]) == (globals_ref, builtins_ref)
        row = rows[operation.id]
        assert row.coverage is AddressCoverage.PARTIAL
        assert tuple(effect.owner for effect in row.effects) == tuple(
            ReferenceOwner(operation.uses[index].id) for index in (0, 1))
        assert all(effect.path == (NamespaceKey(operation.uses[2].id),) for effect in row.effects)
    store, = _protocol_operations(body, PythonProtocolKind.STORE_GLOBAL)
    assert store.uses[0].value == globals_ref
    assert values[store.uses[1].value].origin.value == "G"
    assert not _protocol_operations(body, PythonProtocolKind.MAKE_CELL)


def test_own_formal_cell_is_created_per_invocation_and_not_a_captured_port(tmp_path):
    body, _ = _lower(tmp_path,
        "def outer(x):\n"
        "    x = x + 1\n"
        "    return x\n"
        "    def inner():\n"
        "        return x\n", "outer")
    _, values, _ = _indexes(body)
    assert len(body.graph.environments[0].members) == 5
    make, = _protocol_operations(body, PythonProtocolKind.MAKE_CELL)
    assert Behavior.MEMORY in make.behaviors
    assert make.uses[0].value == body.interface.parameters[0].value
    reads = _protocol_operations(body, PythonProtocolKind.READ_LOCAL_CELL)
    store, = _protocol_operations(body, PythonProtocolKind.STORE_CELL)
    owners = {operation.uses[0].value for operation in (*reads, store)}
    assert len(owners) == 1
    cell = owners.pop()
    assert cell != body.interface.parameters[0].value
    assert isinstance(values[cell], ReferenceValue)
    assert not _protocol_operations(body, PythonProtocolKind.READ_FREE_CELL)
    formal_slot = body.interface.parameters[0].slot
    assert not any(isinstance(value, LocalBindingValue) and value.slot == formal_slot for value in values.values())
    exits = _protocol_operations(body, PythonProtocolKind.FRAME_EXIT)
    assert any(cell in {use.value for use in operation.uses} for operation in exits)


def test_uninitialized_local_cell_is_not_initialized_to_none(tmp_path):
    body, _ = _lower(tmp_path,
        "def outer():\n"
        "    return x\n"
        "    x = None\n"
        "    def inner():\n"
        "        return x\n", "outer")
    _, values, _ = _indexes(body)
    make, = _protocol_operations(body, PythonProtocolKind.MAKE_CELL)
    assert not _reference_uses(make, values)
    assert len(_protocol_operations(body, PythonProtocolKind.READ_LOCAL_CELL)) == 1
    assert not _protocol_operations(body, PythonProtocolKind.READ_FREE_CELL)


def test_address_owner_must_be_an_operation_owned_reference_use(tmp_path):
    body, _ = _lower(tmp_path, "def f():\n    return missing\n", "f")
    _indexes(body)
    row = body.graph.state_address_refinements[0]
    operation = next(operation for operation in body.graph.operations if operation.id == row.site.operation)
    bad_effect = replace(row.effects[0], owner=ReferenceOwner(operation.uses[-1].id))
    corrupted = replace(body.graph, state_address_refinements=(replace(row, effects=(bad_effect,)),))
    with pytest.raises(ValueError):
        require_valid(corrupted)


def test_source_program_v4_round_trip_does_not_reinterpret_structured_v1(tmp_path):
    path = tmp_path / "application.py"
    path.write_text("def f(x):\n    return external(x)\n")
    current = lower_source(path, "f", profile=BodyLoweringProfile.STRUCTURED_ENV)
    document = current.to_dict()
    assert document["schema_version"] == 4
    assert document["profile"] == "STRUCTURED_ENV_V1"
    assert document["summary"]["whole_program_coverage_established"] is False
    assert SourceProgram.from_dict(document).to_dict() == document
    historical = lower_source(path, "f", profile=BodyLoweringProfile.STRUCTURED_BODY)
    assert historical.to_dict()["schema_version"] == 3
    assert not historical.graph.environments
    assert not historical.graph.state_address_refinements
    assert SourceProgram.from_dict(historical.to_dict()).to_dict() == historical.to_dict()


@pytest.mark.parametrize("text", [
    "def f():\n    yield missing\n",
    "async def f():\n    return missing\n",
    "def f():\n    def nested():\n        return missing\n    return nested\n",
])
def test_unimplemented_body_protocols_remain_coverage_failures(tmp_path, text):
    body, _ = _lower(tmp_path, text, "f")
    assert body.graph is None
    assert body.interface is None
    assert body.metadata.gaps
