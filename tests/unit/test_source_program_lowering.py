"""Automatic source construction; no fixture patches repair the resulting IR."""
from dataclasses import FrozenInstanceError, replace
import json
from textwrap import dedent

import pytest

from scar.ir.program.codec import dumps, loads
from scar.ir.program.ids import OperationID
from scar.ir.program.model import (
    BlockArgument, CompletionResult, DataValue, ExitKind, ReferenceValue, StateVersionValue,
    TerminatorKind, UseRole, value_type,
)
from scar.ir.program.source import (
    CandidateArgument, CandidateResult, GapKind, LoweringMetadata, OperationSource, SourceRole,
)
from scar.ir.program.validation import validate
from scar.ir.semantics_v2 import Opcode
from scar.ir.v2._validation import record_errors
from scar.ir.v2.common import EvidenceKind


CHOOSE = """
def choose(x):
    if x is None:
        y = 1
    else:
        y = 2
    return y
"""

CALLS = """
def helper(v):
    return v

def calls(x):
    first = helper(x)
    second = helper(first)
    return second
"""


def lower(tmp_path, text, entry, **kwargs):
    from scar.analysis.program_lowering import lower_source
    path = tmp_path / "program.py"
    path.write_text(dedent(text).lstrip(), encoding="utf-8")
    return lower_source(path, entry, **kwargs)


def assert_valid(result):
    from scar.analysis.program_lowering import validate_source_program
    assert result.graph is not None, result.metadata.gaps
    assert validate(result.graph) == ()
    assert loads(dumps(result.graph)) == result.graph
    checked = validate_source_program(result)
    assert checked["valid"], checked["errors"]
    assert not checked["errors"]
    assert record_errors(result.metadata, LoweringMetadata, "metadata") == []
    expected_uses = {(op.id, use.id) for op in result.graph.operations for use in op.uses}
    actual_uses = [(link.operation, link.use) for link in result.metadata.use_links]
    assert len(actual_uses) == len(set(actual_uses))
    assert set(actual_uses) == expected_uses
    json.dumps(result.to_dict(), allow_nan=False)


def assert_replay_rejects(result):
    from scar.analysis.program_lowering import validate_source_program
    checked = validate_source_program(result)
    assert not checked["valid"]
    assert checked["errors"]


def opcode_links(result, opcode):
    return [link for link in result.metadata.operation_links if link.opcode is opcode]


def operation(result, identity):
    return next(op for op in result.graph.operations if op.id == identity)


def test_choose_builds_real_join_from_source(tmp_path):
    result = lower(tmp_path, CHOOSE, "choose")
    assert_valid(result)
    graph = result.graph
    values = {value.id: value for value in graph.values}
    merges = [values[link.value] for link in result.metadata.value_links
              if link.role is SourceRole.MERGE
              and isinstance(values[link.value], ReferenceValue)]
    assert merges, "the two path definitions must meet in a block argument"
    assert any(op.terminator and op.terminator.kind is TerminatorKind.BRANCH
               for op in graph.operations)
    for merge in merges:
        assert isinstance(merge.origin, BlockArgument)
        incoming = []
        for op in graph.operations:
            if op.terminator is None:
                continue
            uses = {use.id: use.value for use in op.uses}
            for successor in op.terminator.successors:
                if successor.block == merge.origin.block:
                    incoming.append(uses[successor.arguments[merge.origin.index]])
        assert len(incoming) >= 2
        assert len(set(incoming)) >= 2, "branch-local definitions cannot be conflated"
        assert any(use.value == merge.id for op in graph.operations for use in op.uses)
    assert opcode_links(result, Opcode.IS)
    assert result.metadata.entry == "choose"


def test_parameter_reference_and_world_state_are_explicit(tmp_path):
    result = lower(tmp_path, CHOOSE, "choose")
    assert_valid(result)
    values = {value.id: value for value in result.graph.values}
    parameters = [link for link in result.metadata.value_links
                  if link.role is SourceRole.PARAMETER]
    assert parameters
    for link in parameters:
        value = values[link.value]
        assert isinstance(value, ReferenceValue)
        assert isinstance(value.origin, BlockArgument)
        assert value.referent_identity is None and value.targets is None
        assert link.slot in result.semantic.slots
    for region in result.graph.regions:
        for block in region.blocks:
            assert any(isinstance(values[item], StateVersionValue)
                       for item in block.arguments)
        assert {port.kind for port in region.exits} == {ExitKind.NORMAL, ExitKind.RAISE}


def test_unknown_truth_has_bool_and_exceptional_state_completion(tmp_path):
    result = lower(tmp_path, """
        def choose(x):
            if x:
                return 1
            else:
                return 2
    """, "choose")
    assert_valid(result)
    truth = [link for link in result.metadata.operation_links if link.role is SourceRole.TRUTH]
    assert truth
    values = {value.id: value for value in result.graph.values}
    blocks = {block.id: block for region in result.graph.regions for block in region.blocks}
    for link in truth:
        op = operation(result, link.operation)
        assert not op.effects_complete
        assert op.terminator.kind is TerminatorKind.INVOKE
        assert {s.kind for s in op.terminator.successors} == {ExitKind.NORMAL, ExitKind.RAISE}
        normal = next(s for s in op.terminator.successors if s.kind is ExitKind.NORMAL)
        assert any(isinstance(values[item], DataValue)
                   and values[item].data_type == "builtins.bool"
                   for item in blocks[normal.block].arguments)
        for successor in op.terminator.successors:
            assert any(isinstance(values[item], StateVersionValue)
                       for item in blocks[successor.block].arguments)
    assert GapKind.DYNAMIC_DISPATCH in {gap.kind for gap in result.metadata.gaps}


@pytest.mark.parametrize("symbol,opcode", [("+", Opcode.ADD), ("*", Opcode.MUL)])
def test_operator_identity_comes_from_typed_source_semantics(tmp_path, symbol, opcode):
    result = lower(tmp_path, f"def arithmetic(a: int, b: int):\n    return a {symbol} b\n", "arithmetic")
    assert_valid(result)
    links = opcode_links(result, opcode)
    assert len(links) == 1
    link = links[0]
    assert link.semantic_operation in result.semantics.operations
    old = result.semantics.operations[link.semantic_operation]
    assert old.opcode is opcode and len(old.operands) == 2
    use_links = [item for item in result.metadata.use_links
                 if item.operation == link.operation and item.semantic_value is not None]
    assert {(item.role, item.index, item.semantic_value) for item in use_links} >= {
        (item.role, item.index, item.value) for item in old.operands}
    op = operation(result, link.operation)
    assert op.terminator.kind is TerminatorKind.INVOKE
    assert not op.effects_complete, "annotations do not resolve Python dispatch"
    assert GapKind.DYNAMIC_DISPATCH in {gap.kind for gap in result.metadata.gaps}


def test_repeated_operand_reads_keep_distinct_source_use_positions(tmp_path):
    result = lower(tmp_path, "def f(x):\n    return x + x\n", "f")
    assert_valid(result)
    link = opcode_links(result, Opcode.ADD)[0]
    old = result.semantics.operations[link.semantic_operation]
    matching = [item for item in result.metadata.use_links
                if item.operation == link.operation
                and item.semantic_value in {operand.value for operand in old.operands}]
    assert len(matching) == 2
    assert matching[0].use != matching[1].use
    assert matching[0].source.atom_id != matching[1].source.atom_id
    assert matching[0].source.start_column != matching[1].source.start_column
    uses = {item.id: item.value for item in operation(result, link.operation).uses}
    assert uses[matching[0].use] == uses[matching[1].use]


def test_two_calls_keep_candidate_body_and_occurrences_separate(tmp_path):
    result = lower(tmp_path, CALLS, "calls")
    assert_valid(result)
    targets = result.metadata.call_targets
    assert len(targets) == 2
    assert targets[0].candidate is not None
    assert targets[0].candidate == targets[1].candidate
    assert targets[0].operation != targets[1].operation
    assert targets[0].source_definition == targets[1].source_definition
    ops = [operation(result, item.operation) for item in targets]
    for target, op in zip(targets, ops):
        assert target.status is EvidenceKind.INFERRED
        assert target.conditions
        assert op.callee is None, "a same-file definition is only a binding candidate"
        assert any(use.value == target.callee_reference and use.role is UseRole.REFERENCE
                   for use in op.uses)
        assert op.terminator.kind is TerminatorKind.INVOKE
        assert not op.effects_complete
    assert set(use.id for use in ops[0].uses).isdisjoint(use.id for use in ops[1].uses)
    assert set(s.block for s in ops[0].terminator.successors).isdisjoint(
        s.block for s in ops[1].terminator.successors)
    assert GapKind.DYNAMIC_TARGET in {gap.kind for gap in result.metadata.gaps}


def test_local_rebinding_is_not_a_confirmed_module_helper(tmp_path):
    result = lower(tmp_path, """
        def helper(v):
            return v
        def calls(x):
            helper = x
            return helper(x)
    """, "calls")
    assert_valid(result)
    assert len(result.metadata.call_targets) == 1
    target = result.metadata.call_targets[0]
    assert target.candidate is None and target.source_definition is None
    assert operation(result, target.operation).callee is None
    assert GapKind.DYNAMIC_TARGET in {gap.kind for gap in result.metadata.gaps}


def test_candidate_interfaces_cover_exact_arguments_and_both_completion_ports(tmp_path):
    result = lower(tmp_path, CALLS, "calls")
    assert_valid(result)
    values = {value.id: value for value in result.graph.values}
    regions = {region.id: region for region in result.graph.regions}
    blocks = {block.id: block for region in result.graph.regions for block in region.blocks}
    for target in result.metadata.call_targets:
        op = operation(result, target.operation)
        body = regions[target.candidate]
        entry = blocks[body.entry]
        assert target.status is EvidenceKind.INFERRED and op.callee is None
        assert tuple(item.parameter for item in target.arguments) == entry.arguments
        assert len({item.use for item in target.arguments}) == len(entry.arguments)
        uses = {use.id: use for use in op.uses}
        for item in target.arguments:
            assert isinstance(item, CandidateArgument)
            assert value_type(values[uses[item.use].value]) == value_type(values[item.parameter])
            assert uses[item.use].value != target.callee_reference
        assert any(isinstance(values[item.parameter], StateVersionValue)
                   for item in target.arguments)
        expected = {}
        for successor in op.terminator.successors:
            for position, argument in enumerate(successor.arguments):
                if isinstance(argument, CompletionResult):
                    expected[(successor.kind, argument.index)] = blocks[successor.block].arguments[position]
        assert {(item.kind, item.index): item.value for item in target.results} == expected
        assert len(target.results) == len(expected)
        exits = {port.kind: port for port in body.exits}
        assert set(expected) == {(port.kind, index) for port in body.exits
                                 for index in range(len(port.types))}
        for item in target.results:
            assert isinstance(item, CandidateResult)
            assert value_type(values[item.value]) == exits[item.kind].types[item.index]
        assert target.binding_use in result.semantics.uses
        binding = result.semantics.uses[target.binding_use]
        old_call = result.semantics.operations[next(
            link.semantic_operation for link in result.metadata.operation_links
            if link.operation == op.id)]
        callee_operand = next(item for item in old_call.operands if item.role == "callee")
        old_read = result.semantics.operations[result.semantics.values[callee_operand.value].producer]
        assert old_read.binding_use == target.binding_use
        assert binding.source == old_read.source
    first, second = result.metadata.call_targets
    assert first.binding_use != second.binding_use
    assert {item.parameter for item in first.arguments} == {item.parameter for item in second.arguments}
    assert {item.value for item in first.results}.isdisjoint(item.value for item in second.results)


@pytest.mark.parametrize("field", ["arguments", "results", "binding_use"])
def test_same_type_cross_call_correspondence_tampering_is_rejected(tmp_path, field):
    result = lower(tmp_path, CALLS, "calls")
    assert_valid(result)
    first, second = result.metadata.call_targets
    assert first.arguments and first.results and first.binding_use
    # Same body and same types do not authorize borrowing another occurrence's ports.
    forged = replace(first, **{field: getattr(second, field)})
    metadata = replace(result.metadata, call_targets=(forged, second))
    assert_replay_rejects(replace(result, metadata=metadata))


def test_candidate_interface_not_fabricated_for_wrong_argument_count(tmp_path):
    result = lower(tmp_path, """
        def helper(left, right):
            return left
        def calls(x):
            return helper(x)
    """, "calls")
    assert_valid(result)
    target, = result.metadata.call_targets
    assert target.arguments == () and target.results == ()
    assert target.status is EvidenceKind.INFERRED
    assert operation(result, target.operation).callee is None
    assert GapKind.DYNAMIC_TARGET in {gap.kind for gap in result.metadata.gaps}


@pytest.mark.parametrize("text,entry,gap", [
    ("def f(x):\n    if x is None:\n        y = 1\n    return y\n", "f", GapKind.UNBOUND_LOCAL),
    ("def f(x=1):\n    return x\n", "f", GapKind.UNSUPPORTED_SIGNATURE),
    ("def f(*args):\n    return args\n", "f", GapKind.UNSUPPORTED_SIGNATURE),
    ("@decorate\ndef f(x):\n    return x\n", "f", GapKind.UNSUPPORTED_SIGNATURE),
    ("def f(x):\n    while x:\n        x = None\n    return x\n", "f", GapKind.UNSUPPORTED_SYNTAX),
])
def test_unsupported_source_has_located_gap_and_no_repaired_graph(tmp_path, text, entry, gap):
    result = lower(tmp_path, text, entry)
    assert result.graph is None
    matches = [item for item in result.metadata.gaps if item.kind is gap]
    assert matches
    assert all(item.detail and item.source.fingerprint == result.metadata.source.fingerprint
               and item.source.start_line >= 1 for item in matches)
    json.dumps(result.to_dict(), allow_nan=False)


def test_operation_budget_returns_gap(tmp_path):
    result = lower(tmp_path, CHOOSE, "choose", max_operations=1)
    assert result.graph is None
    assert GapKind.BUDGET in {gap.kind for gap in result.metadata.gaps}


def test_construction_does_not_execute_module_or_function(tmp_path):
    marker = tmp_path / "executed"
    result = lower(tmp_path, f"""
        open({str(marker)!r}, 'w').write('module executed')
        def f(x):
            return x
    """, "f")
    assert not marker.exists()
    assert result.metadata.entry == "f"


def test_renaming_does_not_change_typed_operator_rule(tmp_path):
    first = lower(tmp_path, "def f(a, b):\n    return a + b\n", "f")
    second = lower(tmp_path, "def renamed(left, right):\n    return left + right\n", "renamed")
    assert first.graph is not None and second.graph is not None
    assert len(opcode_links(first, Opcode.ADD)) == len(opcode_links(second, Opcode.ADD)) == 1
    assert not opcode_links(second, Opcode.MUL)


def test_source_edit_invalidates_replay(tmp_path):
    result = lower(tmp_path, "def f(a, b):\n    return a + b\n", "f")
    assert_valid(result)
    (tmp_path / "program.py").write_text("def f(a, b):\n    return a * b\n", encoding="utf-8")
    assert_replay_rejects(result)


def test_wrong_typed_opcode_link_invalidates_replay(tmp_path):
    result = lower(tmp_path, "def f(a, b):\n    return a + b\n", "f")
    assert_valid(result)
    original = opcode_links(result, Opcode.ADD)[0]
    metadata = replace(result.metadata, operation_links=tuple(
        replace(link, opcode=Opcode.MUL) if link == original else link
        for link in result.metadata.operation_links))
    assert_replay_rejects(replace(result, metadata=metadata))


def test_missing_source_correspondence_invalidates_replay(tmp_path):
    result = lower(tmp_path, CHOOSE, "choose")
    assert_valid(result)
    assert result.metadata.operation_links
    metadata = replace(result.metadata, operation_links=result.metadata.operation_links[1:])
    assert_replay_rejects(replace(result, metadata=metadata))


def test_source_records_are_frozen_and_typed(tmp_path):
    result = lower(tmp_path, CHOOSE, "choose")
    assert_valid(result)
    link = result.metadata.operation_links[0]
    with pytest.raises(FrozenInstanceError):
        link.operation = OperationID("different")
    # The replay validator rechecks records, including decoder-created objects.
    malformed = replace(link, operation=link.source.atom_id)
    assert record_errors(malformed, OperationSource, "link")
    assert_replay_rejects(replace(result, metadata=replace(
        result.metadata, operation_links=(malformed,) + result.metadata.operation_links[1:])))
