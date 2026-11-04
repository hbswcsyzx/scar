"""Structured statement schedules over the original F2/F3 recipe grammar.

Expression interfaces remain child obligations. Reference release is explicit:
discarding a result is not evidence that its computation/effects are dead.
Suites preserve completion ports; loops are shared templates. Definitions
and cleanup forms still retain local production frontiers.
"""
from hashlib import sha256
from pathlib import Path

from scar.analysis.source_expression_rules import SourceExpressionRules, _Builder, _REF, _BOOL, _require
from scar.ir.program import source_productions as P
from scar.ir.program.control import LanguageCompletionKind as C
from scar.ir.program.structured import PythonProtocolKind as K


_FIELDS = {'Expr': ('value',), 'Pass': (), 'Assign': ('targets', 'value', 'type_comment'),
    'Delete': ('targets',), 'Return': ('value',), 'Global': ('names',), 'Nonlocal': ('names',),
    'If': ('test', 'body', 'orelse'), 'While': ('test', 'body', 'orelse'),
    'For': ('target', 'iter', 'body', 'orelse', 'type_comment'),
    'AsyncFor': ('target', 'iter', 'body', 'orelse', 'type_comment'), 'Break': (), 'Continue': (),
    'AugAssign': ('target', 'op', 'value'), 'AnnAssign': ('target', 'annotation', 'value', 'simple'),
    'Assert': ('test', 'msg'), 'Raise': ('exc', 'cause'),
    'Import': ('names',), 'ImportFrom': ('module', 'names', 'level'),
    'FunctionDef': ('name','args','body','decorator_list','returns','type_comment','type_params'),
    'AsyncFunctionDef': ('name','args','body','decorator_list','returns','type_comment','type_params'),
    'ClassDef': ('name','bases','keywords','body','decorator_list','type_params'),
    'TypeAlias': ('name','type_params','value'),
    'With': ('items','body','type_comment'), 'AsyncWith': ('items','body','type_comment'),
    'Try': ('body','handlers','orelse','finalbody'), 'TryStar': ('body','handlers','orelse','finalbody')}


class SourceStatementRules(SourceExpressionRules):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for constructor, expected in _FIELDS.items():
            _require(tuple(self.source.roles.fields[constructor]) == expected,
                'SOURCE_SCHEMA', constructor, 'original statement field grammar differs from the rule')

    def catalog(self):
        catalog = super().catalog()
        statements = {row.name for row in self.source.context.syntax.profile.ast_schema if 'stmt' in row.bases}
        for row in catalog['rules']:
            row['status'] = ('LOCAL_STATEMENT_RULE' if row['constructor'] in _FIELDS else
                'RULE_FRONTIER' if row['constructor'] in statements else 'OUTSIDE_DOMAIN')
            row['purposes'] = [P.ProductionPurpose.STATEMENT.value] if row['constructor'] in _FIELDS else []
        return {**catalog, 'schema': 'scar.source-statement-rule-catalog',
            'statement_implementation_sha256': sha256(Path(__file__).read_bytes()).hexdigest(),
            'scope': 'STRUCTURED_STATEMENT_SOURCE_RECIPES_ONLY',
            'statement_interface_sha256': sha256(Path(__file__).with_name('source_statement_interfaces.py').read_bytes()).hexdigest(),
            'statement_completion_constructors': list(self.source.statements.constructors),
            'child_completions': 'CONSERVATIVE_SOURCE_OBLIGATIONS_NOT_CHILD_IMPLEMENTATION_PROOF'}

    def descriptor_owner(self, occurrence):
        return self.source.statements.docstring_owner(occurrence) if self.source.context.syntax.nodes[occurrence].constructor == 'Expr' else None

    def build(self, occurrence, purpose=P.ProductionPurpose.STATEMENT, *, max_steps=100_000, max_regions=100_000):
        syntax = self.source.context.syntax
        _require(type(occurrence) is int and 0 <= occurrence < len(syntax.nodes),
            'SOURCE_REFERENCE', 'occurrence', 'expected an original F2 statement occurrence')
        _require(purpose is P.ProductionPurpose.STATEMENT, 'PURPOSE_FRONTIER', str(occurrence),
            'statement rules require the statement interface')
        for name, count in (('max_steps', max_steps), ('max_regions', max_regions)):
            _require(type(count) is int and count >= 0, 'QUERY_ARGUMENT', name, 'expected an exact nonnegative integer')
        constructor = syntax.nodes[occurrence].constructor
        _require(constructor in _FIELDS, 'RULE_FRONTIER', str(occurrence),
            'no local statement rule implemented for ' + constructor)
        _require(self.descriptor_owner(occurrence) is None, 'PARENT_OWNED_SOURCE', str(occurrence),
            'docstring belongs to its parent declaration schedule')
        context = self.source.context.entry_context(occurrence)
        _require(self.source.context.material.regions[context.region].eligibility == 'ELIGIBLE',
            'SUPPRESSED_SOURCE', str(occurrence), 'C1 retains this statement without execution')
        result = _StatementBuilder(self, occurrence, purpose, max_steps, max_regions).build()
        self.source.match(result)
        return result


class _StatementBuilder(_Builder):
    def build(self):
        source = P.ProductionOccurrence(self.occurrence)
        root = self.region(source, (self.world,))
        current = self.parameter(root, 0)
        kind = self.node.constructor
        for name in _FIELDS[kind]:
            self.mark(name, P.ProductionDispositionKind.METADATA)
        if kind == 'Expr':
            self.mark('value', P.ProductionDispositionKind.EVALUATED_CHILD)
            value, current = self.evaluate(root, self.site('value'), current)
            current, = self.protocol(root, K.FRAME_RELEASE_TEMPORARY, (value,), current)
        elif kind in ('Assign', 'Delete'):
            self.mark('targets', P.ProductionDispositionKind.TARGET_ADDRESS)
            targets = self.value(self.site('targets'))
            _require(targets.kind == 'LIST' and bool(targets.items), 'RULE_SHAPE', str(source), 'targets must be nonempty')
            value = None
            if kind == 'Assign':
                self.mark('value', P.ProductionDispositionKind.EVALUATED_CHILD)
                value, current = self.evaluate(root, self.site('value'), current)
            for ordinal in range(len(targets.items)):
                site = self.site('targets', ordinal)
                current, = self.evaluate(root, site, current,
                    P.ProductionPurpose.STORE if kind == 'Assign' else P.ProductionPurpose.DELETE, value)
            if kind == 'Assign':
                current, = self.protocol(root, K.FRAME_RELEASE_TEMPORARY, (value,), current)
        elif kind == 'Return':
            _require(self.rules.source.context.entry_context(self.occurrence).owner.kind == 'FUNCTION_BODY',
                'STATEMENT_CONTEXT_FRONTIER', str(source), 'return requires an original function execution owner')
            field = self.value(self.site('value'))
            if field.kind == 'NODE':
                self.mark('value', P.ProductionDispositionKind.EVALUATED_CHILD)
                value, current = self.evaluate(root, self.site('value'), current)
            else:
                _require(field.kind == 'SCALAR' and field.scalar.to_python() is None,
                    'RULE_SHAPE', str(source), 'bare return requires an explicit None field')
                value, current = self.literal(root, None, current)
            self.transfer(root, C.RETURN, (value, current), (_REF, self.world))
            return self.plan(root, source)
        elif kind in ('Global', 'Nonlocal'):
            values = self.value(self.site('names'))
            _require(values.kind == 'LIST' and bool(values.items), 'RULE_SHAPE', str(source), 'directive requires names')
            for ordinal in range(len(values.items)):
                self.slots[self.site('names', ordinal)] = P.ProductionDispositionKind.ROLE_PORT
        elif kind in ('Break', 'Continue'):
            target = self.rules.source.statements.active_loop(source)
            _require(target is not None, 'STATEMENT_CONTEXT_FRONTIER', str(source), 'jump requires an active original loop')
            self.transfer(root, C.BREAK if kind == 'Break' else C.CONTINUE, (current,), (self.world,), target)
            return self.plan(root, source)
        elif kind == 'If':
            self.conditional_statement(root, current)
            return self.plan(root, source)
        elif kind in ('While', 'For', 'AsyncFor'):
            self.loop_statement(root, current)
            return self.plan(root, source)
        elif kind in ('AugAssign', 'AnnAssign', 'Assert', 'Raise'):
            from scar.analysis.source_statement_atoms import emit_atomic_statement
            emit_atomic_statement(self, root, current)
            return self.plan(root, source)
        elif kind in ('Import', 'ImportFrom'):
            from scar.analysis.source_statement_imports import emit_import_statement
            emit_import_statement(self, root, current)
            return self.plan(root, source)
        elif kind in ('FunctionDef','AsyncFunctionDef'):
            from scar.analysis.source_statement_functions import emit_function_definition
            emit_function_definition(self, root, current)
            return self.plan(root, source)
        elif kind in ('ClassDef','TypeAlias'):
            from scar.analysis.source_statement_definitions import emit_definition
            emit_definition(self,root,current)
            return self.plan(root,source)
        elif kind in ('With','AsyncWith'):
            from scar.analysis.source_statement_contexts import emit_context_statement
            emit_context_statement(self,root,current)
            return self.plan(root,source)
        elif kind in ('Try','TryStar'):
            from scar.analysis.source_statement_exceptions import emit_try_statement
            emit_try_statement(self,root,current)
            return self.plan(root,source)
        self.finish(root, (current,), (self.world,))
        return self.plan(root, source)

    def interface(self, occurrence):
        return tuple(P.ProductionCompletion(kind,
            self.raised if kind is C.RAISE else (_REF, self.world) if kind is C.RETURN else (self.world,), target)
            for kind, target in self.rules.source.statements.completions(occurrence))

    def suite(self, region, name, current, *, metadata_prefix=0):
        self.suite_at(region,self.site(name),current,metadata_prefix=metadata_prefix)

    def suite_at(self,region,site,current,*,metadata_prefix=0):
        self.slots[site]=P.ProductionDispositionKind.EVALUATED_CHILD
        values = self.value(site)
        _require(values.kind == 'LIST', 'RULE_SHAPE', str(site), 'suite requires an original list field')
        for ordinal, value in enumerate(values.items):
            child = P.SlotRef(site.occurrence,site.group,site.ordinal,(*site.item_path,ordinal))
            if ordinal < metadata_prefix:
                self.slots[child] = P.ProductionDispositionKind.METADATA
                continue
            if current is None:
                self.slots[child] = P.ProductionDispositionKind.NO_NORMAL_PREDECESSOR
                continue
            _require(value.kind == 'NODE', 'RULE_SHAPE', str(child), 'suite item must be an original statement')
            self.slots[child] = P.ProductionDispositionKind.EVALUATED_CHILD
            results = self.control(region, P.EvaluateChild(child, P.ProductionPurpose.STATEMENT),
                (current,), self.interface(value.reference), source=child)
            current = results[0] if results else None
        if current is not None:
            self.finish(region, (current,), (self.world,))

    def conditional_statement(self, root, current):
        self.mark('test', P.ProductionDispositionKind.EVALUATED_CHILD)
        value, current = self.evaluate(root, self.site('test'), current)
        decision, current = self.action(root, P.LanguageActionKind.TRUTH, (), (value, current), (_BOOL, self.world))
        alternatives = []
        for name in ('body', 'orelse'):
            child = self.region(self.site(name), (self.world,), root)
            self.suite(child, name, self.parameter(child, 0))
            alternatives.append(child)
        result = self.control(root, P.BranchControl(*(P.ProductionRegionCall(child.id, (current,)) for child in alternatives)),
            (decision,), self.union(*(self.completions(child) for child in alternatives)))
        if result:
            self.finish(root, result, (self.world,))

    def loop_statement(self, root, current):
        source = P.ProductionOccurrence(self.occurrence)
        target = P.SourceLoopTarget(self.occurrence)
        iterator = None
        if self.node.constructor != 'While':
            from scar.analysis.source_comprehension_rules import get_iterator
            self.mark('iter', P.ProductionDispositionKind.EVALUATED_CHILD)
            self.mark('target', P.ProductionDispositionKind.TARGET_ADDRESS)
            iterable, current = self.evaluate(root, self.site('iter'), current)
            iterator, current = get_iterator(self, root, iterable, current, self.node.constructor == 'AsyncFor')
        invariant = 0 if iterator is None else 1
        loop = self.region(source, (self.world,) if iterator is None else (_REF, self.world), root, P.ProductionRegionKind.LOOP)
        condition = self.region(self.site('test' if iterator is None else 'iter'), loop.parameters,
            loop, P.ProductionRegionKind.LOOP_CONDITION)
        state = self.parameter(condition, invariant)
        if iterator is None:
            self.mark('test', P.ProductionDispositionKind.EVALUATED_CHILD)
            value, state = self.evaluate(condition, self.site('test'), state)
            decision, state = self.action(condition, P.LanguageActionKind.TRUTH, (), (value, state), (_BOOL, self.world))
            self.finish(condition, (decision, state), (_BOOL, self.world))
            control = condition.id
        else:
            asynchronous = self.node.constructor == 'AsyncFor'
            if asynchronous:
                from scar.analysis.source_delegation_rules import emit_delegate_loop
                qualified, state = self.delegation(condition, P.DelegationProtocolKind.GET_ASYNC_NEXT,
                    (self.parameter(condition, 0),), state)
                advanced = emit_delegate_loop(self, condition, qualified, state, P.SuspensionKind.AWAIT)
            else:
                advanced = self.protocol(condition, K.COMPREHENSION_NEXT, (self.parameter(condition, 0),), state,
                    selectors=(self.site('iter'),))
            self.finish(condition, advanced, (_REF, self.world))
            exhausted = self.region(self.site('iter'), self.raised, loop, P.ProductionRegionKind.HANDLER)
            args = (self.parameter(exhausted, 0),)
            state = self.parameter(exhausted, len(self.raised)-1)
            stopped, = (self.delegation(exhausted, P.DelegationProtocolKind.MATCH_STOP_ASYNC_ITERATION, args, state)
                if asynchronous else self.protocol(exhausted, K.MATCH_STOP_ITERATION, args, state))
            self.finish(exhausted, (stopped,), (_BOOL,))
            control = P.IterationCondition(P.ProductionRegionCall(condition.id,
                tuple(self.parameter(loop, i) for i in range(len(loop.parameters)))), exhausted.id, invariant)
        body = self.region(self.site('body'), loop.parameters if iterator is None else (*loop.parameters, _REF),
            loop, P.ProductionRegionKind.LOOP_BODY)
        state = self.parameter(body, invariant)
        if iterator is not None:
            state, = self.evaluate(body, self.site('target'), state, P.ProductionPurpose.STORE, self.parameter(body, invariant+1))
        self.suite(body, 'body', state)
        otherwise = self.region(self.site('orelse'), loop.parameters, loop)
        self.suite(otherwise, 'orelse', self.parameter(otherwise, invariant))
        consumed = {(C.FALLTHROUGH, None), (C.BREAK, target), (C.CONTINUE, target)}
        escaped = tuple(c for c in self.completions(body) if (c.kind, c.target) not in consumed)
        exits = self.union(escaped, self.completions(otherwise), (P.ProductionCompletion(C.RAISE, self.raised),),
            (self.normal((self.world,)),) if any(c.kind is C.BREAK and c.target == target for c in self.completions(body)) else ())
        self.control(loop, P.LoopControl(control, body.id, otherwise.id, invariant, target),
            tuple(self.parameter(loop, i) for i in range(len(loop.parameters))), exits)
        inputs = (current,) if iterator is None else (iterator, current)
        result = self.control(root, P.ApplyRegion(P.ProductionRegionCall(loop.id, inputs)), (), exits)
        if result:
            self.finish(root, result, (self.world,))
