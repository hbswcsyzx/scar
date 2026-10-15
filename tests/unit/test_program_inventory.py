"""Source inventory contracts, using files rather than manually repaired graphs."""
import ast
import json
from textwrap import dedent

from scar.ir.program.validation import validate
from scar.ir.v2.ids import OperationDefinitionID


def inventory(tmp_path, source, **kwargs):
    from scar.analysis.program_inventory import inventory_program
    path = tmp_path / "entry.py"
    path.write_text(dedent(source).lstrip(), encoding="utf-8")
    result = inventory_program(path, project_root=tmp_path, **kwargs)
    selected = next(item for item in result.files if item.snapshot.path == str(path))
    return result, selected, ast.parse(path.read_text()), path


def same_span(reference, node):
    return (reference.start_line, reference.end_line,
            reference.start_column, reference.end_column) == (
                node.lineno, node.end_lineno, node.col_offset, node.end_col_offset)


def definition_at(file, node):
    matches = [item for item in file.definitions if same_span(item.source, node)]
    assert len(matches) == 1
    return matches[0]


def call_at(file, node):
    matches = [item for item in file.calls if same_span(item.source, node)]
    assert len(matches) == 1
    return matches[0]


def calls_in(tree):
    return [node for node in ast.walk(tree) if isinstance(node, ast.Call)]


def test_type_alias_value_is_an_annotation_boundary(tmp_path):
    if not hasattr(ast, "TypeAlias"):
        return  # Syntax is unavailable on older supported Python versions.
    _, file, tree, _ = inventory(tmp_path, "type Result = produce_type()\n")
    call = call_at(file, tree.body[0].value)
    assert call.phase.name == "ANNOTATION"
    assert any("type-alias" in gap.detail for gap in file.gaps)


def test_inventory_schema_and_independent_reconstruction(tmp_path):
    from scar.analysis.program_inventory import ProgramInventory
    result, file, _, _ = inventory(tmp_path, """
        def identity(value):
            return value
        def alternate(value):
            return None
    """)
    document = result.to_dict()
    assert document["schema"] == "scar.program-inventory"
    assert document["schema_version"] == 5
    assert document["runtime_scope"] is None
    assert document["interfaces"]["bodies"]
    json.dumps(document, allow_nan=False)
    restored = ProgramInventory.from_dict(
        document, max_files=128, max_bytes=8_000_000, max_directories=4096,
        max_lowered_bodies=256, max_operations=10000)
    assert restored.to_dict() == document
    assert isinstance(result.summary(), dict)
    assert len(file.definitions) == 2
    assert all(isinstance(item.id, OperationDefinitionID) for item in file.definitions)
    lowered = [body for body in file.bodies if body.graph is not None]
    assert len(lowered) == 2
    assert {body.definition for body in lowered} == {item.id for item in file.definitions}
    for body in lowered:
        assert body.status.name == "LOWERED_WITH_GAPS"
        assert body.metadata is not None
        assert validate(body.graph) == ()


def test_repeated_qualname_retains_both_definition_identities(tmp_path):
    _, file, tree, _ = inventory(tmp_path, """
        def duplicate(value):
            return value
        saved = duplicate
        def duplicate(value):
            return None
    """)
    nodes = [item for item in tree.body if isinstance(item, ast.FunctionDef)]
    first, second = [definition_at(file, node) for node in nodes]
    assert first.name == second.name and first.qualname == second.qualname
    assert first.id != second.id
    assert first.source.atom_id != second.source.atom_id
    assert {body.definition for body in file.bodies} >= {first.id, second.id}


def test_definition_time_calls_have_outer_owner_and_body_calls_have_function_owner(tmp_path):
    _, file, tree, _ = inventory(tmp_path, """
        @decorate(factory())
        def work(value=make(), *, option=configure()):
            return consume(value)
    """)
    node = tree.body[0]
    definition = definition_at(file, node)
    assert definition.kind.name == "FUNCTION"
    roles = {item.role.name for item in definition.definition_inputs}
    assert {"DECORATOR", "DEFAULT", "KEYWORD_DEFAULT"} <= roles
    outer_calls = calls_in(node.decorator_list[0]) + calls_in(node.args.defaults[0]) + calls_in(node.args.kw_defaults[0])
    owners = set()
    for call in outer_calls:
        record = call_at(file, call)
        assert record.phase.name == "MODULE_INITIALIZATION"
        assert record.execution_owner != definition.id
        owners.add(record.execution_owner)
    assert len(owners) == 1
    body_call = call_at(file, node.body[0].value)
    assert body_call.execution_owner == definition.id
    assert body_call.phase.name == "FUNCTION_BODY"
    assert len(file.calls) == len(outer_calls) + 1


def test_nested_default_executes_in_outer_function_scope(tmp_path):
    _, file, tree, _ = inventory(tmp_path, """
        def outer(seed):
            def inner(value=prepare(seed)):
                return finish(value)
            return inner
    """)
    outer_node = tree.body[0]
    inner_node = outer_node.body[0]
    outer = definition_at(file, outer_node)
    inner = definition_at(file, inner_node)
    assert inner.lexical_owner == outer.id
    default = call_at(file, inner_node.args.defaults[0])
    assert default.execution_owner == outer.id
    assert default.phase.name == "FUNCTION_BODY"
    body = call_at(file, inner_node.body[0].value)
    assert body.execution_owner == inner.id
    assert body.phase.name == "FUNCTION_BODY"


def test_class_initialization_and_method_calls_are_distinct(tmp_path):
    _, file, tree, _ = inventory(tmp_path, """
        class Container(base_factory(), metaclass=meta_factory()):
            field = construct()
            def method(self, value=prepare()):
                return consume(value)
    """)
    class_node = tree.body[0]
    method_node = class_node.body[1]
    cls = definition_at(file, class_node)
    method = definition_at(file, method_node)
    assert cls.kind.name == "CLASS"
    assert method.lexical_owner == cls.id
    assert {item.role.name for item in cls.definition_inputs} >= {"BASE", "METACLASS"}
    for node in (class_node.bases[0], class_node.keywords[0].value):
        call = call_at(file, node)
        assert call.phase.name == "MODULE_INITIALIZATION"
        assert call.execution_owner != cls.id
    for node in (class_node.body[0].value, method_node.args.defaults[0]):
        call = call_at(file, node)
        assert call.execution_owner == cls.id
        assert call.phase.name == "CLASS_BODY"
    body = call_at(file, method_node.body[0].value)
    assert body.execution_owner == method.id
    assert body.phase.name == "FUNCTION_BODY"


def test_uncalled_function_import_remains_deferred(tmp_path):
    (tmp_path / "optional_local.py").write_text("token = 1\n", encoding="utf-8")
    result, file, tree, _ = inventory(tmp_path, """
        def dormant():
            import optional_local
            return None
    """)
    definition = definition_at(file, tree.body[0])
    dependencies = [item for item in result.discovery.imports
                    if same_span(item.source, tree.body[0].body[0])
                    and item.source.path == file.snapshot.path]
    assert dependencies and all(item.deferred for item in dependencies)
    assert all(item.owner_qualname == definition.qualname for item in dependencies)
    imports = [item for item in file.coverage if same_span(item.source, tree.body[0].body[0])]
    assert imports
    assert all(item.owner == definition.id and item.phase.name == "FUNCTION_BODY"
               for item in imports)


def test_parameter_shadow_cannot_select_same_named_source_function(tmp_path):
    _, file, tree, _ = inventory(tmp_path, """
        def helper(value):
            return value
        def caller(helper, value):
            return helper(value)
    """)
    helper = definition_at(file, tree.body[0])
    caller = definition_at(file, tree.body[1])
    call = call_at(file, tree.body[1].body[0].value)
    assert call.execution_owner == caller.id
    assert helper.id not in call.candidates
    body = next(item for item in file.bodies if item.definition == caller.id)
    assert body.graph is not None
    assert all(op.callee is None for op in body.graph.operations)
    assert all(target.candidate is None for target in body.metadata.call_targets)


def test_inventory_covers_all_unsupported_locations_after_first_lowering_failure(tmp_path):
    _, file, tree, _ = inventory(tmp_path, """
        def process(items, target):
            for item in items:
                target[0] = item
            assert target
            target[1] = None
            return target
    """)
    node = tree.body[0]
    definition = definition_at(file, node)
    unsupported = [item for item in ast.walk(node)
                   if isinstance(item, (ast.For, ast.Assert))
                   or isinstance(item, ast.Subscript) and isinstance(item.ctx, ast.Store)]
    assert len(unsupported) == 4
    for item in unsupported:
        covered = [entry for entry in file.coverage if same_span(entry.source, item)
                   and entry.ast_kind == type(item).__name__]
        assert covered, f"lost source coverage at line {item.lineno}: {type(item).__name__}"
        assert all(entry.owner == definition.id and entry.phase.name == "FUNCTION_BODY"
                   for entry in covered)
        assert all(entry.status.name != "CONNECTED" and entry.reason for entry in covered)
    body = next(item for item in file.bodies if item.definition == definition.id)
    assert body.graph is None and body.status.name == "UNSUPPORTED"
    assert body.reason


def test_discovery_does_not_execute_definition_inputs_or_module(tmp_path):
    marker = tmp_path / "executed"
    result, file, _, _ = inventory(tmp_path, f"""
        open({str(marker)!r}, 'w').write('executed')
        def work(value=open({str(marker)!r}, 'w')):
            return value
    """)
    assert not marker.exists()
    assert len(file.calls) == 3
    assert result.to_dict()["schema"] == "scar.program-inventory"
