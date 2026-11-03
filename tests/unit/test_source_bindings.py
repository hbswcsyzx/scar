"""C2b lexical protocols/captures, without runtime objects or C3 claims."""
import _symtable
import ast
import builtins
from copy import deepcopy
import json
import sys

import pytest

from scar.analysis.source_bytes import source_bytes_document
from scar.analysis.source_tokens import source_tokens_document
from scar.analysis.source_syntax import source_syntax_document
from scar.analysis.source_roles import source_roles_document
from scar.analysis.source_contexts import source_contexts_document
from scar.analysis.source_declarations import source_declarations_document
from scar.ir.program.source_syntax import SourceSyntaxMaterial
from scar.ir.program.source_roles import SourceRolesMaterial
from scar.ir.program.source_contexts import SourceContextsMaterial
from scar.ir.program.source_declarations import SourceDeclarationsMaterial
from scar.ir.record_codec import decode


pytestmark = pytest.mark.skipif(
    sys.implementation.name != 'cpython' or sys.version_info[:3] != (3, 14, 7),
    reason='lexical protocol rules are pinned to CPython 3.14.7')


def _inputs(text, *, mode='exec', max_tokens=2_000_000):
    f0 = source_bytes_document(text.encode(), path='/source/bindings.py', namespace_root='/source')
    f1 = source_tokens_document(f0, max_tokens=max_tokens)
    f2 = source_syntax_document(f0, f1, mode=mode)
    roles = source_roles_document(f0, f1, f2)
    contexts = source_contexts_document(f0, f1, f2, roles)
    declarations = source_declarations_document(f0, f1, f2, roles, contexts)
    return f0, f1, f2, roles, contexts, declarations


def _occurrence(syntax, path):
    node, index = syntax.nodes[syntax.root], syntax.root
    for part in path:
        node = node.fields[getattr(ast, node.constructor)._fields.index(part)] if isinstance(part, str) else node.items[part]
        if node.kind == 'NODE':
            index = node.reference
            node = syntax.nodes[index]
    return index


def _site(syntax, path, field, item_path=()):
    from scar.ir.program.source_roles import SlotRef
    occurrence = _occurrence(syntax, path)
    return SlotRef(occurrence, 'FIELD', getattr(ast, syntax.nodes[occurrence].constructor)._fields.index(field), item_path)


def _source():
    return '''root_value = root_name
global root_global
root_global = root_name
def outer(items):
    value = 1
    def middle():
        global value
        def leaf(): return value
        return leaf
    def write_only():
        nonlocal value
        value = 0
    class ClassGlobal:
        global value
        value = 2
        def method(self): return value
    class ClassNonlocal:
        nonlocal value
        snapshot = value
        value = 3
        del value
    class AnnotationBound:
        if condition: value = 4
        field: value
    class AnnotationGlobal:
        global value
        field: value
    class AnnotationFree:
        field: value
    rows = [lambda: value for value in items]
    walrus = [(saved := item) for item in items]
    local: (lambda: hidden)
    return value
global exported
exports = [(exported := item) for item in source]
class Generic:
    T = marker
    def method[T](self, argument:T)->T:
        return T
class Super:
    __class__ = marker
    def method(self, super): return super
    def explicit(self): return __class__, __classdict__, __conditional_annotations__
    if condition: field: T
module_field: RootAnnotation
'''


@pytest.mark.parametrize('family', ('matrix', 'capture_and_implicit', 'codec_and_budgets'))
def test_c2b_namespace_templates(family, monkeypatch):
    import scar.analysis.source_bindings as api
    inputs = _inputs(_source())
    syntax = decode(SourceSyntaxMaterial, inputs[2])
    roles = decode(SourceRolesMaterial, inputs[3])
    contexts = decode(SourceContextsMaterial, inputs[4])
    declarations = decode(SourceDeclarationsMaterial, inputs[5])
    original_native = _symtable.symtable
    def forbidden(*args, **kwargs):
        raise AssertionError('C2b must not call native symbol analysis or execute target code')
    with monkeypatch.context() as patch:
        patch.setattr(_symtable, 'symtable', forbidden)
        document = api.source_bindings_document(*inputs)
        material = api.read_source_bindings(json.loads(json.dumps(document)), *inputs)
    assert material.status == 'RESOLVED' and not material.conflicts
    assert material.authority == 'SOURCE_NAMESPACE_TEMPLATES'
    assert material.runtime_binding == 'NOT_OBSERVED' and material.compiler_projection == 'NOT_COMPUTED_IN_C2B'
    assert material.profile.projection_phase == 'SYMBOL_VISIT_PROJECTION'

    def name(ref, declared=declarations):
        return declared.names[ref.index].value if ref.kind == 'SOURCE' else ref.symbol

    def port(path, field='id', *, role=None, item_path=()):
        site = _site(syntax, path, field, item_path)
        found = [i for i, row in enumerate(roles.ports) if row.site == site and (role is None or row.role == role)]
        assert len(found) == 1, (path, field, found)
        return material.ports[found[0]]

    def kinds(row, snapshot=material):
        assert row.read_plan is not None
        return tuple(snapshot.interfaces[step.interface].kind for step in snapshot.plans[row.read_plan].steps)

    def read_binding(row, snapshot=material):
        return snapshot.interfaces[snapshot.plans[row.read_plan].steps[-1].interface].binding

    def target(row, access):
        index = row.write_target if access == 'WRITE' else row.delete_target
        assert index is not None
        return material.interfaces[index]

    outer = ('body', 3)
    if family == 'matrix':
        # Handwritten protocol expectations; IDs are local template references.
        assert kinds(port(('body', 0, 'value'))) == ('ROOT_LOCALS', 'ROOT_GLOBALS', 'BUILTINS')
        assert target(port(('body', 0, 'targets', 0)), 'WRITE').kind == 'ROOT_LOCALS'
        assert target(port(('body', 2, 'targets', 0)), 'WRITE').kind == 'ROOT_GLOBALS'
        leaf = port((*outer, 'body', 1, 'body', 1, 'body', 0, 'value'))
        assert kinds(leaf) == ('ENV_GLOBALS', 'BUILTINS')
        method = port((*outer, 'body', 3, 'body', 2, 'body', 0, 'value'))
        assert kinds(method) == ('LEXICAL_BINDING',)
        outer_binding = read_binding(method)
        assert contexts.scopes[material.bindings[outer_binding].owner].owner.occurrence == _occurrence(syntax, outer)
        assert target(port((*outer, 'body', 3, 'body', 1, 'targets', 0)), 'WRITE').kind == 'ENV_GLOBALS'
        read = port((*outer, 'body', 4, 'body', 1, 'value'))
        write = port((*outer, 'body', 4, 'body', 2, 'targets', 0))
        delete = port((*outer, 'body', 4, 'body', 3, 'targets', 0))
        assert kinds(read) == ('CLASS_PREPARED_MAPPING', 'LEXICAL_BINDING')
        assert read_binding(read) == outer_binding
        assert target(write, 'WRITE').kind == target(delete, 'DELETE').kind == 'LEXICAL_BINDING'
        assert target(write, 'WRITE').binding == target(delete, 'DELETE').binding == outer_binding
        bound = port((*outer, 'body', 5, 'body', 1, 'annotation'))
        global_ = port((*outer, 'body', 6, 'body', 1, 'annotation'))
        free = port((*outer, 'body', 7, 'body', 0, 'annotation'))
        assert kinds(bound) == ('CLASS_ANNOTATION_NAMESPACE', 'ENV_GLOBALS', 'BUILTINS')
        assert kinds(global_) == ('ENV_GLOBALS', 'BUILTINS')
        assert kinds(free) == ('CLASS_ANNOTATION_NAMESPACE', 'LEXICAL_BINDING')
        assert read_binding(free) == outer_binding
        generic = ('body', 6, 'body', 1)
        header = port((*generic, 'args', 'args', 1, 'annotation'))
        body = port((*generic, 'body', 0, 'value'))
        assert kinds(header) == ('CLASS_ANNOTATION_NAMESPACE', 'ENV_GLOBALS', 'BUILTINS')
        assert kinds(body) == ('LEXICAL_BINDING',)
        type_binding = material.bindings[read_binding(body)]
        assert type_binding.domain == 'TYPE_PARAMETER_BINDING'
        assert contexts.scopes[type_binding.owner].kind == 'TYPE_PARAMETERS'
        comp = (*outer, 'body', 8, 'value')
        iteration = port((*comp, 'generators', 0, 'target'))
        lambda_value = port((*comp, 'elt', 'body'))
        assert kinds(lambda_value) == ('LEXICAL_BINDING',)
        assert target(iteration, 'WRITE').binding == read_binding(lambda_value) != outer_binding
        saved = port((*outer, 'body', 9, 'value', 'elt', 'target'))
        assert contexts.scopes[material.bindings[target(saved, 'WRITE').binding].owner].owner.occurrence == _occurrence(syntax, outer)
        exported = port(('body', 5, 'value', 'elt', 'target'))
        assert target(exported, 'WRITE').kind == 'ROOT_GLOBALS'
        # Independent key/scope oracle for the subtle generic annotation priority.
        native = original_native('class C:\n T=0\n def method[T](self,arg:T)->T:return T\n', '/oracle.py', 'exec')
        cls = next(row for row in native.children if row.type == _symtable.TYPE_CLASS)
        parameters = next(row for row in cls.children if row.type == _symtable.TYPE_TYPE_PARAMETERS)
        anno = next(row for row in parameters.children if row.type == _symtable.TYPE_ANNOTATION)
        fn = next(row for row in parameters.children if row.type == _symtable.TYPE_FUNCTION)
        assert (anno.symbols['T'] >> _symtable.SCOPE_OFF) & _symtable.SCOPE_MASK == _symtable.GLOBAL_IMPLICIT
        assert (fn.symbols['T'] >> _symtable.SCOPE_OFF) & _symtable.SCOPE_MASK == _symtable.FREE
        invalid = _inputs('def generic[T]():\n def leaf():\n  nonlocal T\n  return T\n return leaf\n')
        rejected = api.read_source_bindings(api.source_bindings_document(*invalid), *invalid)
        assert rejected.status == 'RESOLVED_WITH_CONFLICTS'
        invalid_syntax = decode(SourceSyntaxMaterial, invalid[2])
        invalid_roles = decode(SourceRolesMaterial, invalid[3])
        directive_site = _site(invalid_syntax, ('body', 0, 'body', 0, 'body', 0), 'names', (0,))
        directive = next(i for i, row in enumerate(invalid_roles.ports) if row.site == directive_site)
        assert rejected.ports[directive].conflicts
        shadow = _inputs('def generic[T]():\n T=0\n def leaf():\n  nonlocal T\n  return T\n return leaf\n')
        accepted = api.read_source_bindings(api.source_bindings_document(*shadow), *shadow)
        assert accepted.status == 'RESOLVED' and not accepted.conflicts
        shadow_contexts = decode(SourceContextsMaterial, shadow[4])
        shadow_syntax = decode(SourceSyntaxMaterial, shadow[2])
        shadow_roles = decode(SourceRolesMaterial, shadow[3])
        value_site = _site(shadow_syntax, ('body', 0, 'body', 1, 'body', 1, 'value'), 'id')
        value = next(accepted.ports[i] for i, row in enumerate(shadow_roles.ports) if row.site == value_site)
        binding = accepted.bindings[read_binding(value, accepted)]
        assert shadow_contexts.scopes[binding.owner].kind == 'FUNCTION' and binding.cell_required
        return

    if family == 'capture_and_implicit':
        write_only = port((*outer, 'body', 2, 'body', 1, 'targets', 0))
        assert write_only.read_plan is None and target(write_only, 'WRITE').kind == 'LEXICAL_BINDING'
        assert any(row.requester == write_only.source_scope and row.access == 'WRITE'
                   and write_only.port in row.ports for row in material.captures)
        assert material.bindings[target(write_only, 'WRITE').binding].cell_required
        hidden = port((*outer, 'body', 10, 'annotation', 'body'))
        assert hidden.activation == 'SUPPRESSED' and hidden.analysis_visibility == 'SYMBOL_VISIT'
        assert kinds(hidden) == ('ENV_GLOBALS', 'BUILTINS')
        super_port = port(('body', 7, 'body', 1, 'body', 0, 'value'))
        assert name(super_port.name) == 'super' and kinds(super_port) == ('LEXICAL_BINDING',)
        requirement = next(row for row in material.implicit if row.rule == 'SUPER_CLASS_REQUIREMENT' and super_port.port in row.cause_ports)
        assert name(requirement.name) == '__class__' and requirement.binding is not None
        protocol = material.bindings[requirement.binding]
        assert protocol.domain == 'CLASS_PROTOCOL' and protocol.cell_required
        prepared = port(('body', 7, 'body', 0, 'targets', 0))
        assert target(prepared, 'WRITE').kind == 'CLASS_PREPARED_MAPPING'
        assert material.resolutions[prepared.resolution].classification == 'CLASS_LOCAL'
        assert target(prepared, 'WRITE').binding is None
        assert requirement.read_plan is not None
        implicit_cell = material.interfaces[material.plans[requirement.read_plan].steps[0].interface]
        assert implicit_cell.kind == 'CLASS_PROTOCOL_CELL' and implicit_cell != target(prepared, 'WRITE')
        explicit = ('body', 7, 'body', 2, 'body', 0, 'value', 'elts')
        magic = [port((*explicit, index)) for index in range(3)]
        for row, symbol in zip(magic, ('__class__', '__classdict__', '__conditional_annotations__')):
            binding = material.bindings[read_binding(row)]
            assert binding.domain == 'CLASS_PROTOCOL' and name(binding.name) == symbol
        # A captured class-dict namespace is a separate protocol interface.
        anno = port((*outer, 'body', 7, 'body', 0, 'annotation'))
        mapping = material.interfaces[material.plans[anno.read_plan].steps[0].interface]
        assert mapping.kind == 'CLASS_ANNOTATION_NAMESPACE'
        assert mapping != target(prepared, 'WRITE')
        conditional = [row for row in material.implicit if row.rule == 'CONDITIONAL_ANNOTATION_REQUIREMENT']
        assert conditional
        for annotation in (('body', 7, 'body', 3, 'body', 0), ('body', 8)):
            occurrence = _occurrence(syntax, annotation)
            assert any(row.anchor is not None and row.anchor.occurrence == occurrence
                       and name(row.name) == '__conditional_annotations__' for row in conditional)
        for demand in material.implicit:
            assert demand.rule and all(type(index) is int and 0 <= index < len(roles.ports) for index in demand.cause_ports)
            if demand.anchor is not None:
                assert 0 <= demand.anchor.occurrence < len(syntax.nodes)
        for capture in material.captures:
            assert capture.binding < len(material.bindings) and capture.requester < len(contexts.scopes)
            assert all(0 <= index < len(roles.ports) for index in capture.ports)
            seen, hop = set(), capture.hop
            while hop is not None:
                assert hop not in seen
                seen.add(hop)
                relay = material.relays[hop]
                assert relay.binding == capture.binding
                hop = relay.parent
        # One shared annotation namespace must retain both original regions.
        from scar.analysis.source_context_view import SourceContextView
        for expressions in (('First', 'Second'), ('1', '2')):
            for future_prefix in ('', 'from __future__ import annotations\n'):
                source = future_prefix + 'class C:\n obj.attribute: ' + expressions[0] + '\n simple: ' + expressions[1] + '\n'
                tiny = _inputs(source)
                tiny_syntax = decode(SourceSyntaxMaterial, tiny[2])
                tiny_roles = decode(SourceRolesMaterial, tiny[3])
                tiny_contexts = decode(SourceContextsMaterial, tiny[4])
                tiny_declarations = decode(SourceDeclarationsMaterial, tiny[5])
                tiny_material = api.read_source_bindings(api.source_bindings_document(*tiny), *tiny)
                tiny_view = SourceContextView(tiny_syntax, tiny_roles, tiny_contexts)
                class_path = ('body', 1 if future_prefix else 0)
                requirements = []
                for statement in (0, 1):
                    anchor = _site(tiny_syntax, (*class_path, 'body', statement), 'annotation')
                    found = [row for row in tiny_material.implicit if row.rule == 'CLASS_ANNOTATION_PROTOCOL'
                             and row.anchor == anchor and name(row.name, tiny_declarations) == '__classdict__']
                    assert len(found) == 1
                    requirement = found[0]
                    assert requirement.region == tiny_view.resolve(anchor).state.region
                    requirements.append(requirement)
                assert requirements[0].region != requirements[1].region
                if future_prefix:
                    assert all(row.activation == 'TEMPLATE_ONLY' and row.analysis_visibility == 'DETACHED_FUTURE_ANNOTATION' for row in requirements)
                    assert all(row.binding is not None and not tiny_material.bindings[row.binding].cell_required for row in requirements)
                else:
                    assert [row.activation for row in requirements] == ['SUPPRESSED', 'ELIGIBLE']
                    assert all(row.analysis_visibility == 'SYMBOL_VISIT' for row in requirements)
        generic = _inputs('from __future__ import annotations\nclass C:\n def method[T: Bound](self): pass\n')
        generic_contexts = decode(SourceContextsMaterial, generic[4])
        generic_material = api.read_source_bindings(api.source_bindings_document(*generic), *generic)
        bound_requests = [row for row in generic_material.implicit if row.rule == 'CLASS_ANNOTATION_PROTOCOL'
                          and generic_contexts.regions[row.region].kind == 'TYPE_PARAMETER_BOUND']
        assert bound_requests and all(row.analysis_visibility == 'SYMBOL_VISIT' and row.activation == 'ELIGIBLE' for row in bound_requests)
        future = _inputs('from __future__ import annotations\ndef f():\n local:(lambda:hidden)\n')
        detached = api.read_source_bindings(api.source_bindings_document(*future), *future)
        assert any(row.disposition == 'DETACHED_TEMPLATE' and row.analysis_visibility == 'DETACHED_FUTURE_ANNOTATION' for row in detached.ports)
        assert len(material.ports) == len(roles.ports)
        assert all(row.port == index for index, row in enumerate(material.ports))
        return

    for limit in ('max_bindings', 'max_interfaces', 'max_plans', 'max_plan_steps', 'max_captures', 'max_relays', 'max_search_steps'):
        stopped = api.source_bindings_document(*inputs, **{limit: 0})
        assert stopped['status'] == 'BUDGET_STOPPED' and stopped['ports'] == [] and stopped['bindings'] == []
        assert api.read_source_bindings(stopped, *inputs).status == 'BUDGET_STOPPED'
    conflicting = _inputs('def invalid(parameter):\n global parameter\n return parameter\n')
    conflict = api.read_source_bindings(api.source_bindings_document(*conflicting), *conflicting)
    assert conflict.status == 'RESOLVED_WITH_CONFLICTS'
    original = decode(SourceDeclarationsMaterial, conflicting[5])
    involved = {port for row in original.conflicts for port in row.ports}
    assert involved and all(conflict.ports[index].conflicts for index in involved)
    stopped = api.source_bindings_document(*conflicting, max_conflicts=0)
    assert stopped['status'] == 'BUDGET_STOPPED'
    assert api.read_source_bindings(stopped, *conflicting).status == 'BUDGET_STOPPED'
    from scar.analysis.source_binding_view import SourceBindingView
    view = SourceBindingView(roles, contexts, declarations, material)
    view.verify()
    assert all(view.port(index) == row for index, row in enumerate(material.ports))
    assert len(material.scopes) == len(contexts.scopes)
    for plan in material.plans:
        assert plan.steps and all(row.on_hit == 'RETURN_VALUE' and row.on_exception == 'PROPAGATE' for row in plan.steps)
        assert all(row.on_miss == 'NEXT' for row in plan.steps[:-1])
        assert plan.steps[-1].on_miss == plan.missing_outcome
    for row in material.ports:
        assert row.resolution is None or 0 <= row.resolution < len(material.resolutions)
        assert row.declref is None or 0 <= row.declref < len(declarations.contributions)
    original_compile = builtins.compile
    def only_ast(source, filename, mode, flags=0, **kwargs):
        assert flags & ast.PyCF_ONLY_AST
        return original_compile(source, filename, mode, flags=flags, **kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(_symtable, 'symtable', forbidden)
        patch.setattr(builtins, 'compile', only_ast)
        assert api.read_source_bindings(api.source_bindings_document(*inputs), *inputs) == material
        for mode, source, root_kind in (
            ('eval', '(assigned := value)', 'ROOT_EVAL'),
            ('single', 'assigned = value\n', 'ROOT_INTERACTIVE'),
            ('func_type', '(int) -> str', 'TYPE_GRAMMAR')):
            tiny = _inputs(source, mode=mode)
            tiny_document = api.source_bindings_document(*tiny)
            tiny_material = api.read_source_bindings(json.loads(json.dumps(tiny_document)), *tiny)
            tiny_roles = decode(SourceRolesMaterial, tiny[3])
            tiny_contexts = decode(SourceContextsMaterial, tiny[4])
            assert tiny_material.status == 'RESOLVED' and tiny_material.runtime_binding == 'NOT_OBSERVED'
            assert tiny_contexts.scopes[0].kind == root_kind
            assert [row.port for row in tiny_material.ports] == list(range(len(tiny_roles.ports)))
            assert all(row.disposition == ('TYPE_GRAMMAR' if mode == 'func_type' else 'RESOLVED') for row in tiny_material.ports)
            if mode == 'func_type':
                assert not (tiny_material.bindings or tiny_material.interfaces or tiny_material.plans or tiny_material.captures or tiny_material.relays)
                assert all(row.read_plan is row.write_target is row.delete_target is None and row.activation == 'TYPE_GRAMMAR' for row in tiny_material.ports)
            else:
                writes = [row for row in tiny_material.ports if row.write_target is not None]
                assert len(writes) == 1 and tiny_material.interfaces[writes[0].write_target].kind == 'ROOT_LOCALS'
        upstream = _inputs('assigned = value\n', max_tokens=0)
        incomplete = api.source_bindings_document(*upstream)
        stopped = api.read_source_bindings(incomplete, *upstream)
        assert stopped.status == 'UPSTREAM_NOT_DECLARED'
        assert not (stopped.ports or stopped.bindings or stopped.interfaces or stopped.plans or stopped.captures)
    for route, replacement in (
        (('runtime_binding',), 'OBSERVED'), (('compiler_projection',), 'VERIFIED'),
        (('profile', 'projection_phase'), 'CODEGEN'), (('ports', 0, 'port'), True),
        (('interfaces', 0, 'owner'), 10**6), (('ports', 0, 'read_plan'), 10**6),
        (('captures', 0, 'binding'), 10**6), (('ports', 0, 'extra'), None), (('extra',), [])):
        changed = deepcopy(document)
        target_ = changed
        for part in route[:-1]:
            target_ = target_[part]
        target_[route[-1]] = replacement
        with pytest.raises((TypeError, ValueError)):
            api.read_source_bindings(changed, *inputs)
