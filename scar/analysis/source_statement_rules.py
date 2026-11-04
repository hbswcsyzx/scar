"""Linear statement schedules over the same original F2/F3 recipe grammar.

Expression interfaces remain child obligations. Reference release is explicit:
discarding a result is not evidence that its computation/effects are dead.
Control-flow, definitions and cleanup forms retain rule frontiers for now.
"""
from hashlib import sha256
from pathlib import Path

from scar.analysis.source_expression_rules import SourceExpressionRules, _Builder, _REF, _require
from scar.ir.program import source_productions as P
from scar.ir.program.control import LanguageCompletionKind as C
from scar.ir.program.structured import PythonProtocolKind as K


_FIELDS = {'Expr': ('value',), 'Pass': (), 'Assign': ('targets', 'value', 'type_comment'),
    'Delete': ('targets',), 'Return': ('value',), 'Global': ('names',), 'Nonlocal': ('names',)}


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
            'scope': 'LINEAR_STATEMENT_SOURCE_RECIPES_ONLY'}

    def descriptor_owner(self, occurrence):
        return None

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
        self.finish(root, (current,), (self.world,))
        return self.plan(root, source)
