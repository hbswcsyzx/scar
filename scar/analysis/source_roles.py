"""F3-B: a closed syntax field-role catalog and sparse original-slot ports.

These are syntax roles, not scope bindings or runtime read/write observations.
No symbol-table API, target execution or bytecode compilation is used.
"""
from __future__ import annotations

from functools import lru_cache
from hashlib import sha256
import json
from pathlib import Path

from scar.analysis.source_syntax import _schema_and_digests, read_source_syntax_material
from scar.ir.program.source_syntax import SourceSyntaxMaterial
from scar.ir.literals import LiteralKind
from scar.ir.program.source_roles import (
    FieldRule, RoleCatalog, RoleClassification, RoleConstructor, RoleFrontier,
    RolePort, RuleCount, SlotRef, SlotResolution, SourceRolesInput,
    SourceRolesMaterial, SourceRolesProfile,
)
from scar.ir.record_codec import decode, encode


_VERSION = 'PYTHON_SYNTAX_FIELD_ROLES_V1'
_SUPPORTED_SCHEMA = '8f5cd1f9759dfeb2b1ccaf1a10c4483bad994b674241557e1cdd464be1c4831a'
_CARRIERS = {}
for _constructor in ('FunctionDef', 'AsyncFunctionDef'):
    _CARRIERS[_constructor, 'name'] = ('FUNCTION_BINDING_SYNTAX', 'DIRECT', True)
_CARRIERS['ClassDef', 'name'] = ('CLASS_BINDING_SYNTAX', 'DIRECT', True)
_CARRIERS['Name', 'id'] = ('LEXICAL_NAME_SYNTAX', 'NAME_CONTEXT', True)
for _constructor, _role in (('Global', 'GLOBAL_DECLARATION_SYNTAX'), ('Nonlocal', 'NONLOCAL_DECLARATION_SYNTAX')):
    _CARRIERS[_constructor, 'names'] = (_role, 'DIRECT', True)
for _constructor, _name, _role, _selector in (
    ('ExceptHandler', 'name', 'EXCEPTION_BINDING_SYNTAX', 'OPTIONAL_BINDER'),
    ('arg', 'arg', 'PARAMETER_BINDING_SYNTAX', 'DIRECT'),
    ('alias', 'name', 'IMPORT_SPECIFICATION_SYNTAX', 'IMPORT_NAME'),
    ('alias', 'asname', 'IMPORT_ALIAS_SYNTAX', 'IMPORT_ALIAS'),
    ('MatchMapping', 'rest', 'PATTERN_MAPPING_BINDING_SYNTAX', 'OPTIONAL_BINDER'),
    ('MatchStar', 'name', 'PATTERN_STAR_BINDING_SYNTAX', 'OPTIONAL_BINDER'),
    ('MatchAs', 'name', 'PATTERN_AS_BINDING_SYNTAX', 'OPTIONAL_BINDER'),
    ('Attribute', 'attr', 'ATTRIBUTE_LABEL', 'ATTRIBUTE_CONTEXT'),
    ('keyword', 'arg', 'KEYWORD_LABEL', 'KEYWORD'),
    ('MatchClass', 'kwd_attrs', 'PATTERN_ATTRIBUTE_LABEL', 'DIRECT'),
    ('ImportFrom', 'module', 'IMPORT_FROM_MODULE_SPEC', 'MODULE_SPEC')):
    _CARRIERS[_constructor, _name] = (_role, _selector, True)
for _constructor in ('TypeVar', 'ParamSpec', 'TypeVarTuple'):
    _CARRIERS[_constructor, 'name'] = ('TYPE_PARAMETER_BINDING_SYNTAX', 'DIRECT', True)
for _constructor in ('FunctionDef', 'AsyncFunctionDef', 'Assign', 'For', 'AsyncFor', 'With', 'AsyncWith', 'arg'):
    _CARRIERS[_constructor, 'type_comment'] = ('TYPE_COMMENT_TEXT', 'DIRECT', False)
_CARRIERS.update({('Constant', 'value'): ('LITERAL_PAYLOAD', 'DIRECT', False),
    ('Constant', 'kind'): ('LITERAL_KIND', 'DIRECT', False),
    ('Interpolation', 'str'): ('INTERPOLATION_SOURCE_TEXT', 'DIRECT', False),
    ('MatchSingleton', 'value'): ('PATTERN_SINGLETON_VALUE', 'DIRECT', False),
    ('TypeIgnore', 'tag'): ('TYPE_IGNORE_TEXT', 'DIRECT', False)})
_INTEGER_ROLES = {('AnnAssign', 'simple'): 'ANNOTATION_TARGET_FORM_FLAG',
    ('ImportFrom', 'level'): 'RELATIVE_IMPORT_DEPTH',
    ('FormattedValue', 'conversion'): 'FORMAT_CONVERSION_CODE',
    ('Interpolation', 'conversion'): 'FORMAT_CONVERSION_CODE',
    ('comprehension', 'is_async'): 'ASYNC_COMPREHENSION_FLAG', ('TypeIgnore', 'lineno'): 'TYPE_IGNORE_LINE'}
_FAMILIES = {'stmt', 'type_ignore', 'expr', 'arguments', 'type_param', 'keyword', 'operator',
    'withitem', 'match_case', 'excepthandler', 'alias', 'boolop', 'unaryop', 'comprehension',
    'cmpop', 'expr_context', 'arg', 'pattern'}
_POSITIONS = {'lineno': 'SOURCE_START_LINE', 'col_offset': 'SOURCE_START_UTF8_COLUMN',
    'end_lineno': 'SOURCE_END_LINE', 'end_col_offset': 'SOURCE_END_UTF8_COLUMN'}


def _digest(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode('ascii')).hexdigest()


def _shape(kind):
    if kind.kind == 'LIST':
        nested = kind.items[0]
        return ('LIST_NODE' if nested.kind == 'AST_CLASS' else 'LIST_SCALAR'), nested.name
    if kind.kind == 'UNION':
        nested = next(item for item in kind.items if item.name != 'NoneType')
        return ('OPTIONAL_NODE' if nested.kind == 'AST_CLASS' else 'OPTIONAL_SCALAR'), nested.name
    return ('NODE' if kind.kind == 'AST_CLASS' else 'SCALAR'), kind.name


@lru_cache(maxsize=1)
def _catalog():
    schema = _schema_and_digests()[0]
    schema_sha = _digest(encode(schema))
    if schema_sha != _SUPPORTED_SCHEMA:
        raise ValueError('official AST schema is not covered by the reviewed field-role catalog')
    rules, constructors, carriers, integers = [], [], set(), set()
    for cls in schema:
        if cls.abstract:
            continue
        groups = []
        for group, names in (('FIELD', cls.fields), ('ATTRIBUTE', cls.attributes)):
            indices = []
            for ordinal, name in enumerate(names):
                key = cls.name, name
                if group == 'ATTRIBUTE':
                    shape, family, role, selector, sparse = 'ATTRIBUTE', 'int', _POSITIONS[name], 'DIRECT', False
                else:
                    shape, family = _shape(cls.field_types[ordinal].type)
                    if key in _CARRIERS:
                        carriers.add(key)
                        role, selector, sparse = _CARRIERS[key]
                    elif key in _INTEGER_ROLES:
                        integers.add(key)
                        role, selector, sparse = _INTEGER_ROLES[key], 'DIRECT', False
                    elif family in _FAMILIES and shape in ('NODE', 'OPTIONAL_NODE', 'LIST_NODE'):
                        role, selector, sparse = 'SYNTAX_CHILD_' + family.upper(), 'DIRECT', False
                    else:
                        raise ValueError('official AST field has no reviewed role rule: ' + str(key))
                indices.append(len(rules))
                rules.append(FieldRule(len(rules), cls.name, group, ordinal, name, shape, family, role, selector, sparse))
            groups.append(tuple(indices))
        constructors.append(RoleConstructor(cls.name, groups[0], groups[1]))
    if len(constructors) != 113 or len(rules) != 484 or carriers != set(_CARRIERS) or integers != set(_INTEGER_ROLES):
        raise ValueError('field-role catalog coverage differs from its reviewed schema')
    payload = dict(rule_version=_VERSION, f2_schema_sha256=schema_sha,
        constructors=encode(tuple(constructors)), rules=encode(tuple(rules)),
        schema='scar.source-role-catalog', schema_version=1)
    return RoleCatalog(_VERSION, schema_sha, _digest(payload), tuple(constructors), tuple(rules))


def source_role_catalog() -> dict:
    return encode(_catalog())


def _state(value):
    if value.kind == 'ABSENT':
        return 'ABSENT'
    if value.kind == 'SCALAR' and value.scalar.kind is LiteralKind.NONE:
        return 'NONE'
    if value.kind == 'LIST' and not value.items:
        return 'EMPTY_LIST'
    return 'VALUES'


class SyntaxRoleView:
    """Explicit reusable view; one parent index serves any number of queries."""
    def __init__(self, syntax):
        if type(syntax) is not SourceSyntaxMaterial or syntax.status != 'PARSED':
            raise ValueError('role queries require a typed PARSED F2 material')
        self.syntax, self.catalog = syntax, _catalog()
        if _digest(encode(syntax.profile.ast_schema)) != self.catalog.f2_schema_sha256:
            raise ValueError('F2 schema differs from the role catalog')
        self.constructors = {c.name: c for c in self.catalog.constructors}
        self.parents = {}
        self.fields = {c.name: {self.catalog.rules[i].name: self.catalog.rules[i].ordinal
            for i in c.fields} for c in self.catalog.constructors}
        for occurrence, node in enumerate(syntax.nodes):
            cls = self.constructors.get(node.constructor)
            if cls is None or len(node.fields) != len(cls.fields) or len(node.attributes) != len(cls.attributes):
                raise ValueError('F2 occurrence field layout is not covered by the catalog')
            for group, values in (('FIELD', node.fields), ('ATTRIBUTE', node.attributes)):
                for ordinal, value in enumerate(values):
                    stack = [(value, ())]
                    while stack:
                        item, path = stack.pop()
                        if item.kind == 'NODE':
                            ref = item.reference
                            if ref >= len(syntax.nodes) or ref in self.parents:
                                raise ValueError('F2 occurrence has an invalid or duplicate parent')
                            self.parents[ref] = SlotRef(occurrence, group, ordinal, path)
                        elif item.kind == 'LIST':
                            stack.extend((child, path + (i,)) for i, child in enumerate(item.items))

    def field(self, occurrence, name):
        node = self.syntax.nodes[occurrence]
        return node.fields[self.fields[node.constructor][name]]

    def locate(self, site):
        if type(site) is not SlotRef:
            raise TypeError('role query requires a typed F2 SlotRef')
        site.__post_init__()
        if site.occurrence >= len(self.syntax.nodes):
            raise ValueError('role query occurrence is outside F2')
        node = self.syntax.nodes[site.occurrence]
        cls = self.constructors[node.constructor]
        values, rules = (node.fields, cls.fields) if site.group == 'FIELD' else (node.attributes, cls.attributes)
        if site.ordinal >= len(values):
            raise ValueError('role query ordinal is outside its F2 field group')
        value = values[site.ordinal]
        for i in site.item_path:
            if value.kind != 'LIST' or i >= len(value.items):
                raise ValueError('role item path is not an original F2 list item')
            value = value.items[i]
        return self.catalog.rules[rules[site.ordinal]], value

    def parent(self, occurrence):
        site = self.parents.get(occurrence)
        if site is None:
            return None, None, None
        rule, _ = self.locate(site)
        return site.occurrence, self.syntax.nodes[site.occurrence].constructor, rule.name

    def context(self, occurrence):
        value = self.field(occurrence, 'ctx')
        if value.kind != 'NODE':
            raise ValueError('context-dependent name role requires its explicit F2 ctx')
        context = self.syntax.nodes[value.reference].constructor
        if context not in ('Load', 'Store', 'Del'):
            raise ValueError('unreviewed expression context')
        return context

    def resolve(self, site):
        rule, value = self.locate(site)
        state, role, owner, qualifiers = _state(value), rule.role, None, []
        projection = 'IDENTITY' if value.kind == 'SCALAR' and state != 'NONE' else 'NO_VALUE'
        if state == 'NONE' and (rule.constructor, rule.name) in (('Constant', 'value'), ('MatchSingleton', 'value')):
            projection = 'IDENTITY'
            qualifiers.append('LITERAL_NONE_VALUE')
        if value.kind == 'LIST':
            qualifiers.append('LIST_CONTAINER')
        if site.item_path and state == 'NONE':
            if (rule.constructor, rule.name) == ('Dict', 'keys'):
                role = 'DICT_UNPACK_KEY_MARKER'
            elif (rule.constructor, rule.name) == ('arguments', 'kw_defaults'):
                role = 'REQUIRED_KWONLY_DEFAULT_MARKER'
        if state in ('ABSENT', 'EMPTY_LIST') or value.kind == 'LIST':
            return SlotResolution(site, rule.rule, state, role, tuple(qualifiers), projection, None)
        parent, parent_kind, parent_field = self.parent(site.occurrence)
        if rule.selector == 'NAME_CONTEXT':
            context = self.context(site.occurrence)
            role = {'Load': 'REFERENCE_SYNTAX', 'Store': 'BINDING_SYNTAX', 'Del': 'DELETION_SYNTAX'}[context]
            if (parent_kind, parent_field) == ('AugAssign', 'target'):
                if context != 'Store':
                    raise ValueError('AugAssign target context is not Store')
                role, owner = 'AUGMENTED_BINDING_SYNTAX', parent
                qualifiers.append('AUGMENTED_TARGET')
            elif (parent_kind, parent_field) == ('AnnAssign', 'target'):
                if context != 'Store':
                    raise ValueError('AnnAssign target context is not Store')
                state_value = _state(self.field(parent, 'value'))
                if state_value == 'ABSENT':
                    raise ValueError('AnnAssign target role requires explicit value presence')
                role = 'DECLARATION_ONLY' if state_value == 'NONE' else 'BINDING_SYNTAX'
                owner = parent
                simple = self.field(parent, 'simple')
                if simple.kind != 'SCALAR' or type(simple.scalar.to_python()) is not int:
                    raise ValueError('AnnAssign target role requires its simple flag')
                qualifiers.append('ANNASSIGN_SIMPLE' if simple.scalar.to_python() == 1 else 'ANNASSIGN_NON_SIMPLE')
            elif (parent_kind, parent_field) in (('NamedExpr', 'target'), ('TypeAlias', 'name')):
                if context != 'Store':
                    raise ValueError('declaration target context is not Store')
                role = 'NAMED_EXPR_BINDING_SYNTAX' if parent_kind == 'NamedExpr' else 'TYPE_ALIAS_BINDING_SYNTAX'
                owner = parent
        elif rule.selector == 'ATTRIBUTE_CONTEXT':
            qualifiers.append('CONTEXT_' + self.context(site.occurrence).upper())
            if (parent_kind, parent_field) == ('AugAssign', 'target'):
                qualifiers.append('AUGMENTED_TARGET');owner = parent
            elif (parent_kind, parent_field) == ('AnnAssign', 'target'):
                state_value = _state(self.field(parent, 'value'))
                if state_value == 'ABSENT':
                    raise ValueError('attribute annotation role requires explicit value presence')
                qualifiers.append('DECLARATION_ONLY' if state_value == 'NONE' else 'ANNOTATED_ASSIGNMENT');owner = parent
        elif rule.selector in ('IMPORT_NAME', 'IMPORT_ALIAS'):
            if (parent_kind, parent_field) not in (('Import', 'names'), ('ImportFrom', 'names')):
                raise ValueError('import carrier role requires its original Import/ImportFrom owner')
            owner = parent
            if rule.selector == 'IMPORT_ALIAS':
                role = 'NO_IMPORT_ALIAS' if state == 'NONE' else 'IMPORT_BINDING_SYNTAX'
            elif state != 'NONE':
                name = value.scalar.to_python()
                role = 'IMPORT_MODULE_SPEC' if parent_kind == 'Import' else ('IMPORT_WILDCARD_SPEC' if name == '*' else 'IMPORT_MEMBER_SPEC')
        elif rule.selector == 'KEYWORD' and state == 'NONE':
            role = 'KEYWORD_UNPACK_MARKER'
        elif rule.selector == 'MODULE_SPEC' and state == 'NONE':
            role = 'RELATIVE_MODULE_MARKER'
        elif rule.selector == 'OPTIONAL_BINDER' and state == 'NONE':
            role = {'ExceptHandler': 'NO_EXCEPTION_BINDING', 'MatchMapping': 'NO_PATTERN_REST',
                'MatchStar': 'PATTERN_WILDCARD', 'MatchAs': 'PATTERN_WILDCARD'}[rule.constructor]
        return SlotResolution(site, rule.rule, state, role, tuple(qualifiers), projection, owner)

    def ports(self, site):
        result = self.resolve(site)
        ports = [RolePort(result.site, result.rule, result.role, result.projection, result.context_owner, result.qualifiers)]
        rule = self.catalog.rules[result.rule]
        if rule.selector == 'IMPORT_NAME' and result.state == 'VALUES':
            alias = self.field(site.occurrence, 'asname')
            if _state(alias) == 'NONE' and result.role != 'IMPORT_WILDCARD_SPEC':
                projection = 'IMPORT_HEAD' if result.role == 'IMPORT_MODULE_SPEC' else 'IDENTITY'
                ports.append(RolePort(site, result.rule, 'IMPORT_BINDING_SYNTAX', projection,
                    result.context_owner, ('DERIVED_IMPORT_BINDER',)))
        return ports


def role_at_slot(syntax_material, slot_ref) -> SlotResolution:
    """Resolve a slot; pass a SyntaxRoleView for repeated constant-time queries."""
    view = syntax_material if type(syntax_material) is SyntaxRoleView else SyntaxRoleView(syntax_material)
    return view.resolve(slot_ref)


def _zero_counts():
    return tuple(RuleCount(i, 0, 0, 0, 0, 0, 0, 0) for i in range(len(_catalog().rules)))


def classify_syntax_roles(material, *, max_ports=1_000_000, max_slots=10_000_000) -> RoleClassification:
    """Pure typed-table adapter; synthetic callers do not obtain source proof."""
    if any(type(n) is not int or n < 0 for n in (max_ports, max_slots)):
        raise ValueError('role budgets must be exact nonnegative integers')
    if type(material) is not SourceSyntaxMaterial:
        raise TypeError('role classification requires a typed F2 material')
    if material.status != 'PARSED':
        return RoleClassification('UPSTREAM_NOT_PARSED', (), _zero_counts(), 0, 0, ())
    index = SyntaxRoleView(material)
    counts = [[0] * 7 for _ in index.catalog.rules]
    ports, slots, list_items = [], 0, 0

    def stopped(code, site):
        frontier = RoleFrontier(code, site, slots, len(ports), 'classification budget reached; no partial roles published')
        return RoleClassification('BUDGET_STOPPED', (), _zero_counts(), 0, 0, (frontier,))

    for occurrence, node in enumerate(material.nodes):
        for group, values in (('FIELD', node.fields), ('ATTRIBUTE', node.attributes)):
            for ordinal, value in enumerate(values):
                site = SlotRef(occurrence, group, ordinal)
                if slots >= max_slots:
                    return stopped('SLOT_BUDGET', site)
                rule, _ = index.locate(site)
                row = counts[rule.rule]
                row[0] += 1;slots += 1
                row[{'ABSENT': 1, 'NONE': 2, 'EMPTY_LIST': 3, 'VALUES': 4}[_state(value)]] += 1
                if value.kind == 'LIST':
                    row[5] += len(value.items);list_items += len(value.items)
                if not rule.sparse:
                    continue
                sites = (SlotRef(occurrence, group, ordinal, (i,)) for i in range(len(value.items))) if value.kind == 'LIST' and value.items else (site,)
                for leaf in sites:
                    emitted = index.ports(leaf)
                    if len(ports) + len(emitted) > max_ports:
                        return stopped('PORT_BUDGET', leaf)
                    ports.extend(emitted);row[6] += len(emitted)
    result_counts = tuple(RuleCount(i, *row) for i, row in enumerate(counts))
    return RoleClassification('CLASSIFIED', tuple(ports), result_counts, slots, list_items, ())


def _profile():
    catalog = _catalog()
    return SourceRolesProfile(_VERSION, catalog.f2_schema_sha256, catalog.content_sha256,
        sha256(Path(__file__).read_bytes()).hexdigest())


def _produce(f0, f1, f2, max_ports, max_slots):
    if any(type(n) is not int or n < 0 for n in (max_ports, max_slots)):
        raise ValueError('role budgets must be exact nonnegative integers')
    syntax = read_source_syntax_material(f2, f0, f1)
    result = classify_syntax_roles(syntax, max_ports=max_ports, max_slots=max_slots)
    inputs = SourceRolesInput(_digest(f0), _digest(f1), _digest(f2), f0['path'], syntax.mode, syntax.status)
    return SourceRolesMaterial(inputs, _profile(), max_ports, max_slots, result.status,
        result.ports, result.counts, result.slots, result.list_items, result.frontiers)


def source_roles_document(f0, f1, f2, *, max_ports=1_000_000, max_slots=10_000_000) -> dict:
    return encode(_produce(f0, f1, f2, max_ports, max_slots))


def read_source_roles(document, f0, f1, f2) -> SourceRolesMaterial:
    material = decode(SourceRolesMaterial, document)
    if material.profile != _profile():
        raise ValueError('field-role implementation/catalog profile mismatch')
    fresh = _produce(f0, f1, f2, material.max_ports, material.max_slots)
    if material != fresh:
        raise ValueError('role ports/counters differ from original F2 slots and the reviewed catalog')
    return material


__all__ = ['source_role_catalog', 'source_roles_document', 'read_source_roles',
    'role_at_slot', 'SyntaxRoleView', 'classify_syntax_roles']
