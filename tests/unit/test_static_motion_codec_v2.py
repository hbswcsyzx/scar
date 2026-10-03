"""Strict codec and OIR-shape coverage for typed static source moves.

The source fragment below is derived from a generic local Python fixture. These
tests cover its serialization and OIR membership constraints only; an OIR
roundtrip is not a source-motion legality proof.
"""
from copy import deepcopy
from dataclasses import replace

import pytest

from scar.analysis.control_flow_v2 import build_source_control_flow
from scar.analysis.source_fragments_v2 import derive_source_fragment
from scar.analysis.source_semantics_v2 import extract_source_semantics
from scar.ir import control_flow_v2
from scar.ir import v2 as core_ir
from scar.ir.frontend_v2 import build_semantic
from scar.ir.record_codec import decode, encode
from scar.ir.source_fragments_v2 import (
    source_fragment_from_dict,
    source_fragment_from_json,
    source_fragment_to_dict,
    source_fragment_to_json,
    static_source_move_from_dict,
    static_source_move_from_json,
    static_source_move_to_dict,
    static_source_move_to_json,
)
from scar.ir.v2 import (
    ControlRegionID,
    LogicalValueID,
    OperationDefinitionID,
    OptimizationRegionID,
    PlanAlternativeID,
    SourceVersion,
    StaticSourceMove,
    TransformDelta,
    ValueVersionID,
)
from scar.ir.v2.codec import optimization_from_dict
from scar.ir.v2.ids import (
    ControlFlowNodeID,
    ControlFlowSuiteID,
    InsertionPointID,
    StaticValueID,
)
from scar.ir.v2.optimization import (
    LiteralValue,
    OptimizationContext,
    OptimizationGraph,
    OptimizationRegion,
    PlanAlternative,
    RegionGranularity,
    RegionMove,
    SourceFragment,
    StaticValueSubstitution,
    TransformKind,
    ValueSubstitution,
)
from scar.ir.v2.common import SourceVersion as CoreSourceVersion
from scar.ir.v2.ids import (
    ControlFlowNodeID as CoreControlFlowNodeID,
    ControlFlowSuiteID as CoreControlFlowSuiteID,
    InsertionPointID as CoreInsertionPointID,
)
from scar.ir.literals import PythonLiteral


PROGRAM = "def calculate():\n    result = 3\n"


def _source_case(tmp_path):
    path = tmp_path / "program.py"
    path.write_text(PROGRAM)
    semantic = build_semantic(path, project_root=tmp_path).graph
    sources = {module.path: PROGRAM for module in semantic.modules.values()
               if module.path and module.fingerprint}
    source_semantics = extract_source_semantics(semantic, sources=sources)
    control_flow = build_source_control_flow(
        semantic, source_semantics, sources=sources)
    statements = [node for node in control_flow.nodes.values()
                  if node.source is not None and node.source.start_line == 2
                  and node.kind.value == "statement"]
    assert len(statements) == 1
    statement = statements[0]
    fragment = derive_source_fragment(
        semantic, source_semantics, control_flow, statement.id, sources=sources)
    insertion = next(iter(control_flow.insertions.values()))
    return semantic, source_semantics, control_flow, fragment, insertion.id


def _optimization_case(semantic, fragment, insertion, *, delta=None):
    context = OptimizationContext(
        definitions=frozenset(semantic.definitions),
        source_atoms=frozenset(semantic.source_atoms),
    )
    graph = OptimizationGraph(context)
    region_id = OptimizationRegionID("whole-statement")
    graph.add_region(OptimizationRegion(
        region_id,
        RegionGranularity.INSTRUCTION,
        "one source statement",
        definitions=fragment.operation_ids,
        source_atoms=(fragment.source.atom_id,),
    ))
    original_id = PlanAlternativeID("original")
    graph.add_alternative(PlanAlternative(
        original_id, region_id, "original", TransformKind.NO_OP,
        original=True,
    ))
    alternative = PlanAlternative(
        PlanAlternativeID("move-statement"), region_id, "move statement",
        TransformKind.MOVE,
        delta if delta is not None else TransformDelta(
            static_moves=(StaticSourceMove(fragment, insertion),)),
        fallback=original_id,
    )
    return graph, alternative, context


def _alternative_record(document, identity="move-statement"):
    return next(item for item in document["alternatives"]
                if item["id"]["value"] == identity)


def test_core_records_and_schema4_oir_roundtrip(tmp_path):
    semantic, _source_semantics, _control_flow, fragment, insertion = _source_case(tmp_path)

    assert type(fragment) is SourceFragment
    assert type(fragment.statement) is ControlFlowNodeID
    assert type(fragment.suite) is ControlFlowSuiteID
    assert type(insertion) is InsertionPointID

    fragment_dict = source_fragment_to_dict(fragment)
    assert source_fragment_from_dict(fragment_dict) == fragment
    assert source_fragment_from_json(source_fragment_to_json(fragment)) == fragment
    assert decode(SourceFragment, encode(fragment)) == fragment

    move = StaticSourceMove(fragment, insertion)
    move_dict = static_source_move_to_dict(move)
    assert static_source_move_from_dict(move_dict) == move
    assert static_source_move_from_json(static_source_move_to_json(move)) == move
    assert decode(StaticSourceMove, encode(move)) == move

    graph, alternative, context = _optimization_case(semantic, fragment, insertion)
    graph.add_alternative(alternative)
    document = graph.to_dict()
    assert document["schema_version"] == 4
    assert _alternative_record(document)["delta"]["static_moves"] == [move_dict["move"]]

    restored = optimization_from_dict(document, context)
    assert restored.to_dict() == document
    restored_move = restored.alternatives[alternative.id].delta.static_moves[0]
    assert type(restored_move) is StaticSourceMove
    assert type(restored_move.fragment) is SourceFragment
    # Shape and roundtrip validation do not establish MOVE legality.


def test_control_flow_and_core_reexports_share_typed_class_identity():
    assert control_flow_v2.ControlFlowSuiteID is CoreControlFlowSuiteID
    assert control_flow_v2.ControlFlowSuiteID is core_ir.ControlFlowSuiteID
    assert control_flow_v2.ControlFlowNodeID is CoreControlFlowNodeID
    assert control_flow_v2.ControlFlowNodeID is core_ir.ControlFlowNodeID
    assert control_flow_v2.InsertionPointID is CoreInsertionPointID
    assert control_flow_v2.InsertionPointID is core_ir.InsertionPointID
    assert control_flow_v2.SourceVersion is CoreSourceVersion
    assert control_flow_v2.SourceVersion is core_ir.SourceVersion is SourceVersion


def test_schema4_requires_static_moves_and_exact_nested_id_categories(tmp_path):
    semantic, _source_semantics, _control_flow, fragment, insertion = _source_case(tmp_path)
    graph, alternative, context = _optimization_case(semantic, fragment, insertion)
    graph.add_alternative(alternative)
    document = graph.to_dict()

    missing = deepcopy(document)
    _alternative_record(missing)["delta"].pop("static_moves")
    with pytest.raises(ValueError, match="static_moves"):
        optimization_from_dict(missing, context)

    wrong_id = deepcopy(document)
    record = _alternative_record(wrong_id)["delta"]["static_moves"][0]
    record["fragment"]["statement"] = fragment.suite.as_dict()
    with pytest.raises(ValueError):
        optimization_from_dict(wrong_id, context)

    missing_fragment_field = deepcopy(document)
    record = _alternative_record(missing_fragment_field)["delta"]["static_moves"][0]
    record["fragment"].pop("source_version")
    with pytest.raises(ValueError):
        optimization_from_dict(missing_fragment_field, context)


@pytest.mark.parametrize("corruption", ["duplicate_operation", "digest_case"])
def test_static_move_reader_rejects_noncanonical_fragment_records(tmp_path, corruption):
    semantic, _source_semantics, _control_flow, fragment, insertion = _source_case(tmp_path)
    move = StaticSourceMove(fragment, insertion)
    document = static_source_move_to_dict(move)
    bad = deepcopy(document)

    if corruption == "duplicate_operation":
        bad["move"]["fragment"]["operation_ids"].append(
            deepcopy(bad["move"]["fragment"]["operation_ids"][0]))
    else:
        bad["move"]["fragment"]["text_digest"] = "sha256:" + "A" * 64

    with pytest.raises(ValueError):
        static_source_move_from_dict(bad)


@pytest.mark.parametrize("mixed_delta", [
    lambda fragment, insertion, region: TransformDelta(
        removed_definitions=fragment.operation_ids,
        static_moves=(StaticSourceMove(fragment, insertion),)),
    lambda fragment, insertion, region: TransformDelta(
        substitutions=(ValueSubstitution(
            ValueVersionID(LogicalValueID("value"), 0),
            literal=LiteralValue(7)),),
        static_moves=(StaticSourceMove(fragment, insertion),)),
    lambda fragment, insertion, region: TransformDelta(
        static_substitutions=(StaticValueSubstitution(
            # The move-mixing guard must reject before resolving this unrelated
            # static-value reference against the optimization context.
            StaticValueID("value"),
            fragment.operation_ids[0], fragment.source,
            PythonLiteral.from_python(7)),),
        static_moves=(StaticSourceMove(fragment, insertion),)),
    lambda fragment, insertion, region: TransformDelta(
        moves=(RegionMove(region, ControlRegionID("before"),
                          ControlRegionID("after")),),
        static_moves=(StaticSourceMove(fragment, insertion),)),
    lambda fragment, insertion, region: TransformDelta(
        added_operations=("operation",),
        static_moves=(StaticSourceMove(fragment, insertion),)),
])
def test_oir_rejects_mixed_static_move_deltas(tmp_path, mixed_delta):
    semantic, _source_semantics, _control_flow, fragment, insertion = _source_case(tmp_path)
    graph, alternative, _context = _optimization_case(semantic, fragment, insertion)
    region = alternative.region
    mixed = mixed_delta(fragment, insertion, region)
    with pytest.raises(ValueError, match="cannot mix unrelated"):
        graph.add_alternative(replace(alternative, delta=mixed))


@pytest.mark.parametrize("forgery", ["unknown_scope", "unknown_operation"])
def test_oir_rejects_fragments_with_unknown_scope_or_operation(tmp_path, forgery):
    semantic, _source_semantics, _control_flow, fragment, insertion = _source_case(tmp_path)
    graph, alternative, _context = _optimization_case(semantic, fragment, insertion)

    if forgery == "unknown_scope":
        forged = replace(fragment,
            scope=OperationDefinitionID("unknown-scope"))
    else:
        unknown = OperationDefinitionID("unknown-operation")
        forged = replace(fragment, operation_ids=tuple(sorted(
            (*fragment.operation_ids, unknown), key=lambda item: item.wire)))
    move = StaticSourceMove(forged, insertion)

    with pytest.raises(ValueError):
        graph.add_alternative(replace(alternative,
            delta=TransformDelta(static_moves=(move,))))
