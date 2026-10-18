import json
import sys
import types

import pytest

from scar.ir.program import (
    AccessMode, Behavior, Block, BlockArgument, BlockID, CompletionResult,
    CompletionSignature, CompletionSuccessor, DataValue, ExitKind, ExitPort,
    Footprint, FootprintKind, LiteralOrigin, LocationID, Operation, OperationID,
    OperationResult, ProgramGraph, ReferenceValue, Region, RegionID, StateAccess,
    StateLocation, StateVersionValue, Successor, Terminator, TerminatorKind,
    Use, UseID, UseRole, ValueID, ValueKind, ValueType, dumps, loads,
)


@pytest.fixture
def skip_graph_validation(monkeypatch):
    module = types.ModuleType("scar.ir.program.validation")
    module.require_valid = lambda graph: None
    monkeypatch.setitem(sys.modules, "scar.ir.program.validation", module)


def graph_with(operation, *, values=(), locations=()):
    root = RegionID("main")
    block_id = BlockID("entry")
    block = Block(block_id, (), (operation.id,))
    region = Region(root, "main", block_id, (block,),
                    (ExitPort("normal", ExitKind.NORMAL, ()),))
    return ProgramGraph(root, (region,), (operation,), tuple(values), tuple(locations))


def invoke_operation(*, successors=None, completions=None, uses=None, results=(), accesses=(),
                     callee=None, invoke_arguments=(), call_arguments=()):
    if successors is None:
        successors = (
            CompletionSuccessor(ExitKind.NORMAL, BlockID("normal"),
                                (UseID("forward-normal"), CompletionResult(0))),
            CompletionSuccessor(ExitKind.RAISE, BlockID("raise"),
                                (UseID("forward-raise"), CompletionResult(0))),
        )
    if completions is None:
        completions = (
            CompletionSignature(ExitKind.NORMAL,
                                (ValueType(ValueKind.REFERENCE), ValueType(ValueKind.DATA,
                                                                           data_type="builtins.int"))),
            CompletionSignature(ExitKind.RAISE, (ValueType(ValueKind.REFERENCE),)),
        )
    if uses is None:
        uses = (
            Use(UseID("forward-normal"), ValueID("arg")),
            Use(UseID("forward-raise"), ValueID("arg")),
        )
    terminator = Terminator(TerminatorKind.INVOKE, successors=successors)
    return Operation(OperationID("invoke"), "dynamic call", (Behavior.COMPUTE,),
                     uses=tuple(uses), results=tuple(results), accesses=tuple(accesses),
                     terminator=terminator, callee=callee,
                     call_arguments=tuple(call_arguments), completions=tuple(completions),
                     invoke_arguments=tuple(invoke_arguments))


def v1_document_for(graph):
    document = json.loads(dumps(graph))
    document["schema_version"] = 1
    for operation in document["operations"]:
        operation.pop("completions")
        operation.pop("invoke_arguments")
    return document


def test_completion_records_are_typed_and_reject_bool_indices():
    signature = CompletionSignature(
        ExitKind.NORMAL, (ValueType(ValueKind.DATA, data_type="builtins.bool"),))
    assert signature.kind is ExitKind.NORMAL
    assert signature.types[0].data_type == "builtins.bool"
    assert CompletionResult(0).index == 0
    assert CompletionSuccessor(ExitKind.RAISE, BlockID("raise"),
                               (UseID("u"), CompletionResult(1))).arguments == (
                                   UseID("u"), CompletionResult(1))
    with pytest.raises(ValueError):
        CompletionResult(True)
    with pytest.raises(TypeError):
        CompletionSuccessor(ExitKind.NORMAL, BlockID("b"), ("not-an-argument",))
    with pytest.raises(TypeError):
        CompletionSignature(ExitKind.NORMAL, [ValueType(ValueKind.REFERENCE)])


def test_invoke_requires_one_distinct_normal_and_raise_completion_target():
    valid = invoke_operation()
    assert valid.terminator.kind is TerminatorKind.INVOKE
    assert len(valid.completions) == 2

    normal = CompletionSuccessor(ExitKind.NORMAL, BlockID("same"), ())
    raise_same = CompletionSuccessor(ExitKind.RAISE, BlockID("same"), ())
    with pytest.raises(ValueError, match="distinct"):
        Terminator(TerminatorKind.INVOKE, (normal, raise_same))
    # General INVOKE may now have one actual completion (wire v18); its
    # operation signature must still match, and old wire families reject it.
    assert Terminator(TerminatorKind.INVOKE, (normal,)).successors == (normal,)
    with pytest.raises(ValueError):
        Terminator(TerminatorKind.INVOKE, (
            normal, CompletionSuccessor(ExitKind.NORMAL, BlockID("other"), ())))
    with pytest.raises(TypeError):
        Terminator(TerminatorKind.JUMP, (normal,))


def test_operation_invoke_checks_signatures_results_and_preserves_ordinary_use_ids():
    input_use = Use(UseID("callee-use"), ValueID("callee"), UseRole.REFERENCE)
    forward_normal = Use(UseID("forward-normal"), ValueID("arg"))
    forward_raise = Use(UseID("forward-raise"), ValueID("arg"))
    operation = invoke_operation(uses=(input_use, forward_normal, forward_raise),
                                 invoke_arguments=(input_use.id,))
    assert operation.callee is None  # Dynamic invocation can still bind its argument uses.
    assert operation.invoke_arguments == (input_use.id,)
    assert operation.call_arguments == ()
    with pytest.raises(ValueError, match="invoke_arguments, not call_arguments"):
        invoke_operation(uses=(input_use, forward_normal, forward_raise),
                         call_arguments=(input_use.id,))
    with pytest.raises(ValueError, match="invoke_arguments must reference"):
        invoke_operation(invoke_arguments=(UseID("not-an-operation-use"),))

    with pytest.raises(ValueError, match="completion signatures"):
        invoke_operation(completions=(
            CompletionSignature(ExitKind.NORMAL, ()),
            CompletionSignature(ExitKind.NORMAL, ()),
        ))
    with pytest.raises(ValueError, match="ordinary results"):
        invoke_operation(results=(ValueID("ordinary-result"),))
    state_use = Use(UseID("state-before"), ValueID("state"), UseRole.STATE_CONTENT)
    write = StateAccess(LocationID("memory"), state_use.id, AccessMode.WRITE,
                        after=ValueID("state-after"))
    with pytest.raises(ValueError, match="state accesses"):
        invoke_operation(uses=(state_use,), accesses=(write,))
    with pytest.raises(ValueError, match="only INVOKE"):
        Operation(OperationID("jump"), "jump", (Behavior.CONTROL,),
                  terminator=Terminator(TerminatorKind.JUMP,
                                        (Successor(BlockID("next"), ()),)),
                  completions=(CompletionSignature(ExitKind.NORMAL, ()),))
    with pytest.raises(ValueError, match="only INVOKE may carry invoke_arguments"):
        Operation(OperationID("return"), "return", (Behavior.CONTROL,),
                  uses=(input_use,),
                  terminator=Terminator(TerminatorKind.RETURN, exit="normal"),
                  invoke_arguments=(input_use.id,))

    # CompletionResult is a port selector; every UseID remains a real operand.
    bad_forward = CompletionSuccessor(ExitKind.NORMAL, BlockID("normal"),
                                      (UseID("missing-use"), CompletionResult(0)))
    with pytest.raises(ValueError, match="uses"):
        invoke_operation(successors=(bad_forward, operation.terminator.successors[1]))


@pytest.mark.parametrize("literal", [True, 1, 1.25, "text", None])
def test_reference_literal_preserves_unknown_identity_and_target(literal):
    value = ReferenceValue(ValueID("literal-ref"), RegionID("main"),
                           LiteralOrigin(literal), referent_identity=None,
                           targets=(), selector=Footprint(FootprintKind.UNKNOWN))
    assert value.origin == LiteralOrigin(literal)
    assert value_type_is_reference(value)


def value_type_is_reference(value):
    from scar.ir.program import value_type
    return value_type(value).kind is ValueKind.REFERENCE


def test_reference_literal_rejects_identity_target_or_known_selector():
    args = (ValueID("r"), RegionID("main"), LiteralOrigin("x"))
    with pytest.raises(ValueError):
        ReferenceValue(*args, referent_identity="identity", targets=())
    with pytest.raises(ValueError):
        ReferenceValue(*args, targets=None)
    with pytest.raises(ValueError):
        ReferenceValue(*args, targets=(LocationID("target"),))
    with pytest.raises(ValueError):
        ReferenceValue(*args, targets=(), selector=Footprint(FootprintKind.WHOLE))
    # Nonliteral references retain the v1 unknown-target defaults.
    assert ReferenceValue(ValueID("ordinary"), RegionID("main"),
                          OperationResult(OperationID("op"), 0)).targets is None


def test_v2_codec_roundtrips_invoke_completion_union_and_literal_reference(skip_graph_validation):
    callee = Use(UseID("callee"), ValueID("callee-value"), UseRole.REFERENCE)
    normal_forward = Use(UseID("forward-normal"), ValueID("arg"))
    raise_forward = Use(UseID("forward-raise"), ValueID("arg"))
    operation = invoke_operation(
        uses=(callee, normal_forward, raise_forward), invoke_arguments=(callee.id,))
    literal = ReferenceValue(ValueID("literal"), RegionID("main"), LiteralOrigin(3),
                             targets=())
    graph = graph_with(operation, values=(literal,))

    payload = dumps(graph)
    document = json.loads(payload)
    assert document["schema_version"] == 2
    assert "completions" in document["operations"][0]
    restored = loads(payload)
    assert restored == graph
    assert type(restored.operations[0].terminator.successors[0]) is CompletionSuccessor
    assert type(restored.operations[0].terminator.successors[0].arguments[1]) is CompletionResult
    assert type(restored.values[0]) is ReferenceValue
    assert restored.values[0].origin == LiteralOrigin(3)


def test_v1_migration_only_injects_empty_completions(skip_graph_validation):
    operation = Operation(
        OperationID("return"), "return", (Behavior.CONTROL,),
        terminator=Terminator(TerminatorKind.RETURN, exit="normal"))
    graph = graph_with(operation)
    document = v1_document_for(graph)
    assert all("completions" not in item for item in document["operations"])
    restored = loads(json.dumps(document))
    assert restored == graph
    assert restored.operations[0].completions == ()
    assert restored.operations[0].invoke_arguments == ()


def test_v1_migration_rejects_new_fields_and_n2_semantics(skip_graph_validation):
    operation = Operation(
        OperationID("return"), "return", (Behavior.CONTROL,),
        terminator=Terminator(TerminatorKind.RETURN, exit="normal"))
    graph = graph_with(operation)
    document = v1_document_for(graph)
    document["operations"][0]["completions"] = []
    with pytest.raises(ValueError, match="cannot contain Operation.completions"):
        loads(json.dumps(document))
    document = v1_document_for(graph)
    document["operations"][0]["invoke_arguments"] = []
    with pytest.raises(ValueError, match="cannot contain Operation.invoke_arguments"):
        loads(json.dumps(document))

    invoke_graph = graph_with(invoke_operation())
    document = v1_document_for(invoke_graph)
    with pytest.raises(ValueError, match="INVOKE"):
        loads(json.dumps(document))

    literal_graph = graph_with(operation, values=(ReferenceValue(
        ValueID("literal"), RegionID("main"), LiteralOrigin(True), targets=()),))
    document = v1_document_for(literal_graph)
    with pytest.raises(ValueError, match="literal ReferenceValue"):
        loads(json.dumps(document))


def test_v2_codec_remains_strict_about_schema_and_fields(skip_graph_validation):
    graph = graph_with(Operation(
        OperationID("return"), "return", (Behavior.CONTROL,),
        terminator=Terminator(TerminatorKind.RETURN, exit="normal")))
    document = json.loads(dumps(graph))
    document["schema_version"] = True
    with pytest.raises(ValueError, match="version"):
        loads(json.dumps(document))
    document = json.loads(dumps(graph))
    document["operations"][0]["extra"] = 1
    with pytest.raises(ValueError):
        loads(json.dumps(document))
