"""Join C3 construction blocks to compiled code constants, without execution.

The join follows original compiler parents, including generic factories and
inlined scopes. Source positions and language role constrain each child slot;
the caller must still authenticate its complete captured code descriptor.
No callable instance, environment contents or execution is inferred here.
"""
from collections import defaultdict
import dis
from types import CodeType

from scar.analysis.compiler_topology import compiler_topology_catalog
from scar.ir.program.compiler_code_paths import CompilerCodePath, CompilerCodeRole as Role


# A finite rule per C3 origin, rather than a list of application constructs.
# Names are compiler conventions or original source identifiers, never rules
# about particular libraries. Location matching is scoped by the parent path.
_RULES = {
    Role.ROOT: ('ROOT', 'ROOT'),
    Role.FUNCTION_BODY: ('DECLARATION', 'ORIGIN'),
    Role.LAMBDA_BODY: ('EXPRESSION', 'ORIGIN'),
    Role.CLASS_BODY: ('DECLARATION', 'ORIGIN'),
    Role.TYPE_PARAMETERS: ('FACTORY', 'ORIGIN'),
    Role.HEADER_ANNOTATIONS: ('ANNOTATIONS', 'ORIGIN'),
    Role.VARIABLE_ANNOTATIONS: ('ANNOTATIONS', 'ENTRY'),
    Role.TYPE_PARAMETER_BOUND: ('PARAMETER', 'EXPRESSION'),
    Role.TYPE_PARAMETER_DEFAULT: ('PARAMETER', 'EXPRESSION'),
    Role.TYPE_ALIAS: ('DECLARATION', 'ORIGIN'),
    Role.COMPREHENSION: ('EXPRESSION', 'ORIGIN'),
    Role.GENERATOR_EXPRESSION: ('EXPRESSION', 'ORIGIN'),
}
_PROJECTIONS = frozenset(('PUBLIC', 'INLINED', 'FUTURE_DETACHED', 'DETACHED_DESCENDANT'))
_EXPRESSION_NAMES = {'Lambda':'<lambda>', 'GeneratorExp':'<genexpr>',
    'ListComp':'<listcomp>', 'SetComp':'<setcomp>', 'DictComp':'<dictcomp>'}


class CompilerCodeIndex:
    """Shared code paths indexed by original source scope, not source lines.

    Non-emitted blocks retain their C3 projection. Ambiguous correspondence
    remains a frontier; two source blocks never silently acquire one code.
    """
    def __init__(self, syntax, topology, root):
        catalog = compiler_topology_catalog()
        if (set(_RULES) != {Role(role) for role in catalog['origin_roles']}
                or _PROJECTIONS != set(catalog['projections'])
                or topology.status != 'PROJECTED' or type(root) is not CodeType):
            raise ValueError('code construction rules must cover the original C3 domains')
        self.syntax, self.topology = syntax, topology
        self.schemas = {s.name:s for s in syntax.profile.ast_schema}
        self.codes = {():root}; self.loads = {}; self.children = defaultdict(list)
        self.by_scope = defaultdict(list); self.matches = {}; self.frontiers = []
        pending = [()]
        while pending:
            path = pending.pop(); code = self.codes[path]
            for instruction in dis.get_instructions(code, adaptive=False, show_caches=False):
                if instruction.opname != 'LOAD_CONST' or type(instruction.argval) is not CodeType:
                    continue
                if (type(instruction.arg) is not int
                        or code.co_consts[instruction.arg] is not instruction.argval):
                    raise ValueError('compiler child lost its original constant slot')
                child = (*path,instruction.arg)
                load = instruction.offset,tuple(instruction.positions)
                if child not in self.codes:
                    self.codes[child] = instruction.argval; pending.append(child)
                    self.children[path].append(child)
                self.loads.setdefault(child,[]).append(load)
        paths = {}
        for index, block in enumerate(topology.blocks):
            role = Role(block.origin.role)
            if block.projection not in _PROJECTIONS:
                raise ValueError('undeclared C3 code projection')
            if block.projection in ('FUTURE_DETACHED','DETACHED_DESCENDANT'):
                paths[index] = (); continue
            if block.parent is None:
                if role is not Role.ROOT or index != 0:
                    raise ValueError('compiler construction has a different root')
                paths[index] = ((),)
            elif block.projection == 'INLINED':
                paths[index] = paths[block.parent]
                continue
            elif block.source_scope is None:
                # Empty annotation symbol-table scopes emit no callback.
                paths[index] = (); continue
            else:
                selected = []
                for parent in paths[block.parent]:
                    for child in self.children[parent]:
                        if self._matches(block, parent, child): selected.append(child)
                paths[index] = tuple(dict.fromkeys(selected))
            if block.source_scope is None: continue
            candidates = paths[index]
            if len(candidates) != 1:
                self.frontiers.append(dict(block=index,scope=block.source_scope,
                    role=role.value,reason='NO_UNIQUE_COMPILER_CHILD',constant_paths=candidates))
                continue
            path = candidates[0]
            load,position = (None,None) if not path else self.loads[path][0]
            self.matches[index] = CompilerCodePath(index,block.source_scope,role,path,load,position)
        owners = defaultdict(list)
        for index,row in self.matches.items(): owners[row.constant_path].append(index)
        for path,indices in owners.items():
            if len(indices) > 1:
                for index in indices:
                    row = self.matches.pop(index)
                    self.frontiers.append(dict(block=index,scope=row.source_scope,role=row.role.value,
                        reason='COMPILER_CHILD_HAS_MULTIPLE_SOURCE_OWNERS',constant_paths=(path,)))
        for row in self.matches.values(): self.by_scope[row.source_scope].append(row)

    def field(self, occurrence, name):
        node = self.syntax.nodes[occurrence]
        return node.fields[self.schemas[node.constructor].fields.index(name)]

    def scalar(self, occurrence, name):
        return self.field(occurrence,name).scalar.to_python()

    def span(self, occurrence):
        node = self.syntax.nodes[occurrence]
        attributes = dict(zip(self.schemas[node.constructor].attributes,node.attributes))
        return tuple(attributes[name].scalar.to_python() if name in attributes else None
            for name in ('lineno','end_lineno','col_offset','end_col_offset'))

    def _name(self, block):
        occurrence = block.origin.occurrence; node = self.syntax.nodes[occurrence]
        kind = _RULES[Role(block.origin.role)][0]
        if kind == 'ROOT': return '<module>'
        if kind == 'ANNOTATIONS': return '__annotate__'
        if kind == 'EXPRESSION': return _EXPRESSION_NAMES[node.constructor]
        name = (self.scalar(self.field(occurrence,'name').reference,'id')
            if node.constructor == 'TypeAlias' else self.scalar(occurrence,'name'))
        return '<generic parameters of '+name+'>' if kind == 'FACTORY' else name

    def _matches(self, block, parent, child):
        code = self.codes[child]; origin = block.origin.occurrence
        if code.co_name != self._name(block): return False
        location = _RULES[Role(block.origin.role)][1]
        source = self.span(origin)
        spans = tuple(span for _,span in self.loads[child])
        if location == 'ORIGIN': return source in spans
        if location == 'EXPRESSION':
            field = 'bound' if block.origin.role == 'TYPE_PARAMETER_BOUND' else 'default_value'
            expression = self.field(origin,field)
            expected = self.span(expression.reference)
            # CPython may attribute construction to the type parameter or
            # to its expression. The code's entry line separates evaluators.
            return code.co_firstlineno == expected[0] and any(s in (source,expected) for s in spans)
        if location == 'ENTRY':
            if code.co_firstlineno != self.codes[parent].co_firstlineno: return False
            if self.syntax.nodes[origin].constructor in ('Module','Interactive'):
                return any(s[0] == code.co_firstlineno for s in spans)
            entry = source[0],source[0],source[2],source[2]
            return entry in spans
        return False

    def summary(self):
        return dict(source_blocks=len(self.topology.blocks),code_constants=len(self.codes),
            matched_blocks=len(self.matches),frontiers=self.frontiers,
            projections={p:sum(b.projection == p for b in self.topology.blocks) for p in sorted(_PROJECTIONS)})
