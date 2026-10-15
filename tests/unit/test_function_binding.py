"""Raw signature binding plans retain source and runtime-state conditions."""
import ast
from dataclasses import replace
from textwrap import dedent

import pytest

from scar.analysis.function_binding import bind_call
from scar.analysis.function_interfaces import extract_signature
from scar.analysis.program_lowering import prepare_source
from scar.ir.program.functions import (
    ArgumentKind, BindingCondition, BindingIssueKind, BindingOrigin,
    CallArgument, CallBindingStatus,
)
from scar.ir.program.inventory import DefinitionInventory, DefinitionKind
from scar.ir.v2.ids import OperationDefinitionID


def source_case(tmp_path, text):
    """Use generated source atoms, definitions and slots for binder inputs."""
    path = tmp_path / "binding.py"
    path.write_text(dedent(text).lstrip(), encoding="utf-8")
    context = prepare_source(path, project_root=tmp_path)
    atoms = {(atom.kind, atom.reference.start_line, atom.reference.end_line,
              atom.reference.start_column, atom.reference.end_column): atom.reference
             for atom in context.semantic.source_atoms.values()}

    def source(node):
        return atoms[(type(node).__name__, node.lineno, node.end_lineno,
                      node.col_offset, node.end_col_offset)]

    function = next(node for node in context.tree.body
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and node.name == "target")
    definition = next(item for item in context.semantic.definitions.values()
                      if item.code_id == source(function).atom_id.wire
                      and item.metadata.get("phase") == "call_time")
    inventory = DefinitionInventory(
        definition.id, source(function), function.name, function.name,
        DefinitionKind.ASYNC_FUNCTION if isinstance(function, ast.AsyncFunctionDef) else DefinitionKind.FUNCTION,
        None,
    )
    signature = extract_signature(context, inventory)
    bindings = []
    for node in ast.walk(context.tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name) or node.func.id != "target":
            continue
        arguments = []
        for actual in node.args:
            arguments.append(CallArgument(
                len(arguments), source(actual),
                ArgumentKind.STARRED if isinstance(actual, ast.Starred) else ArgumentKind.POSITIONAL,
            ))
        for keyword in node.keywords:
            arguments.append(CallArgument(
                len(arguments), source(keyword.value),
                ArgumentKind.DOUBLE_STARRED if keyword.arg is None else ArgumentKind.KEYWORD,
                keyword.arg,
            ))
        operation = next(item for item in context.semantics.operations.values()
                         if item.source == source(node))
        bindings.append(bind_call(signature, call=operation.operation, target=definition.id,
                                  source=source(node), arguments=tuple(arguments)))
    return signature, tuple(bindings), context


def routes_by_name(signature, binding):
    assert tuple(route.slot for route in binding.routes) == tuple(parameter.slot for parameter in signature.parameters)
    return {parameter.name: route for parameter, route in zip(signature.parameters, binding.routes)}


def test_all_formal_kinds_bind_in_canonical_source_order(tmp_path):
    signature, (binding,), context = source_case(tmp_path, """
        def target(first, /, second, *items, flag, option=None, **options):
            return first
        target(11, 22, 33, 44, flag=True, spare=55)
    """)
    assert binding.status is CallBindingStatus.CONDITIONAL
    routes = routes_by_name(signature, binding)
    assert routes["first"].argument_indices == (0,)
    assert routes["second"].argument_indices == (1,)
    assert routes["items"].origin is BindingOrigin.VAR_POSITIONAL_PACK
    assert routes["items"].argument_indices == (2, 3)
    assert routes["flag"].argument_indices == (4,)
    assert routes["option"].origin is BindingOrigin.DEFAULT_STATE
    assert routes["option"].default_source == signature.parameters[4].default_source
    assert routes["options"].origin is BindingOrigin.VAR_KEYWORD_PACK
    assert routes["options"].argument_indices == (5,)
    assert {parameter.slot for parameter in signature.parameters} <= set(context.semantic.slots)
    assert all(actual.source.atom_id in context.semantic.source_atoms for actual in binding.arguments)
    assert binding.source.atom_id in context.semantic.source_atoms
    assert binding.conditions == tuple(BindingCondition)


def test_empty_variadic_packs_are_explicit(tmp_path):
    signature, (binding,), _ = source_case(tmp_path, """
        def target(*items, **options):
            return items
        target()
    """)
    routes = routes_by_name(signature, binding)
    assert binding.status is CallBindingStatus.CONDITIONAL
    assert routes["items"].origin is BindingOrigin.VAR_POSITIONAL_PACK
    assert routes["options"].origin is BindingOrigin.VAR_KEYWORD_PACK
    assert routes["items"].argument_indices == routes["options"].argument_indices == ()
    assert BindingCondition.PACKING_AND_BINDING_EFFECTS_PRESERVED in binding.conditions


def test_positional_only_name_is_an_independent_varkw_key(tmp_path):
    signature, bindings, _ = source_case(tmp_path, """
        def target(value, /, **options):
            return value
        target(10, value=20)
        target(value=30)
    """)
    valid, missing = bindings
    routes = routes_by_name(signature, valid)
    assert valid.status is CallBindingStatus.CONDITIONAL
    assert routes["value"].argument_indices == (0,)
    assert routes["options"].argument_indices == (1,)
    assert missing.status is CallBindingStatus.INCOMPATIBLE
    assert missing.routes == ()
    assert any(issue.kind is BindingIssueKind.MISSING_REQUIRED
               and issue.slot == signature.parameters[0].slot for issue in missing.issues)
    assert all(issue.kind is not BindingIssueKind.POSITIONAL_ONLY_KEYWORD for issue in missing.issues)


@pytest.mark.parametrize(("declaration", "call_text", "expected"), [
    ("value", "target()", BindingIssueKind.MISSING_REQUIRED),
    ("value", "target(1, 2)", BindingIssueKind.TOO_MANY_POSITIONAL),
    ("value", "target(1, value=2)", BindingIssueKind.DUPLICATE_ARGUMENT),
    ("value, /", "target(value=2)", BindingIssueKind.POSITIONAL_ONLY_KEYWORD),
    ("value", "target(1, extra=2)", BindingIssueKind.UNEXPECTED_KEYWORD),
    ("value, *, flag", "target(1)", BindingIssueKind.MISSING_REQUIRED),
])
def test_explicit_incompatibility_has_no_formal_routes(tmp_path, declaration, call_text, expected):
    signature, (binding,), _ = source_case(
        tmp_path, f"def target({declaration}):\n    return None\n{call_text}\n",
    )
    assert binding.status is CallBindingStatus.INCOMPATIBLE
    assert binding.routes == ()
    assert expected in {issue.kind for issue in binding.issues}
    assert binding.conditions == tuple(BindingCondition)
    for issue in binding.issues:
        assert issue.slot is None or issue.slot in {parameter.slot for parameter in signature.parameters}
        assert set(issue.argument_indices) <= {argument.index for argument in binding.arguments}


@pytest.mark.parametrize(("declaration", "receiving_formal"), [
    ("value", "value"),
    ("**options", "options"),
    ("value=0, /, **options", "options"),
])
def test_repeated_explicit_keywords_are_incompatible(tmp_path, declaration, receiving_formal):
    signature, (base,), _ = source_case(
        tmp_path, f"def target({declaration}):\n    return None\ntarget(value=1)\n",
    )
    # The second source actual is reused only as a typed fixture: Python's
    # compiler rejects repeated explicit keyword spelling before execution.
    arguments = base.arguments + (replace(base.arguments[0], index=1),)
    binding = bind_call(signature, call=base.call, target=base.target,
                        source=base.source, arguments=arguments)
    assert binding.status is CallBindingStatus.INCOMPATIBLE
    assert binding.routes == ()
    duplicate = next(issue for issue in binding.issues if issue.kind is BindingIssueKind.DUPLICATE_ARGUMENT)
    assert duplicate.argument_indices == (0, 1)
    assert duplicate.slot == next(parameter.slot for parameter in signature.parameters
                                  if parameter.name == receiving_formal)


def test_defaults_are_current_function_state_across_calls_and_writes(tmp_path):
    signature, bindings, _ = source_case(tmp_path, """
        def target(value=[], *, option={}):
            value.append(option)
            return value
        target()
        target()
        target.__defaults__ = (['replacement'],)
        target.__kwdefaults__ = {'option': {'changed': True}}
        target()
    """)
    assert len(bindings) == 3
    assert len({binding.call for binding in bindings}) == 3
    assert len({binding.source for binding in bindings}) == 3
    for binding in bindings:
        assert binding.status is CallBindingStatus.CONDITIONAL
        assert BindingCondition.FUNCTION_DEFAULT_STATE_MATCHES_SOURCE_DECLARATION in binding.conditions
        assert all(route.origin is BindingOrigin.DEFAULT_STATE for route in binding.routes)
        assert tuple(route.default_source for route in binding.routes) == tuple(
            parameter.default_source for parameter in signature.parameters)
        assert all(route.argument_indices == () for route in binding.routes)
    # The stable declaration route does not claim the original mutable object
    # survives writes or default-state replacement, or gets recreated per call.
    assert bindings[0].routes == bindings[1].routes == bindings[2].routes


def test_added_runtime_default_does_not_upgrade_raw_missing_argument(tmp_path):
    _, (binding,), _ = source_case(tmp_path, """
        def target(value):
            return value
        target.__defaults__ = (123,)
        target()
    """)
    assert binding.status is CallBindingStatus.INCOMPATIBLE
    assert BindingCondition.FUNCTION_DEFAULT_STATE_MATCHES_SOURCE_DECLARATION in binding.conditions
    assert BindingCondition.RAW_FUNCTION_TARGET_MATCHES_SIGNATURE in binding.conditions
    assert binding.routes == ()


def test_two_calls_keep_their_actual_sources(tmp_path):
    signature, (first, second), _ = source_case(tmp_path, """
        def target(value, *, flag):
            return value
        target(11, flag='first')
        target(22, flag='second')
    """)
    assert first.status is second.status is CallBindingStatus.CONDITIONAL
    assert first.call != second.call and first.source != second.source
    assert routes_by_name(signature, first) == routes_by_name(signature, second)
    assert all(left.source != right.source for left, right in zip(first.arguments, second.arguments))
    assert all(argument.source.start_line == first.source.start_line for argument in first.arguments)
    assert all(argument.source.start_line == second.source.start_line for argument in second.arguments)


@pytest.mark.parametrize("actuals", ["*explode()", "**explode()", "1, *explode(), value=2", "1, **explode()"])
def test_expansion_is_incomplete_without_evaluation(tmp_path, actuals):
    _, (binding,), _ = source_case(tmp_path, f"""
        def explode():
            raise AssertionError('source must never execute')
        def target(value):
            return value
        target({actuals})
    """)
    assert binding.status is CallBindingStatus.INCOMPLETE
    assert binding.routes == ()
    assert {issue.kind for issue in binding.issues} == {BindingIssueKind.EXPANDED_ARGUMENT}
    assert all(binding.arguments[index].kind in (ArgumentKind.STARRED, ArgumentKind.DOUBLE_STARRED)
               for issue in binding.issues for index in issue.argument_indices)
    assert binding.conditions == tuple(BindingCondition)


@pytest.mark.parametrize(("declaration", "body", "expected"), [
    ("@replace_callable\ndef target(value):", "return value", BindingIssueKind.DECORATED_TARGET),
    ("async def target(value):", "return value", BindingIssueKind.SUSPENDED_BODY),
    ("def target(value):", "yield value", BindingIssueKind.SUSPENDED_BODY),
    ("async def target(value):", "yield value", BindingIssueKind.SUSPENDED_BODY),
])
def test_decorated_and_suspended_source_bodies_remain_incomplete(tmp_path, declaration, body, expected):
    _, (binding,), _ = source_case(
        tmp_path, f"{declaration}\n    {body}\ntarget(1)\n",
    )
    assert binding.status is CallBindingStatus.INCOMPLETE
    assert binding.routes == ()
    assert expected in {issue.kind for issue in binding.issues}
    assert binding.conditions == tuple(BindingCondition)


def test_absent_signature_and_mismatched_target_are_explicit(tmp_path):
    signature, (base,), _ = source_case(tmp_path, """
        def target(value):
            return value
        target(1)
    """)
    absent = bind_call(None, call=base.call, target=base.target,
                       source=base.source, arguments=base.arguments)
    assert absent.status is CallBindingStatus.INCOMPLETE
    assert absent.issues[0].kind is BindingIssueKind.NO_SIGNATURE
    assert absent.routes == ()
    assert absent.conditions == tuple(BindingCondition)
    with pytest.raises(ValueError, match="target"):
        bind_call(signature, call=base.call, target=OperationDefinitionID("other"),
                  source=base.source, arguments=base.arguments)


def test_noncontiguous_actual_indices_are_rejected(tmp_path):
    signature, (base,), _ = source_case(tmp_path, """
        def target(value):
            return value
        target(1)
    """)
    with pytest.raises(ValueError, match="indices"):
        bind_call(signature, call=base.call, target=base.target, source=base.source,
                  arguments=(replace(base.arguments[0], index=2),))
