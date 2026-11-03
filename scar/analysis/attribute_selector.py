"""Source-bound attribute selectors without evaluating a receiver or module.

Private-name mangling is lexical, including inside nested functions. A nested
class replaces that lexical class only in its body: decorators, bases and
keywords are evaluated in its enclosing context. Original source references
come from the caller's SG lookup; this helper creates no source atoms or IDs.
The local CPython compiler is used only as a static compiler, never executed.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass
import dis
import hashlib
import sys
from types import CodeType, MappingProxyType
from typing import Callable

from scar.analysis.static_compilation import StaticCodeEvidence
from scar.ir.program.attribute_lookups import SelectorResolution, StaticAttributeSelector
from scar.ir.v2.common import SourceReference
from scar.trace.code_snapshot import code_key


_MAX_SOURCE_BYTES = 4_000_000
_MAX_AST_NODES = 262144
_MAX_CODE_OBJECTS = 16384
_MAX_INSTRUCTIONS = 1_000_000
_CPYTHON_PRIVATE_RULE_VERSIONS = frozenset((3, minor) for minor in (11, 12, 13, 14))


def _span(node):
    values = (getattr(node, 'lineno', None), getattr(node, 'end_lineno', None),
              getattr(node, 'col_offset', None), getattr(node, 'end_col_offset', None))
    if any(type(value) is not int for value in values):
        raise ValueError('attribute selector requires exact original AST positions')
    return values


def _cpython_attribute_positions(node, position=None):
    """Original and CPython3.14.7 shortened attribute/codegen locations.

    codegen.c:update_start_location_to_match_attr uses the normalized AST
    identifier's Unicode length, even though AST columns are UTF-8 offsets.
    ``position`` also permits the same rule at an owning CALL location.
    """
    position = _span(node) if position is None else position
    positions = {position}
    if (sys.implementation.name == 'cpython' and sys.version_info[:3] == (3, 14, 7)
            and type(node) is ast.Attribute and position[0] != node.end_lineno):
        column = node.end_col_offset - len(node.attr)
        if column >= 0:
            start_line = node.end_lineno
            end_line = max(start_line, position[1])
            end_column = max(column, position[3]) if end_line == start_line else position[3]
            positions.add((start_line, end_line, column, end_column))
    return tuple(sorted(positions))


def _source_span(source):
    if source.end_column is None:
        raise ValueError('attribute selector source lacks its exact end column')
    return source.start_line, source.end_line, source.start_column, source.end_column


def _source_ref(value, node, source):
    if type(value) is not SourceReference:
        raise ValueError('source_for_node returned a non-SourceReference')
    value.__post_init__()
    if (value.path != source.path or value.fingerprint != source.fingerprint
            or _source_span(value) != _span(node)):
        raise ValueError('source_for_node differs from the original node/source snapshot')
    return value


@dataclass(frozen=True, slots=True)
class _AttributeInput:
    node: ast.Attribute
    owner: ast.ClassDef | None
    parent: ast.AST | None
    spelling: str
    span: tuple[int, int, int, int]
    context: type[ast.expr_context]
    owner_name: str | None
    owner_span: tuple[int, int, int, int] | None


def _owner_index(tree):
    """Index lexical ownership once for this original full-file AST."""
    pending = [(tree, None, None)]
    found = {}
    count = 0
    while pending:
        current, owner, parent = pending.pop()
        count += 1
        if count > _MAX_AST_NODES:
            raise OverflowError('ATTRIBUTE_SELECTOR_AST_BUDGET: lexical owner index exceeded its node budget')
        if type(current) is ast.Attribute:
            if id(current) in found:
                raise ValueError('attribute node has multiple ownership occurrences in the original AST')
            found[id(current)] = _AttributeInput(current, owner, parent, current.attr,
                _span(current), type(current.ctx), None if owner is None else owner.name,
                None if owner is None else _span(owner))
        if type(current) is ast.ClassDef:
            # A ClassDef header belongs to its enclosing code/class context.
            # The new class name controls private identifiers in its body.
            for field, value in ast.iter_fields(current):
                nested_owner = current if field == 'body' else owner
                # PEP 695 generic-class headers run in their generated
                # annotation scope, whose private-name context is cleared;
                # decorators still run in the enclosing class context.
                if getattr(current, 'type_params', ()) and field in ('type_params', 'bases', 'keywords'):
                    nested_owner = None
                children = value if type(value) is list else (value,)
                pending.extend((child, nested_owner, current) for child in children if isinstance(child, ast.AST))
        else:
            pending.extend((child, owner, current) for child in ast.iter_child_nodes(current))
    return MappingProxyType(found)


def _validate_ast(tree, text, path):
    original = ast.dump(tree, include_attributes=True)
    # PreparedSource and read-session ASTs differ in their type_comments flag.
    # Accept only a complete original parse under one of these two policies.
    for comments in (False, True):
        parsed = ast.parse(text, filename=path, type_comments=comments)
        if ast.dump(parsed, include_attributes=True) == original:
            return
    raise ValueError('attribute source AST differs from its retained text snapshot')


def _codes(root):
    pending, seen = [root], set()
    while pending:
        code = pending.pop()
        if id(code) in seen:
            continue
        seen.add(id(code))
        if len(seen) > _MAX_CODE_OBJECTS:
            raise OverflowError('ATTRIBUTE_SELECTOR_CODE_BUDGET: static compiler child-code budget exhausted')
        yield code
        pending.extend(child for child in code.co_consts if type(child) is CodeType)


class AttributeSelectorSource:
    """Owned immutable source facts and lazy no-exec compiler materials.

    Construct once per builder or once per fresh validation batch. This is an
    index over the retained source, never a cache of selector validity/PASS.
    Callers keep the original AST immutable during this input scope; selected
    node/class spelling and positions are checked again on each lookup.
    """
    __slots__ = ('source_tree', 'source_text', 'source_path', 'fingerprint',
        '_owners', '_root', '_code_paths', '_instruction_positions', '_compile_error')

    def __setattr__(self, name, value):
        raise AttributeError('selector source facts are immutable owned input records')

    def __init__(self, source_tree, source_text, source_path):
        if type(source_tree) is not ast.Module or type(source_text) is not str:
            raise TypeError('selector source facts require the original Module AST and retained text')
        if type(source_path) is not str or not source_path:
            raise TypeError('selector source facts require the original source path')
        raw = source_text.encode('utf-8')
        if len(raw) > _MAX_SOURCE_BYTES:
            raise OverflowError('ATTRIBUTE_SELECTOR_SOURCE_BYTE_BUDGET: retained source exceeds the bounded static selector profile')
        _validate_ast(source_tree, source_text, source_path)
        object.__setattr__(self, 'source_tree', source_tree)
        object.__setattr__(self, 'source_text', source_text)
        object.__setattr__(self, 'source_path', source_path)
        object.__setattr__(self, 'fingerprint', 'sha256:' + hashlib.sha256(raw).hexdigest())
        object.__setattr__(self, '_owners', _owner_index(source_tree))
        for name in ('_root', '_code_paths', '_instruction_positions', '_compile_error'):
            object.__setattr__(self, name, None)

    def original(self, node):
        fact = self._owners.get(id(node))
        if fact is None or fact.node is not node:
            raise ValueError('attribute node is not an original member of the selector source scope')
        if (node.attr != fact.spelling or _span(node) != fact.span or type(node.ctx) is not fact.context
                or fact.owner is not None and (fact.owner.name != fact.owner_name
                    or _span(fact.owner) != fact.owner_span)):
            raise ValueError('selected attribute/class AST fields changed after source indexing')
        return fact

    def _compile(self):
        if self._compile_error is not None:
            raise OverflowError(self._compile_error)
        if self._root is not None:
            return
        root = compile(self.source_text, self.source_path, 'exec', flags=0, dont_inherit=True, optimize=0)
        pending, paths, positions, instructions = [((), root)], {}, {}, 0
        try:
            while pending:
                path, code = pending.pop()
                if len(paths) >= _MAX_CODE_OBJECTS:
                    raise OverflowError('ATTRIBUTE_SELECTOR_CODE_BUDGET: static compiler child-code budget exhausted')
                paths[path] = code
                for instruction in dis.get_instructions(code, adaptive=False, show_caches=False):
                    instructions += 1
                    if instructions > _MAX_INSTRUCTIONS:
                        raise OverflowError('ATTRIBUTE_SELECTOR_INSTRUCTION_BUDGET: static instruction budget exhausted')
                    if instruction.opname in ('LOAD_ATTR', 'LOAD_METHOD', 'STORE_ATTR', 'DELETE_ATTR'):
                        positions.setdefault(tuple(instruction.positions), []).append((path, instruction))
                pending.extend(((*path, index), child) for index, child in enumerate(code.co_consts)
                    if type(child) is CodeType)
        except OverflowError as error:
            object.__setattr__(self, '_compile_error', str(error))
            raise
        object.__setattr__(self, '_root', root)
        object.__setattr__(self, '_code_paths', MappingProxyType(paths))
        object.__setattr__(self, '_instruction_positions', MappingProxyType({position: tuple(rows) for position, rows in positions.items()}))

    def compiler_instructions(self, node, evidence):
        self._compile()
        prefix = ()
        if evidence is not None:
            if code_key(self._root) != evidence.root_code_layout_key:
                raise ValueError('attribute compiler evidence root differs from a fresh original-source compilation')
            prefix = evidence.code_path
            selected = self._code_paths.get(prefix)
            if selected is None or code_key(selected) != evidence.code_layout_key:
                raise ValueError('attribute compiler evidence child path/layout differs from original-source compilation')
        operations = ({'LOAD_ATTR', 'LOAD_METHOD'} if type(node.ctx) is ast.Load
                      else {'STORE_ATTR'} if type(node.ctx) is ast.Store
                      else {'DELETE_ATTR'} if type(node.ctx) is ast.Del else set())
        found = {}
        for position in _cpython_attribute_positions(node):
            for path, instruction in self._instruction_positions.get(position, ()):
                if path[:len(prefix)] == prefix and instruction.opname in operations:
                    found[path, instruction.offset] = instruction
        return tuple(found.values())


def prepare_attribute_selector_source(source_tree: ast.Module, source_text: str,
        source_path: str) -> AttributeSelectorSource:
    """Create one source/owner index; reuse it within its immutable scope."""
    return AttributeSelectorSource(source_tree, source_text, source_path)


def _validate_mode(instructions, parent, selected, version):
    direct_call = type(parent) is ast.Call and parent.func is selected
    for instruction in instructions:
        if type(instruction.argval) is not str:
            raise ValueError('attribute compiler operand is not its original string selector')
        method = instruction.opname == 'LOAD_METHOD'
        if instruction.opname == 'LOAD_ATTR' and version >= (3, 12):
            if type(instruction.arg) is not int:
                raise ValueError('attribute compiler operand lost its name/method flags')
            method = bool(instruction.arg & 1)
        if method and not direct_call:
            raise ValueError('attribute compiler method mode contradicts its original AST call position')


def _probe_private_rule(class_name, spelling):
    """Check this local compiler's Unicode/long-name rule, not target code.

    The probe creates no program/source identity and is never executed. It is
    used only if optimization omitted the original unreachable attribute, so
    missing runtime instructions do not make a lexical language rule dynamic.
    """
    arguments = ast.arguments(posonlyargs=[], args=[ast.arg(arg='receiver')],
        kwonlyargs=[], kw_defaults=[], defaults=[], vararg=None, kwarg=None)
    function = ast.FunctionDef(name='_scar_selector_rule', args=arguments,
        body=[ast.Return(value=ast.Attribute(value=ast.Name(id='receiver', ctx=ast.Load()),
            attr=spelling, ctx=ast.Load()))], decorator_list=[], type_params=[])
    klass = ast.ClassDef(name=class_name, bases=[], keywords=[], body=[function],
        decorator_list=[], type_params=[])
    tree = ast.fix_missing_locations(ast.Module(body=[klass], type_ignores=[]))
    root = compile(tree, '<scar-static-private-name-rule>', 'exec', flags=0, dont_inherit=True, optimize=0)
    names = [instruction.argval for code in _codes(root)
        for instruction in dis.get_instructions(code, adaptive=False, show_caches=False)
        if instruction.opname in ('LOAD_ATTR', 'LOAD_METHOD')]
    if len(names) != 1 or type(names[0]) is not str:
        raise ValueError('local CPython private-name rule probe has no unique static selector')
    return names[0]


def derive_attribute_selector(node: ast.Attribute, *, source_tree: ast.Module,
        source: SourceReference, source_text: str | None = None,
        source_facts: AttributeSelectorSource | None = None,
        source_for_node: Callable[[ast.AST], SourceReference | None] | None = None,
        compiler_evidence: StaticCodeEvidence | None = None,
        on_unresolved: Callable[[str], None] | None = None) -> StaticAttributeSelector:
    """Resolve one original lookup name, preserving field-specific failures.

    ``source_for_node`` must be SCAR's original SG source-atom lookup, checking
    exact AST kind as well as span/hash. It must never evaluate target code.
    A supplied StaticCodeEvidence is checked against a fresh no-exec compile
    of the retained full text, its original root key and exact child path.
    No successful validation result is cached by this helper.
    """
    if type(node) is not ast.Attribute or type(source_tree) is not ast.Module:
        raise TypeError('attribute selector requires an original Attribute and full Module AST')
    if type(source) is not SourceReference:
        raise TypeError('attribute selector requires its original SourceReference')
    source.__post_init__()
    if type(node.attr) is not str or not node.attr or _span(node) != _source_span(source):
        raise ValueError('attribute spelling/source span differs from its original occurrence')
    if source_for_node is not None and not callable(source_for_node):
        raise TypeError('source_for_node must be the original SG lookup callback')
    if on_unresolved is not None and not callable(on_unresolved):
        raise TypeError('on_unresolved must be a diagnostic callback')
    lexical_source = None

    def unresolved(reason):
        selector = StaticAttributeSelector(node.attr, None, SelectorResolution.UNRESOLVED,
            lexical_class_source=lexical_source, unresolved_reason=reason)
        if on_unresolved is not None:
            on_unresolved(reason)
        return selector

    if source_facts is not None and type(source_facts) is not AttributeSelectorSource:
        raise TypeError('source_facts must be owned AttributeSelectorSource input facts')
    if source_text is None and source_facts is not None:
        source_text = source_facts.source_text
    if source_text is None:
        return unresolved('ATTRIBUTE_SELECTOR_SOURCE_TEXT_UNAVAILABLE: retained full-file text is required to verify the AST/source fingerprint')
    if type(source_text) is not str:
        raise TypeError('attribute source_text must be the retained decoded string')
    try:
        facts = source_facts or prepare_attribute_selector_source(source_tree, source_text, source.path)
        if (facts.source_tree is not source_tree or facts.source_text != source_text
                or facts.source_path != source.path or facts.fingerprint != source.fingerprint):
            raise ValueError('attribute source facts differ from the selected original AST/text/path/fingerprint')
        original_fact = facts.original(node)
        owner, parent = original_fact.owner, original_fact.parent
    except OverflowError as error:
        return unresolved(str(error))
    if source_for_node is not None:
        try:
            original = source_for_node(node)
        except KeyError:
            original = None
        if original is not None and _source_ref(original, node, source) != source:
            raise ValueError('attribute SG callback identifies another original source atom')
        if owner is not None:
            try:
                original = source_for_node(owner)
            except KeyError:
                original = None
            if original is not None:
                lexical_source = _source_ref(original, owner, source)
    private = node.attr.startswith('__') and not node.attr.endswith('__') and '.' not in node.attr
    class_prefix = owner.name.lstrip('_') if owner is not None else ''
    mangled = private and bool(class_prefix)
    expected = '_' + class_prefix + node.attr if mangled else node.attr
    if mangled and lexical_source is None:
        return unresolved('ATTRIBUTE_SELECTOR_LEXICAL_CLASS_SOURCE_UNAVAILABLE: the original lexical ClassDef source atom is required for this private-name mapping')
    # Ordinary selectors are a language-level source fact. Private-name rules
    # additionally depend on the supported compiler/lexical-class profile.
    needs_compiler = mangled or compiler_evidence is not None
    if needs_compiler:
        version = tuple(sys.version_info[:2])
        if sys.implementation.name != 'cpython' or version not in _CPYTHON_PRIVATE_RULE_VERSIONS:
            return unresolved('ATTRIBUTE_SELECTOR_COMPILER_PROFILE_UNSUPPORTED: static private-name/method-mode mapping is adapted only for CPython 3.11-3.14')
        if compiler_evidence is not None:
            if type(compiler_evidence) is not StaticCodeEvidence:
                raise TypeError('attribute compiler_evidence must be original StaticCodeEvidence')
            compiler_evidence.__post_init__()
            if (compiler_evidence.snapshot.path != source.path
                    or compiler_evidence.snapshot.fingerprint != source.fingerprint):
                raise ValueError('attribute compiler evidence belongs to another source snapshot')
            if (compiler_evidence.compiler_implementation != sys.implementation.name
                    or compiler_evidence.compiler_version != tuple(sys.version_info[:3])
                    or compiler_evidence.compiler_cache_tag != sys.implementation.cache_tag):
                return unresolved('ATTRIBUTE_SELECTOR_COMPILER_VERSION_MAPPING_UNSUPPORTED: supplied code profile differs from the local static compiler')
        try:
            instructions = facts.compiler_instructions(node, compiler_evidence)
            _validate_mode(instructions, parent, node, version)
            if instructions:
                if {instruction.argval for instruction in instructions} != {expected}:
                    raise ValueError('attribute lexical name rule contradicts original compiler selector operands')
            elif compiler_evidence is not None:
                return unresolved('ATTRIBUTE_SELECTOR_COMPILER_OPERATION_MAPPING_UNAVAILABLE: the supplied original code scope has no supported attribute opcode at this exact source position')
            elif mangled and _probe_private_rule(owner.name, node.attr) != expected:
                raise ValueError('attribute lexical private-name rule contradicts the local static compiler')
        except OverflowError as error:
            return unresolved(str(error))
    return StaticAttributeSelector(node.attr, expected,
        SelectorResolution.LEXICAL_MANGLED if mangled else SelectorResolution.AS_WRITTEN,
        lexical_class_source=lexical_source)


__all__ = ['AttributeSelectorSource', 'prepare_attribute_selector_source', 'derive_attribute_selector']
