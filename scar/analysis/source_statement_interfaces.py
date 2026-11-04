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

    def suite_items(self, occurrence, name):
        value = self.roles.field(occurrence, name)
        _require(value.kind == 'LIST' and all(v.kind == 'NODE' for v in value.items),
            occurrence, 'statement suite must contain original node references')
        return tuple(v.reference for v in value.items)

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

    def groups(self, occurrence):
        kind = self.nodes[occurrence].constructor
        groups = {name: self.suite_items(occurrence, name) for name in _SUITES.get(kind, ())}
        if kind in ('Try', 'TryStar'):
            handlers = self.roles.field(occurrence, 'handlers')
            groups.update(('handler:' + str(i), self.suite_items(v.reference, 'body'))
                for i, v in enumerate(handlers.items))
        elif kind == 'Match':
            cases = self.roles.field(occurrence, 'cases')
            groups.update(('case:' + str(i), self.suite_items(v.reference, 'body'))
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
