"""C3-T source/compiler topology queries; symbol origins remain unprojected."""
from hashlib import sha256
import json

from scar.ir.program.compiler_topology import CompilerTopologyMaterial
from scar.ir.program.source_contexts import SourceContextsMaterial
from scar.ir.program.source_roles import SourceRolesMaterial
from scar.ir.program.source_symbols import SourceSymbolsMaterial
from scar.ir.record_codec import encode


def _digest(document):
    return sha256(json.dumps(document, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode('ascii')).hexdigest()


def _index(index, size, label):
    if type(index) is not int or not 0 <= index < size:
        raise ValueError('C3-T ' + label + ' is outside its original table')
    return index


_SOURCE_ROLES = {
    'ROOT': 'ROOT', 'FUNCTION_BODY': 'FUNCTION_BODY', 'CLASS_BODY': 'CLASS_BODY',
    'LAMBDA_BODY': 'LAMBDA_BODY', 'TYPE_PARAMETERS': 'TYPE_PARAMETERS',
    'HEADER_ANNOTATIONS': 'HEADER_ANNOTATIONS', 'VARIABLE_ANNOTATIONS': 'VARIABLE_ANNOTATIONS',
    'TYPE_ALIAS_VALUE': 'TYPE_ALIAS', 'TYPE_PARAMETER_BOUND': 'TYPE_PARAMETER_BOUND',
    'TYPE_PARAMETER_DEFAULT': 'TYPE_PARAMETER_DEFAULT', 'COMPREHENSION': 'COMPREHENSION',
    'GENERATOR_EXPRESSION': 'GENERATOR_EXPRESSION',
}
_ORIGIN_CONSTRUCTORS = {
    'ROOT': ('Module', 'Interactive', 'Expression'),
    'FUNCTION_BODY': ('FunctionDef', 'AsyncFunctionDef'), 'CLASS_BODY': ('ClassDef',),
    'LAMBDA_BODY': ('Lambda',), 'TYPE_PARAMETERS': ('FunctionDef', 'AsyncFunctionDef', 'ClassDef', 'TypeAlias'),
    'HEADER_ANNOTATIONS': ('FunctionDef', 'AsyncFunctionDef'),
    'VARIABLE_ANNOTATIONS': ('Module', 'Interactive', 'FunctionDef', 'AsyncFunctionDef', 'ClassDef'),
    'TYPE_ALIAS': ('TypeAlias',), 'TYPE_PARAMETER_BOUND': ('TypeVar',),
    'TYPE_PARAMETER_DEFAULT': ('TypeVar', 'ParamSpec', 'TypeVarTuple'),
    'COMPREHENSION': ('ListComp', 'SetComp', 'DictComp'),
    'GENERATOR_EXPRESSION': ('GeneratorExp',),
}


class CompilerTopologyView:
    """Queries retain C1 scope/region IDs and original F3-A public row IDs."""

    def __init__(self, roles, c1, native, material, *, contexts=None):
        from scar.analysis.compiler_topology import _catalog
        if (type(roles) is not SourceRolesMaterial or roles.status != 'CLASSIFIED'
                or type(c1) is not SourceContextsMaterial or c1.status != 'CONTEXTUALIZED'
                or type(native) is not SourceSymbolsMaterial
                or type(material) is not CompilerTopologyMaterial
                or material.status not in ('PROJECTED', 'SOURCE_ONLY_MODE')):
            raise ValueError('C3-T queries require typed complete source/topology inputs')
        self.roles, self.contexts, self.native, self.material = roles, c1, native, material
        self.context_view, self.catalog = contexts, _catalog()
        basis = material.input
        if (basis.source_scope_count != len(c1.scopes) or basis.native_scope_count != len(native.scopes)
                or basis.c1_status != c1.status or basis.f3a_status != native.status
                or basis.f3b_document_sha256 != _digest(encode(roles))
                or basis.c1_document_sha256 != _digest(encode(c1))
                or basis.f3a_document_sha256 != _digest(encode(native))
                or any(getattr(basis, field) != getattr(native.input, field)
                    or getattr(basis, field) != getattr(c1.input, field)
                    for field in ('f0_document_sha256', 'f1_document_sha256', 'f2_document_sha256', 'path'))
                or basis.mode != native.mode or basis.mode != c1.input.mode
                or material.profile.native_profile_sha256 != _digest(encode(native.profile))
                or material.profile.topology_catalog_sha256 != self.catalog.content_sha256
                or material.profile.context_catalog_sha256 != c1.profile.context_catalog_sha256
                or material.profile.f2_schema_sha256 != c1.profile.f2_schema_sha256):
            raise ValueError('C3-T source/compiler receipts or versioned catalogs differ')
        if contexts is not None and (contexts.roles != roles or contexts.material != c1):
            raise ValueError('C3-T source context view belongs to another source unit')
        self._owners = {}
        for index, scope in enumerate(c1.scopes):
            if scope.owner in self._owners:
                raise ValueError('C3-T requires a unique source environment per typed C1 owner')
            self._owners[scope.owner] = index

    def block(self, index):
        return self.material.blocks[_index(index, len(self.material.blocks), 'compiler block reference')]

    def scope(self, index):
        return self.material.scopes[_index(index, len(self.material.scopes), 'source scope reference')]

    def region(self, index):
        from scar.ir.program.source_contexts import OwnerRef
        region = self.contexts.regions[_index(index, len(self.contexts.regions), 'source region reference')]
        owner = region.owner
        if owner.kind == 'FORMAL_INTERFACE':
            # A function's parameter interface belongs to its body environment,
            # although the containing arguments slot is evaluated by its creator.
            candidates = [self._owners[key] for kind in ('FUNCTION_BODY', 'LAMBDA_BODY')
                if (key := OwnerRef(owner.occurrence, kind)) in self._owners]
            if len(candidates) != 1:
                raise ValueError('C3-T formal region lacks its unique source function/lambda body')
            scope = candidates[0]
        else:
            if owner not in self._owners:
                raise ValueError('C3-T region has no original source owner environment')
            scope = self._owners[owner]
        return self.scope(scope)

    def port(self, index):
        _index(index, len(self.roles.ports), 'source port reference')
        if self.context_view is None:
            raise ValueError('C3-T port queries require the original SourceContextView')
        return self.scope(self.context_view.context_for_port(index).state.environment)

    def _empty_header(self, occurrence):
        fields = self.context_view.role_view
        if fields.field(occurrence, 'returns').kind == 'NODE':
            return False
        arguments = fields.field(occurrence, 'args').reference
        args = []
        for name in ('posonlyargs', 'args', 'kwonlyargs'):
            args.extend(item.reference for item in fields.field(arguments, name).items)
        for name in ('vararg', 'kwarg'):
            value = fields.field(arguments, name)
            if value.kind == 'NODE':
                args.append(value.reference)
        return all(fields.field(arg, 'annotation').kind != 'NODE' for arg in args)

    def verify(self):
        from scar.analysis.compiler_topology import _projection_children
        data = self.material
        if tuple(row.scope for row in data.scopes) != tuple(range(len(self.contexts.scopes))):
            raise ValueError('C3-T source scope projection does not preserve every original ordinal')
        if data.status == 'SOURCE_ONLY_MODE':
            if data.input.mode != 'func_type' or self.native.status != 'UNSUPPORTED_SYMTABLE_MODE':
                raise ValueError('C3-T grammar-only projection has a different official compiler boundary')
            for index in range(len(self.contexts.regions)):
                self.region(index)
            return dict(blocks=0, scopes=len(data.scopes), regions=len(self.contexts.regions),
                public_blocks=0, public_edges=0, rewrites=0)
        if self.native.status != 'CAPTURED' or not data.blocks:
            raise ValueError('C3-T public projection requires a captured official scope graph')
        if data.blocks[0].parent is not None or data.blocks[0].origin.role != 'ROOT':
            raise ValueError('C3-T original compiler construction graph has a different root')
        origins, child_refs, public_refs, expected_rewrites = set(), [[] for _ in data.blocks], {}, set()
        detached = [False] * len(data.blocks)
        for index, block in enumerate(data.blocks):
            origin = block.origin
            key = origin.occurrence, origin.role
            if key in origins or origin.role not in self.catalog.origin_roles:
                raise ValueError('C3-T compiler origin is duplicated or has an undeclared role')
            origins.add(key)
            if self.context_view is not None:
                syntax = self.context_view.syntax
                _index(origin.occurrence, len(syntax.nodes), 'source occurrence')
                if syntax.nodes[origin.occurrence].constructor not in _ORIGIN_CONSTRUCTORS[origin.role]:
                    raise ValueError('C3-T compiler origin role does not match its original F2 constructor')
            if (block.attachment not in self.catalog.attachments or block.projection not in self.catalog.projections
                    or type(block.can_see_class_scope) is not bool):
                raise ValueError('C3-T compiler block has an undeclared attachment/projection policy')
            if index:
                _index(block.parent, index, 'previously created compiler parent')
            elif block.attachment != 'DIRECT' or block.projection != 'PUBLIC':
                raise ValueError('C3-T public root cannot be detached or inlined')
            if block.parent is not None:
                detached[index] = detached[block.parent]
            if block.attachment == 'FUTURE_DETACHED':
                if origin.role not in ('HEADER_ANNOTATIONS', 'VARIABLE_ANNOTATIONS'):
                    raise ValueError('C3-T future detachment requires an annotation origin')
                detached[index] = True
                expected = 'FUTURE_DETACHED'
                expected_rewrites.add(('FUTURE_DETACH', index, block.parent))
            elif detached[index]:
                expected = 'DETACHED_DESCENDANT'
            elif origin.role == 'COMPREHENSION' and not self.block(block.parent).can_see_class_scope:
                expected = 'INLINED'
                expected_rewrites.add(('INLINE_COMPREHENSION', index, block.parent))
            else:
                expected = 'PUBLIC'
            if block.projection != expected:
                raise ValueError('C3-T projection ignores the original reachable-parent/annotation rule')
            if block.projection == 'PUBLIC':
                native = _index(block.public_scope, len(self.native.scopes), 'original public compiler row')
                if native in public_refs:
                    raise ValueError('C3-T public row has multiple compiler-template identities')
                public_refs[native] = index
            elif block.public_scope is not None:
                raise ValueError('C3-T elided compiler template cannot claim an observed public row')
            if len(set(block.children)) != len(block.children):
                raise ValueError('C3-T original child attachment is duplicated')
            for child in block.children:
                _index(child, len(data.blocks), 'compiler child')
                if child <= index or self.block(child).parent != index or self.block(child).attachment != 'DIRECT':
                    raise ValueError('C3-T child was not attached to its original construction parent')
                child_refs[child].append(index)
            if block.source_scope is None:
                if origin.role != 'HEADER_ANNOTATIONS' or (self.context_view is not None and not self._empty_header(origin.occurrence)):
                    raise ValueError('C3-T source-less compiler block lacks an empty header origin')
            else:
                source = self.contexts.scopes[_index(block.source_scope, len(self.contexts.scopes), 'original source scope')]
                if (source.owner.occurrence, _SOURCE_ROLES.get(source.owner.kind)) != key:
                    raise ValueError('C3-T block is not the role of its original typed source owner')
        for index, block in enumerate(data.blocks):
            expected = [] if index == 0 or block.attachment == 'FUTURE_DETACHED' else [block.parent]
            if child_refs[index] != expected:
                raise ValueError('C3-T original parent/child attachment inverse is incomplete')
        for row in data.scopes:
            block = self.block(row.block)
            if block.source_scope != row.scope or row.disposition != block.projection:
                raise ValueError('C3-T source projection does not round-trip to its compiler template')
            source = self.contexts.scopes[row.scope]
            parent = None if source.parent is None else self.scope(source.parent).block
            if block.parent != parent:
                raise ValueError('C3-T source parent does not match the original compiler environment')
        actual_rewrites = {(row.rule, row.block, row.parent) for row in data.rewrites}
        if len(actual_rewrites) != len(data.rewrites) or actual_rewrites != expected_rewrites:
            raise ValueError('C3-T rewrite witnesses are missing, duplicated or unsupported')
        if set(public_refs) != set(range(len(self.native.scopes))) or data.blocks[0].public_scope != self.native.root:
            raise ValueError('C3-T public correspondence does not cover the original compiler rows exactly once')
        children, edges = _projection_children(data.blocks), 0
        for native, index in public_refs.items():
            projected = tuple(self.block(child).public_scope for child in children[index])
            if projected != self.native.scopes[native].children:
                raise ValueError('C3-T original public child edges differ from the witnessed splice result')
            edges += len(projected)
        for index in range(len(self.contexts.regions)):
            self.region(index)
        return dict(blocks=len(data.blocks), scopes=len(data.scopes), regions=len(self.contexts.regions),
            public_blocks=len(public_refs), public_edges=edges, rewrites=len(data.rewrites))


__all__ = ['CompilerTopologyView']
