"""May-completion interfaces over original F2 statements, without execution.

These are conservative child obligations, not completed child lowerings or
proofs of feasible paths. Deferred definitions are atomic here. Only structured
control composes suites; source loops consume their own break/continue ports.
"""
from scar.ir.program import source_productions as P
from scar.ir.program.control import LanguageCompletionKind as C


_NORMAL = (C.FALLTHROUGH, None)
_RAISE = (C.RAISE, None)
_LOOPS = frozenset(('For', 'While', 'AsyncFor'))
_ATOMIC = frozenset(('Expr', 'Assign', 'AnnAssign', 'AugAssign', 'Delete', 'Import',
    'ImportFrom', 'Assert', 'FunctionDef', 'AsyncFunctionDef', 'ClassDef', 'TypeAlias'))
_SUITES = {'If': ('body', 'orelse'), 'For': ('body', 'orelse'), 'While': ('body', 'orelse'),
    'AsyncFor': ('body', 'orelse'), 'With': ('body',), 'AsyncWith': ('body',),
    'Try': ('body', 'orelse', 'finalbody'), 'TryStar': ('body', 'orelse', 'finalbody')}
_CONSTRUCTORS = _ATOMIC | frozenset(_SUITES) | frozenset(('Pass', 'Global', 'Nonlocal',
    'Return', 'Raise', 'Break', 'Continue', 'Match'))


def _require(condition, path, detail):
    if not condition:
        from scar.analysis.source_productions import ProductionError
        raise ProductionError('STATEMENT_INTERFACE', str(path), detail)


class SourceStatementInterfaceIndex:
    """Memoized postorder over source references; no AST copies or unrolling."""
    def __init__(self, source):
        self.source = source
        self.nodes = source.context.syntax.nodes
        self.roles = source.roles
        self._summaries = {}
        self._import_projections = {port.site: source.frontend.declarations.ports[i].projection
            for i, port in enumerate(source.frontend.roles.ports) if port.role in (
                'IMPORT_MODULE_SPEC','IMPORT_MEMBER_SPEC','IMPORT_FROM_MODULE_SPEC','RELATIVE_MODULE_MARKER')}
        declared = {row.name for row in source.context.syntax.profile.ast_schema if 'stmt' in row.bases}
        _require(declared == _CONSTRUCTORS, 'constructor domain',
            'finite statement completion rules differ from the original grammar')
        self.constructors = tuple(sorted(declared))

    def active_loop(self, ref):
        # A body field enters its own loop, whereas an orelse field does not.
        if type(ref) is P.SlotRef:
            current = ref.occurrence
            if self.nodes[current].constructor in _LOOPS and self.roles.locate(ref)[0].name == 'body':
                return P.SourceLoopTarget(current)
        else:
            current = ref.occurrence
        while current in self.roles.parents:
            edge = self.roles.parents[current]
            kind = self.nodes[edge.occurrence].constructor
            field = self.roles.locate(edge)[0].name
            if kind in _LOOPS and field == 'body':
                return P.SourceLoopTarget(edge.occurrence)
            if kind in ('FunctionDef', 'AsyncFunctionDef', 'ClassDef', 'Lambda') and field == 'body':
                return None
            current = edge.occurrence
        return None

    def node_items(self, occurrence, name):
        value = self.roles.field(occurrence, name)
        _require(value.kind == 'LIST' and all(v.kind == 'NODE' for v in value.items),
            occurrence, 'source field must contain original node references')
        return tuple(v.reference for v in value.items)

    def function_docstring(self, occurrence):
        if self.nodes[occurrence].constructor not in ('FunctionDef','AsyncFunctionDef'):
            return None
        body = self.node_items(occurrence,'body')
        if not body or self.nodes[body[0]].constructor != 'Expr':
            return None
        value = self.roles.field(body[0],'value')
        if value.kind != 'NODE' or self.nodes[value.reference].constructor != 'Constant':
            return None
        if type(self.roles.field(value.reference,'value').scalar.to_python()) is not str:
            return None
        return P.SlotRef(value.reference,'FIELD',self.roles.fields['Constant']['value'])

    def docstring_owner(self, statement):
        parent = self.roles.parents.get(statement)
        if parent is None or self.nodes[parent.occurrence].constructor not in ('FunctionDef','AsyncFunctionDef'):
            return None
        return parent if self.roles.locate(parent)[0].name == 'body' and parent.item_path == (0,) and self.function_docstring(parent.occurrence) is not None else None

    def two_part_slice(self, occurrence):
        if self.nodes[occurrence].constructor != 'Slice':
            return False
        parts = [self.roles.field(occurrence, name) for name in ('lower', 'upper', 'step')]
        constant = all(v.kind != 'NODE' or self.nodes[v.reference].constructor == 'Constant' for v in parts)
        return not constant and parts[2].kind != 'NODE'

    def annotation_publication(self, occurrence, exception_abi):
        _require(self.nodes[occurrence].constructor == 'AnnAssign', occurrence, 'expected annotated assignment')
        annotation = P.SlotRef(occurrence, 'FIELD', self.roles.fields['AnnAssign']['annotation'])
        context = self.source.context.context_at_slot(annotation).state
        region = self.source.context.material.regions[context.region]
        simple = self.roles.field(occurrence, 'simple').scalar.to_python()
        if region.suppression_reason in ('FUNCTION_LOCAL_ANNOTATION', 'NON_SIMPLE_ANNOTATION'):
            return None
        target = self.roles.field(occurrence, 'target').reference
        _require(simple == 1 and self.nodes[target].constructor == 'Name', occurrence,
            'published variable annotation requires a simple original name')
        name = P.SlotRef(target, 'FIELD', self.roles.fields['Name']['id'])
        if region.suppression_reason == 'FUTURE_ANNOTATION_STRINGIZED':
            return P.PublishAnnotation(annotation, name, P.AnnotationPublicationKind.STRINGIZED, False, exception_abi)
        _require(region.eligibility == 'ELIGIBLE' and region.kind == 'VARIABLE_ANNOTATION',
            occurrence, 'unknown original variable annotation policy')
        environment = self.source.context.entry_context(occurrence).environment
        scope = self.source.context.material.scopes[environment]
        _require(scope.kind in ('ROOT_EXEC', 'ROOT_INTERACTIVE', 'CLASS'), occurrence,
            'published annotation requires an original module/class namespace')
        conditional = scope.kind != 'CLASS'
        current = occurrence
        compound = frozenset(('If', 'While', 'For', 'AsyncFor', 'Try', 'TryStar', 'With', 'AsyncWith', 'Match'))
        while current in self.roles.parents:
            edge = self.roles.parents[current]
            parent = self.nodes[edge.occurrence].constructor
            if parent in ('ClassDef', 'FunctionDef', 'AsyncFunctionDef'):
                break  # compiler conditional depth restarts in each code scope
            conditional |= parent in compound
            current = edge.occurrence
        return P.PublishAnnotation(annotation, name, P.AnnotationPublicationKind.DEFERRED, conditional, exception_abi)

    def import_request(self, occurrence, exception_abi, alias=None):
        kind = self.nodes[occurrence].constructor
        _require(kind in ('Import', 'ImportFrom'), occurrence, 'expected original import statement')
        members = self.node_items(occurrence, 'names')
        _require(bool(members), occurrence, 'import requires original aliases')
        if kind == 'Import':
            _require(alias in members, occurrence, 'ordinary import requires one of its original aliases')
            module = P.SlotRef(alias, 'FIELD', self.roles.fields['alias']['name'])
            names, level = None, None
            text = self.roles.field(alias, 'name').scalar.to_python()
            from_names, relative = None, 0
            anchor = alias
        else:
            _require(alias is None, occurrence, 'from-import has one shared request')
            module = P.SlotRef(occurrence, 'FIELD', self.roles.fields[kind]['module'])
            level = P.SlotRef(occurrence, 'FIELD', self.roles.fields[kind]['level'])
            names = tuple(P.SlotRef(a, 'FIELD', self.roles.fields['alias']['name']) for a in members)
            text = self.roles.field(occurrence, 'module').scalar.to_python() or ''
            from_names = tuple(self.roles.field(a, 'name').scalar.to_python() for a in members)
            relative = self.roles.field(occurrence, 'level').scalar.to_python()
            anchor = occurrence
        return P.ImportRequest(module, names, level, self.source.context.entry_context(anchor).environment, exception_abi,
            self.import_compiler_name(module, text), from_names, relative)

    def import_compiler_name(self, site, text):
        """Apply compiler name projection using the accepted original F3 basis.

        This uses the private policy/prefix, not IMPORT_HEAD binder projection:
        a full module request and its binding head are distinct names.
        """
        basis = self._import_projections.get(site)
        _require(basis is not None, site, 'import name has no original F3 projection basis')
        if basis.private_mode == 'NONE':
            return text
        if basis.private_mode == 'SELECTIVE':
            scope = self.source.context.material.scopes[basis.parameter_group]
            _, value = self.roles.locate(scope.anchor)
            allowed = {self.roles.field(v.reference, 'name').scalar.to_python()
                for v in value.items[:basis.prefix_count]}
            if text not in allowed:
                return text
        owner = basis.class_owner.occurrence
        class_name = self.roles.field(owner, 'name').scalar.to_python().lstrip('_')
        return ('_' + class_name + text if class_name and text.startswith('__')
            and not text.endswith('__') and '.' not in text else text)

    def import_member(self, alias, component, exception_abi):
        _require(self.nodes[alias].constructor == 'alias', alias, 'import member requires an original alias')
        parent = self.roles.parents[alias]
        owner = self.nodes[parent.occurrence].constructor
        name = self.roles.field(alias, 'name').scalar.to_python()
        if owner == 'ImportFrom':
            _require(component is None and name != '*', alias, 'from-import requires one named member')
            text = self.import_compiler_name(P.SlotRef(alias, 'FIELD', self.roles.fields['alias']['name']), name)
        else:
            _require(owner == 'Import' and self.roles.field(alias, 'asname').scalar.to_python() is not None
                and type(component) is int and 1 <= component < len(name.split('.')),
                alias, 'dotted as-import requires an original non-head path component')
            text = name.split('.')[component]
        return P.ImportMember(P.SlotRef(alias, 'FIELD', self.roles.fields['alias']['name']), component, exception_abi, text)

    def import_star(self, alias, exception_abi):
        _require(self.nodes[alias].constructor == 'alias'
            and self.roles.field(alias, 'name').scalar.to_python() == '*', alias, 'expected original star alias')
        parent = self.roles.parents[alias]
        _require(self.nodes[parent.occurrence].constructor == 'ImportFrom'
            and self.node_items(parent.occurrence, 'names') == (alias,), alias, 'star import requires one from-import alias')
        context = self.source.context.entry_context(alias)
        _require(self.source.context.material.scopes[context.environment].kind in ('ROOT_EXEC','ROOT_INTERACTIVE'),
            alias, 'star import requires an original module namespace')
        return P.ImportStar(P.SlotRef(alias, 'FIELD', self.roles.fields['alias']['name']), context.environment, exception_abi)

    def groups(self, occurrence):
        kind = self.nodes[occurrence].constructor
        groups = {name: self.node_items(occurrence, name) for name in _SUITES.get(kind, ())}
        if kind in ('Try', 'TryStar'):
            handlers = self.roles.field(occurrence, 'handlers')
            groups.update(('handler:' + str(i), self.node_items(v.reference, 'body'))
                for i, v in enumerate(handlers.items))
        elif kind == 'Match':
            cases = self.roles.field(occurrence, 'cases')
            groups.update(('case:' + str(i), self.node_items(v.reference, 'body'))
                for i, v in enumerate(cases.items))
        return groups

    def sequence(self, occurrences):
        result = {_NORMAL}
        for occurrence in occurrences:
            if _NORMAL not in result:
                break
            result.remove(_NORMAL)
            result.update(self._summaries[occurrence])
        return result

    def completions(self, occurrence):
        _require(type(occurrence) is int and 0 <= occurrence < len(self.nodes), occurrence, 'invalid original occurrence')
        pending = [(occurrence, False)]
        while pending:
            current, ready = pending.pop()
            if current in self._summaries:
                continue
            groups = self.groups(current)
            if not ready:
                pending.append((current, True))
                pending.extend((child, False) for items in reversed(tuple(groups.values())) for child in reversed(items))
                continue
            kind = self.nodes[current].constructor
            suites = {name: self.sequence(items) for name, items in groups.items()}
            if kind in _ATOMIC:
                result = {_NORMAL, _RAISE}
            elif kind in ('Pass', 'Global', 'Nonlocal'):
                result = {_NORMAL}
            elif kind == 'Return':
                result = {(C.RETURN, None)}
                if self.roles.field(current, 'value').kind == 'NODE':
                    result.add(_RAISE)
            elif kind == 'Raise':
                result = {_RAISE}
            elif kind in ('Break', 'Continue'):
                target = self.active_loop(P.ProductionOccurrence(current))
                _require(target is not None, current, 'break/continue has no active source loop')
                result = {(C.BREAK if kind == 'Break' else C.CONTINUE, target)}
            elif kind == 'If':
                result = suites['body'] | suites['orelse'] | {_RAISE}
            elif kind in _LOOPS:
                target = P.SourceLoopTarget(current)
                body = suites['body']
                result = (body - {_NORMAL, (C.BREAK, target), (C.CONTINUE, target)}) | suites['orelse'] | {_RAISE}
                if (C.BREAK, target) in body:
                    result.add(_NORMAL)
            elif kind in ('With', 'AsyncWith'):
                result = suites['body'] | {_RAISE}
                if _RAISE in suites['body']:
                    result.add(_NORMAL)  # __exit__ may suppress a body exception
            elif kind in ('Try', 'TryStar'):
                body = suites['body']
                result = body - {_NORMAL}
                if _NORMAL in body:
                    result |= suites['orelse']
                if _RAISE in body:
                    # Unmatched exceptions and errors in handler admission remain.
                    result |= set().union(*(v for k, v in suites.items() if k.startswith('handler:')))
                final = suites['finalbody']
                result = (result if _NORMAL in final else set()) | (final - {_NORMAL})
            elif kind == 'Match':
                # Matching/guards may raise, and no case may match. Feasibility
                # and irrefutability refinement are separate from this interface.
                result = {_NORMAL, _RAISE} | set().union(*suites.values())
            else:
                _require(False, current, 'no finite statement interface for ' + kind)
            self._summaries[current] = frozenset(result)
        rank = {kind: i for i, kind in enumerate(C)}
        return tuple(sorted(self._summaries[occurrence], key=lambda k: (rank[k[0]], -1 if k[1] is None else k[1].occurrence)))
