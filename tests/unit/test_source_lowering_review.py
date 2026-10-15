"""Independent Python-scope and evaluation-order checks for source lowering."""

import inspect
from textwrap import dedent, indent

import pytest

from scar.analysis.program_lowering import lower_source, validate_source_program
from scar.ir.program import ExitKind, TerminatorKind
from scar.ir.program.source import GapKind, SourceRole
from scar.ir.program.validation import validate
from scar.ir.semantics_v2 import Opcode
from scar.ir.v2.common import EvidenceKind


def _lower(tmp_path, source):
    source = dedent(source).lstrip()
    path = tmp_path / "review.py"
    path.write_text(source, encoding="utf-8")
    return lower_source(path, "f")


def _python_function(source):
    namespace = {}
    exec(compile(dedent(source).lstrip(), "review-fixture.py", "exec"), namespace)
    return namespace["f"]


def _valid(result):
    assert result.graph is not None, result.metadata.gaps
    assert validate(result.graph) == ()
    checked = validate_source_program(result)
    assert checked["valid"], checked["errors"]


@pytest.mark.parametrize("binding", (
    "import x",
    "from math import pi as x",
    "del x",
    "try:\n    pass\nexcept Exception as x:\n    pass",
    "match None:\n    case x:\n        pass",
))
def test_unreachable_binding_still_makes_earlier_read_an_unbound_local(tmp_path, binding):
    source = "x = 7\ndef f():\n    return x\n" + indent(binding, "    ") + "\n"
    with pytest.raises(UnboundLocalError):
        _python_function(source)()
    result = _lower(tmp_path, source)
    assert result.graph is None, (
        "an unbound local read was incorrectly lowered as a successful global lookup",
        validate_source_program(result),
    )
    assert GapKind.UNBOUND_LOCAL in {gap.kind for gap in result.metadata.gaps}


@pytest.mark.parametrize("suspension", ("yield 1", "yield from ()"))
def test_unreachable_yield_still_changes_the_function_calling_protocol(tmp_path, suspension):
    source = f"def f(x):\n    return x\n    {suspension}\n"
    function = _python_function(source)
    assert inspect.isgeneratorfunction(function)
    instance = function(7)
    assert inspect.isgenerator(instance)
    instance.close()
    result = _lower(tmp_path, source)
    assert result.graph is None, "generator body cannot be presented as a synchronous call"
    assert GapKind.UNSUPPORTED_SIGNATURE in {gap.kind for gap in result.metadata.gaps}


def test_yield_in_a_nested_function_does_not_change_the_outer_calling_protocol(tmp_path):
    source = """
        def f(x):
            return x
            def inner():
                yield x
    """
    function = _python_function(source)
    assert not inspect.isgeneratorfunction(function)
    assert function(7) == 7
    result = _lower(tmp_path, source)
    assert GapKind.UNSUPPORTED_SIGNATURE not in {gap.kind for gap in result.metadata.gaps}
    if result.graph is not None:
        _valid(result)
    else:
        assert GapKind.UNSUPPORTED_SYNTAX in {gap.kind for gap in result.metadata.gaps}


@pytest.mark.parametrize("nested_scope", ("(x for x in ())", "(lambda: (x := 1))"))
def test_nested_expression_locals_do_not_shadow_an_outer_global_read(tmp_path, nested_scope):
    source = f"x = 7\ndef f():\n    return x\n    {nested_scope}\n"
    assert _python_function(source)() == 7
    result = _lower(tmp_path, source)
    _valid(result)
    assert GapKind.UNBOUND_LOCAL not in {gap.kind for gap in result.metadata.gaps}


def test_python_compiler_rejects_invalid_scope_even_after_closed_return_path(tmp_path):
    source = "x = 7\ndef f():\n    return x\n    global x\n"
    with pytest.raises(SyntaxError):
        compile(source, "review-fixture.py", "exec")
    try:
        result = _lower(tmp_path, source)
    except SyntaxError:
        return
    assert result.graph is None, "ast.parse alone does not establish a legal Python function"


def test_nested_calls_keep_left_to_right_evaluation_and_keyword_value_dependencies(tmp_path):
    source = "def f(target, left, right):\n    return target(left(), named=right())\n"
    events = []

    def left():
        events.append("left")
        return "left-value"

    def right():
        events.append("right")
        return "right-value"

    def target(value, *, named):
        events.append("target")
        return value, named

    assert _python_function(source)(target, left, right) == ("left-value", "right-value")
    assert events == ["left", "right", "target"]
    result = _lower(tmp_path, source)
    _valid(result)
    links = [link for link in result.metadata.operation_links if link.opcode is Opcode.CALL]
    line = source.splitlines()[1]
    assert [line[link.source.start_column:link.source.end_column] for link in links] == [
        "left()", "right()", "target(left(), named=right())",
    ]
    operations = {operation.id: operation for operation in result.graph.operations}
    blocks = {block.id: block for region in result.graph.regions for block in region.blocks}
    outputs = []
    for link in links[:2]:
        op = operations[link.operation]
        normal = next(edge for edge in op.terminator.successors if edge.kind is ExitKind.NORMAL)
        outputs.append(blocks[normal.block].arguments[0])
    outer = operations[links[-1].operation]
    actuals = {use.id: use.value for use in outer.uses}
    bound = {link.role: actuals[link.use] for link in result.metadata.use_links
             if link.operation == outer.id and link.role in ("argument", "keyword:named")}
    assert bound == {"argument": outputs[0], "keyword:named": outputs[1]}


def test_early_return_branch_does_not_require_a_definition_from_the_closed_path(tmp_path):
    source = """
        def f(flag, x, y):
            if flag:
                return x
            chosen = y
            return chosen
    """
    function = _python_function(source)
    assert function(True, 1, 2) == 1
    assert function(False, 1, 2) == 2
    result = _lower(tmp_path, source)
    _valid(result)
    parameter = next(link.value for link in result.metadata.value_links
                     if link.role is SourceRole.PARAMETER
                     and result.semantic.slots[link.slot].name == "y")
    return_link = next(link for link in result.metadata.operation_links
                       if link.role is SourceRole.RETURN and link.source.start_line == 5)
    op = next(op for op in result.graph.operations if op.id == return_link.operation)
    assert op.terminator.kind is TerminatorKind.INVOKE
    return_use = next(link.use for link in result.metadata.use_links
                      if link.operation == op.id and link.role == "return")
    assert next(use.value for use in op.uses if use.id == return_use) == parameter


def test_module_rebinding_does_not_turn_a_source_candidate_into_a_confirmed_call(tmp_path):
    source = """
        def helper(x):
            return x
        def replacement(x):
            return 2
        helper = replacement
        def f(x):
            return helper(x)
    """
    assert _python_function(source)(1) == 2
    result = _lower(tmp_path, source)
    _valid(result)
    target, = result.metadata.call_targets
    assert target.status is EvidenceKind.INFERRED
    op = next(op for op in result.graph.operations if op.id == target.operation)
    assert op.callee is None
    assert GapKind.DYNAMIC_TARGET in {gap.kind for gap in result.metadata.gaps}


def test_a_reachable_unsupported_branch_is_not_silently_dropped(tmp_path):
    result = _lower(tmp_path, """
        def f(flag, x):
            if flag:
                while x:
                    x = None
            return x
    """)
    assert result.graph is None
    gaps = [gap for gap in result.metadata.gaps if gap.kind is GapKind.UNSUPPORTED_SYNTAX]
    assert any(gap.source.start_line == 3 for gap in gaps)
