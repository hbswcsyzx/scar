"""Declared content/source examples over original producers, not recovered code."""
from scar.ir.literals import PythonLiteral, literal_builtin_type
from scar.ir.program import (
    AccessMode, Behavior, Block, BlockArgument, BlockID, CodeConstant,
    CompletionResult, CompletionSignature, CompletionSuccessor, DataValue,
    ExactLiteralOrigin, ExitKind, ExitPort, InvokeLiteralResult, LiteralEvaluation,
    LocationID, Operation, OperationID, OperationResult, ProgramGraph, ReferenceValue,
    Region, RegionID, SourceExpression, StateAccess, StateLocation, StateVersionValue,
    Terminator, TerminatorKind, UninterpretedConstant, UnlocatedLiteral,
    Use, UseID, UseRole, ValueID, ValueKind, ValueType,
)
from scar.ir.program.providers import ProviderArtifact, ProviderFactReference
from scar.ir.program.structured import ControlEdgeReference
from scar.ir.v2.common import SourceReference
from scar.ir.v2.ids import SourceAtomID


def literal_program(*, exact=True, attachments=True, payload="a\x00literal"):
    """Direct and NORMAL results; landing physical order differs from signature."""
    rid, loc = RegionID("literal.root"), LocationID("literal.world")
    def value(name): return ValueID(name)
    def op(name): return OperationID(name)
    def use(name, val, role=UseRole.DATA): return Use(UseID(name), value(val), role)
    def arg(name, index): return BlockArgument(BlockID(name), index)
    def result(name, index=0): return OperationResult(op(name), index)
    literal = PythonLiteral.from_python(payload, exact=True)
    kind = literal_builtin_type(literal)
    if exact:
        constant = DataValue(value("constant"), rid, ExactLiteralOrigin(literal),
                             kind.__module__ + "." + kind.__qualname__)
    else:
        from scar.ir.program import LiteralOrigin
        constant = DataValue(value("constant"), rid, LiteralOrigin("legacy"), "builtins.str")
    vals = (
        ReferenceValue(value("input"), rid, arg("entry", 0)),
        StateVersionValue(value("world0"), rid, arg("entry", 1), loc),
        constant,
        DataValue(value("computed"), rid, result("direct", 0), "builtins.str"),
        ReferenceValue(value("constructed"), rid, result("direct", 1)),
        StateVersionValue(value("world1"), rid, result("direct", 2), loc),
        StateVersionValue(value("normal.world"), rid, arg("normal", 0), loc),
        ReferenceValue(value("normal.ref"), rid, arg("normal", 1)),
        DataValue(value("normal.data"), rid, arg("normal", 2), "builtins.str"),
        StateVersionValue(value("raise.world"), rid, arg("failure", 0), loc),
        ReferenceValue(value("raise.error"), rid, arg("failure", 1)),
    )
    direct = Operation(op("direct"), "construct a declared content", (Behavior.COMPUTE, Behavior.READ, Behavior.WRITE), (
        use("direct.left", "input", UseRole.REFERENCE),
        use("direct.right", "input", UseRole.REFERENCE), use("direct.constant", "constant"),
        use("direct.state", "world0", UseRole.STATE_CONTENT),
    ), (value("computed"), value("constructed"), value("world1")),
        accesses=(StateAccess(loc, UseID("direct.state"), AccessMode.READ_WRITE, value("world1")),),
        effects_complete=False)
    data_type, ref_type, state_type = ValueType(ValueKind.DATA, "builtins.str"), ValueType(ValueKind.REFERENCE), ValueType(ValueKind.STATE, location=loc)
    invoke = Operation(op("invoke"), "fallible original production", (Behavior.CONTROL,), (
        use("invoke.ref", "constructed", UseRole.REFERENCE),
        use("invoke.data", "computed"), use("invoke.state", "world1", UseRole.STATE_CONTENT),
    ), completions=(CompletionSignature(ExitKind.NORMAL, (data_type, ref_type, state_type)),
                    CompletionSignature(ExitKind.RAISE, (ref_type, state_type))),
        invoke_arguments=(UseID("invoke.ref"), UseID("invoke.data"), UseID("invoke.state")),
        terminator=Terminator(TerminatorKind.INVOKE, (
            CompletionSuccessor(ExitKind.NORMAL, BlockID("normal"), (CompletionResult(2), CompletionResult(1), CompletionResult(0))),
            CompletionSuccessor(ExitKind.RAISE, BlockID("failure"), (CompletionResult(1), CompletionResult(0))),
        )))
    done = Operation(op("return"), "return", (Behavior.CONTROL,), (
        use("return.data", "normal.data"), use("return.ref", "normal.ref", UseRole.REFERENCE),
        use("return.state", "normal.world", UseRole.STATE_CONTENT),
    ), terminator=Terminator(TerminatorKind.RETURN, exit="normal", values=(UseID("return.data"), UseID("return.ref"), UseID("return.state"))))
    fail = Operation(op("raise"), "raise", (Behavior.CONTROL,), (
        use("raise.error.use", "raise.error", UseRole.REFERENCE),
        use("raise.state", "raise.world", UseRole.STATE_CONTENT),
    ), terminator=Terminator(TerminatorKind.RAISE, exit="failure", values=(UseID("raise.error.use"), UseID("raise.state"))))
    region = Region(rid, "literal evaluation declarations", BlockID("entry"), (
        Block(BlockID("entry"), (value("input"), value("world0")), (op("direct"), op("invoke"))),
        Block(BlockID("normal"), (value("normal.world"), value("normal.ref"), value("normal.data")), (op("return"),)),
        Block(BlockID("failure"), (value("raise.world"), value("raise.error")), (op("raise"),)),
    ), (ExitPort("normal", ExitKind.NORMAL, (data_type, ref_type, state_type)),
        ExitPort("failure", ExitKind.RAISE, (ref_type, state_type))))
    fact = ProviderFactReference(ProviderArtifact("declared:code", "a" * 64, 123, "declared.code-record"), "#/code/0")
    source = SourceExpression(SourceReference(SourceAtomID("literal.expression"), "declared.py", "sha256:" + "b" * 64, 1, 1))
    rows = (
        LiteralEvaluation(result("direct", 0), PythonLiteral.from_python("computed", exact=True), source),
        LiteralEvaluation(result("direct", 1), UninterpretedConstant("runtime construction is not replayed")),
        LiteralEvaluation(InvokeLiteralResult(ControlEdgeReference(op("invoke"), 0), CompletionResult(0)), PythonLiteral.from_python("normal", exact=True), CodeConstant(fact, 3)),
        LiteralEvaluation(InvokeLiteralResult(ControlEdgeReference(op("invoke"), 0), CompletionResult(1)), PythonLiteral.from_python((1, None), exact=True), UnlocatedLiteral("object payload declaration only")),
    ) if attachments else ()
    graph = ProgramGraph(rid, (region,), (direct, invoke, done, fail), vals,
                         (StateLocation(loc, "coarse world"),), literal_evaluations=rows)
    return graph, {"direct": result("direct", 0), "reference": result("direct", 1),
                   "invoke": InvokeLiteralResult(ControlEdgeReference(op("invoke"), 0), CompletionResult(0)),
                   "invoke_reference": InvokeLiteralResult(ControlEdgeReference(op("invoke"), 0), CompletionResult(1)),
                   "code_fact": fact, "source": source}
