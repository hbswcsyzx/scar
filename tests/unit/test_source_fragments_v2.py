from dataclasses import replace
import re

import pytest

from scar.analysis.control_flow_v2 import build_source_control_flow
from scar.analysis.source_fragments_v2 import (
    derive_source_fragment,
    validate_source_fragment,
)
from scar.analysis.source_semantics_v2 import extract_source_semantics
from scar.ir.control_flow_v2 import (
    ControlFlowBudget,
    ControlFlowNodeID,
    InsertionKind,
    NodeKind,
)
from scar.ir.frontend_v2 import build_semantic
from scar.ir.source_fragments_v2 import (
    SourceFragment,
    StaticSourceMove,
    source_fragment_from_dict,
    source_fragment_from_json,
    source_fragment_to_dict,
    source_fragment_to_json,
    static_source_move_from_dict,
    static_source_move_to_dict,
)
from scar.ir.v2.ids import OperationDefinitionID, SourceAtomID
from scar.ir.v2.optimization import SourceFragment as CoreSourceFragment
from scar.ir.v2.optimization import StaticSourceMove as CoreStaticSourceMove
from scar.ir.v2.common import SourceReference


PROGRAM = """def compute():
    token = ()
    marker = 1 + 2
    alias = token
    return alias
"""


def models(tmp_path, text=PROGRAM):
    path = tmp_path / "program.py"
    path.write_text(text)
    semantic = build_semantic(path, project_root=tmp_path).graph
    sources = {module.path: text for module in semantic.modules.values()
               if module.path and module.fingerprint}
    source_semantics = extract_source_semantics(semantic, sources=sources)
    control_flow = build_source_control_flow(
        semantic, source_semantics, sources=sources)
    return semantic, source_semantics, control_flow, sources


def statement_at(control_flow, line):
    matches = [item for item in control_flow.nodes.values()
               if item.kind is NodeKind.STATEMENT and item.source is not None
               and item.source.start_line == line]
    assert len(matches) == 1
    return matches[0]


def test_fragment_serde_roundtrip_and_move_schema_are_strict(tmp_path):
    semantic, source_semantics, control_flow, sources = models(tmp_path)
    statement = statement_at(control_flow, 4)
    fragment = derive_source_fragment(
        semantic, source_semantics, control_flow, statement.id, sources=sources)

    assert type(fragment) is SourceFragment is CoreSourceFragment
    assert fragment.statement == statement.id
    assert fragment.suite == statement.suite
    assert fragment.scope == statement.scope
    assert fragment.source == statement.source
    assert fragment.source_version == control_flow.suites[statement.suite].version
    assert statement.operations[0] in fragment.operation_ids
    assert re.fullmatch(r"sha256:[0-9a-f]{64}", fragment.text_digest)
    assert validate_source_fragment(
        fragment, semantic, source_semantics, control_flow, sources=sources)["valid"]

    fragment_document = source_fragment_to_dict(fragment)
    assert source_fragment_from_dict(fragment_document) == fragment
    assert source_fragment_from_json(source_fragment_to_json(fragment)) == fragment

    insertion = next(item for item in control_flow.insertions.values()
                     if item.kind is InsertionKind.BEFORE
                     and item.anchor == statement_at(control_flow, 3).id)
    move = StaticSourceMove(fragment, insertion.id)
    assert type(move) is CoreStaticSourceMove
    assert static_source_move_from_dict(static_source_move_to_dict(move)) == move

    forged = source_fragment_to_dict(fragment)
    forged["extra"] = True
    with pytest.raises(ValueError, match="schema or fields"):
        source_fragment_from_dict(forged)

    forged = source_fragment_to_dict(fragment)
    forged["fragment"]["text_digest"] = "sha256:bad"
    with pytest.raises(ValueError):
        source_fragment_from_dict(forged)


def test_fragment_covers_statement_owner_and_rhs_read_binding_operations(tmp_path):
    semantic, source_semantics, control_flow, sources = models(tmp_path)
    statement = statement_at(control_flow, 4)
    fragment = derive_source_fragment(
        semantic, source_semantics, control_flow, statement.id, sources=sources)

    contained = {
        operation.operation
        for operation in source_semantics.operations.values()
        if operation.scope == statement.scope
        and operation.source.path == statement.source.path
        and (operation.source.start_line, operation.source.start_column)
            >= (statement.source.start_line, statement.source.start_column)
        and (operation.source.end_line, operation.source.end_column)
            <= (statement.source.end_line, statement.source.end_column)
    }
    assert contained
    assert contained <= set(fragment.operation_ids)
    assert set(statement.operations) <= set(fragment.operation_ids)


def test_changed_source_and_wrong_source_anchor_are_rejected(tmp_path):
    semantic, source_semantics, control_flow, sources = models(tmp_path)
    statement = statement_at(control_flow, 4)
    fragment = derive_source_fragment(
        semantic, source_semantics, control_flow, statement.id, sources=sources)

    changed = dict(sources)
    path = statement.source.path
    changed[path] = changed[path].replace("alias = token", "alias = token + 0")
    report = validate_source_fragment(
        fragment, semantic, source_semantics, control_flow, sources=changed)
    assert not report["valid"]
    assert any("fingerprint" in item for item in report["errors"])

    forged_source = replace(fragment.source, atom_id=SourceAtomID("forged-source-atom"))
    forged = replace(fragment, source=forged_source)
    report = validate_source_fragment(
        forged, semantic, source_semantics, control_flow, sources=sources)
    assert not report["valid"]

    with pytest.raises(ValueError, match="absent"):
        derive_source_fragment(semantic, source_semantics, control_flow,
            ControlFlowNodeID("dangling-statement"), sources=sources)


def test_operation_membership_tampering_is_rederived_not_trusted(tmp_path):
    semantic, source_semantics, control_flow, sources = models(tmp_path)
    statement = statement_at(control_flow, 3)
    fragment = derive_source_fragment(
        semantic, source_semantics, control_flow, statement.id, sources=sources)
    forged = replace(fragment, operation_ids=(OperationDefinitionID("forged-operation"),))

    report = validate_source_fragment(
        forged, semantic, source_semantics, control_flow, sources=sources)
    assert not report["valid"]
    assert any("operation membership" in item for item in report["errors"])


def test_operation_membership_does_not_use_mutable_metadata_as_authority(tmp_path):
    semantic, source_semantics, control_flow, sources = models(tmp_path)
    statement = statement_at(control_flow, 3)
    original = derive_source_fragment(
        semantic, source_semantics, control_flow, statement.id, sources=sources)

    semantic.definitions[statement.operations[0]].metadata["purity_claim"] = True
    source_semantics = extract_source_semantics(semantic, sources=sources)
    control_flow = build_source_control_flow(
        semantic, source_semantics, sources=sources)
    refreshed_statement = statement_at(control_flow, 3)
    refreshed = derive_source_fragment(
        semantic, source_semantics, control_flow, refreshed_statement.id, sources=sources)

    assert refreshed.operation_ids == original.operation_ids
    assert validate_source_fragment(
        refreshed, semantic, source_semantics, control_flow, sources=sources)["valid"]


@pytest.mark.parametrize("text, line, error", [
    ("def f():\n    left = right = 1\n", 2, "chained, unpacking"),
    ("def f():\n    if True:\n        value = 1\n", 2, "simple statement node"),
    ("def f():\n    value = lambda: 1\n", 2, "nested-scope"),
    ("def f():\n    value = 1; other = 2\n", 2, "standalone statement"),
])
def test_compound_nested_and_shared_statement_regions_are_rejected(
        tmp_path, text, line, error):
    semantic, source_semantics, control_flow, sources = models(tmp_path, text)
    candidate = [item for item in control_flow.nodes.values()
                 if item.kind in {NodeKind.STATEMENT, NodeKind.BRANCH_TEST,
                                  NodeKind.LOOP_TEST, NodeKind.GAP}
                 and item.source is not None and item.source.start_line == line]
    assert candidate
    candidate.sort(key=lambda item: (item.source.start_column, item.id.wire))
    with pytest.raises(ValueError, match=error):
        derive_source_fragment(semantic, source_semantics, control_flow,
                               candidate[0].id, sources=sources)


def test_duplicate_statement_position_is_rejected_before_replay(tmp_path):
    semantic, source_semantics, control_flow, sources = models(tmp_path)
    statement = statement_at(control_flow, 3)
    duplicate_id = ControlFlowNodeID("duplicate-statement-position")
    control_flow.nodes[duplicate_id] = replace(statement, id=duplicate_id)

    with pytest.raises(ValueError, match="duplicate statement source positions"):
        derive_source_fragment(semantic, source_semantics, control_flow,
                               statement.id, sources=sources)


@pytest.mark.parametrize("budget, message", [
    (ControlFlowBudget(max_source_bytes=8), "source-byte budget"),
    (ControlFlowBudget(max_ast_nodes=1), "AST-node budget"),
])
def test_source_fragment_replay_obeys_caller_verification_budget(
        tmp_path, budget, message):
    semantic, source_semantics, control_flow, sources = models(tmp_path)
    statement = statement_at(control_flow, 3)

    with pytest.raises(ValueError, match=message):
        derive_source_fragment(semantic, source_semantics, control_flow,
            statement.id, sources=sources, verification_budget=budget)
