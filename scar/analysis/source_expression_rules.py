"""F4-B local expression schedules over accepted original F2/F3 references.

Child evaluations are typed obligations, not recursively completed lowerings.
One conservative state domain threads every potentially effectful protocol.
No effect is certified pure and no physical allocation/transfer is inferred.
"""
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path

from scar.analysis.source_productions import ProductionError, ProductionSourceIndex, _digest
from scar.ir.program import source_productions as P
from scar.ir.program.control import LanguageCompletionKind as C
from scar.ir.program.model import ValueKind, ValueType
from scar.ir.program.protocol_signatures import ExceptionABI
from scar.ir.program.signature_patterns import ResolvedSignature, SignatureForm, validate_resolved_signature
from scar.ir.record_codec import encode


_REF = ValueType(ValueKind.REFERENCE)
_BOOL = ValueType(ValueKind.DATA, 'builtins.bool')
_FIELDS = {
    'Constant': ('value', 'kind'), 'Name': ('id', 'ctx'),
    'BinOp': ('left', 'op', 'right'), 'UnaryOp': ('op', 'operand'),
    'Attribute': ('value', 'attr', 'ctx'), 'Subscript': ('value', 'slice', 'ctx'),
    'Slice': ('lower', 'upper', 'step'), 'NamedExpr': ('target', 'value'),
    'IfExp': ('test', 'body', 'orelse'), 'BoolOp': ('op', 'values'),
    'Compare': ('left', 'ops', 'comparators'),
}
_SELECTORS = {
    'BinOp': frozenset(('Add', 'Sub', 'Mult', 'MatMult', 'Div', 'Mod', 'Pow', 'LShift',
                       'RShift', 'BitOr', 'BitXor', 'BitAnd', 'FloorDiv')),
    'UnaryOp': frozenset(('Invert', 'Not', 'UAdd', 'USub')),
    'BoolOp': frozenset(('And', 'Or')),
    'Compare': frozenset(('Eq', 'NotEq', 'Lt', 'LtE', 'Gt', 'GtE', 'Is', 'IsNot', 'In', 'NotIn')),
}
_TARGETS = frozenset(('Name', 'Attribute', 'Subscript'))


class SourceRuleError(ProductionError):
    pass


def _require(condition, code, path, detail):
    if not condition:
        raise SourceRuleError(code, path, detail)


@dataclass
class _Draft:
    id: P.ProductionRegionID
    parent: P.ProductionRegionID | None
    kind: P.ProductionRegionKind
    source: P.ProductionSource
    parameters: tuple
    steps: list = field(default_factory=list)


class SourceExpressionRules:
    """Source schedules conditional on explicit state/exception interfaces.

    These interfaces are supplied, not inferred from an existing op's arity.
    Their physical state/effect correspondence remains a separate obligation.
    """
    def __init__(self, source, *, world, exception_abi):
        _require(type(source) is ProductionSourceIndex, 'SOURCE_INPUT', 'source', 'expected an original source index')
        validate_resolved_signature(ResolvedSignature(SignatureForm.ORDINARY, (world,), (world,)))
        _require(type(world) is ValueType and world.kind is ValueKind.STATE, 'STATE_PARAMETER',
                 'world', 'source schedule requires an explicit abstract state domain')
        _require(type(exception_abi) is ExceptionABI and any(exception_abi is member for member in ExceptionABI),
                 'EXCEPTION_ABI', 'exception_abi', 'expected a declared exception ABI')
        self.source, self.world, self.exception_abi = source, world, exception_abi
        self.raised = ((_REF, world) if exception_abi is ExceptionABI.EXCEPTION_WORLD else (_REF, _REF, world))
        self._identity = _digest(encode(source.input))[:24]
        self._ports = {}
        for ordinal, port in enumerate(source.frontend.roles.ports):
            self._ports.setdefault(port.site, []).append(ordinal)
        for constructor, expected in _FIELDS.items():
            actual = tuple(source.roles.fields[constructor])
            _require(actual == expected, 'SOURCE_SCHEMA', constructor, 'original field grammar differs from the rule')

    def catalog(self):
        rows = []
        selectors = ('operator', 'unaryop', 'boolop', 'cmpop', 'expr_context')
        for row in self.source.context.syntax.profile.ast_schema:
            if row.abstract:
                continue
            supported = row.name in _FIELDS
            status = ('LOCAL_RULE' if supported else 'SELECTOR_METADATA' if any(
                base in selectors for base in row.bases) else 'RULE_FRONTIER')
            purposes = ((P.ProductionPurpose.VALUE, P.ProductionPurpose.STORE, P.ProductionPurpose.DELETE)
                        if row.name in _TARGETS else (P.ProductionPurpose.VALUE,)) if supported else ()
            rows.append(dict(constructor=row.name, fields=list(row.fields), status=status,
                purposes=[p.value for p in purposes], selectors=sorted(_SELECTORS.get(row.name, ()))))
        return dict(schema='scar.source-expression-rule-catalog', schema_version=1,
            source_schema_sha256=self.source.roles.catalog.f2_schema_sha256,
            rules=rows, implementation_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),
            state_parameter=encode(self.world), exception_abi=self.exception_abi.value,
            child_interfaces='VALUE:(WORLD)->(REFERENCE,WORLD);STORE:(REFERENCE,WORLD)->(WORLD);DELETE:(WORLD)->(WORLD)',
            effect_policy='CONSERVATIVE_STATE;NO_PURITY_OR_PHYSICAL_ACTION_PROOF')

    def build(self, occurrence, purpose=P.ProductionPurpose.VALUE, *, max_steps=100_000, max_regions=100_000):
        syntax = self.source.context.syntax
        _require(type(occurrence) is int and 0 <= occurrence < len(syntax.nodes), 'SOURCE_REFERENCE',
                 'occurrence', 'expected an original F2 occurrence')
        _require(type(purpose) is P.ProductionPurpose, 'PURPOSE', 'purpose', 'expected an exact source purpose')
        for name, count in (('max_steps', max_steps), ('max_regions', max_regions)):
            _require(type(count) is int and count >= 0, 'QUERY_ARGUMENT', name, 'expected an exact nonnegative integer')
        constructor = syntax.nodes[occurrence].constructor
        _require(constructor in _FIELDS, 'RULE_FRONTIER', str(occurrence),
                 'no local expression rule implemented for ' + constructor)
        _require(purpose is P.ProductionPurpose.VALUE or constructor in _TARGETS and purpose in (
            P.ProductionPurpose.STORE, P.ProductionPurpose.DELETE), 'PURPOSE_FRONTIER', str(occurrence),
            'constructor has no rule for this purpose')
        context = self.source.context.entry_context(occurrence)
        _require(self.source.context.material.regions[context.region].eligibility == 'ELIGIBLE',
                 'SUPPRESSED_SOURCE', str(occurrence), 'C1 retains this syntax without an executable schedule')
        builder = _Builder(self, occurrence, purpose, max_steps, max_regions)
        result = builder.build()
        self.source.match(result)
        return result

    def verify(self, plan, **budgets):
        self.source.match(plan)
        _require(type(plan.source) is P.ProductionOccurrence, 'SOURCE_REFERENCE', 'plan.source',
                 'expression schedules require an original occurrence')
        expected = self.build(plan.source.occurrence, plan.purpose, **budgets)
        _require(plan == expected, 'SOURCE_RULE_MISMATCH', 'plan',
                 'source fields, schedule, state threading or completion references differ')
        return dict(source_rule_replayed=True, local_schedule_verified=True, field_dispositions_verified=True,
            child_interfaces_assumed=True, state_parameter_origin_proven=False,
            effects_proven=False, canonical_graph_generated=False, transformation_authorized=False)


class _Builder:
    def __init__(self, rules, occurrence, purpose, max_steps, max_regions):
        self.rules, self.occurrence, self.purpose = rules, occurrence, purpose
        self.max_steps, self.max_regions = max_steps, max_regions
        self.world, self.raised = rules.world, rules.raised
        self.regions, self.steps, self.slots = [], [], {}
        self.key = rules._identity + ':' + str(occurrence) + ':' + purpose.value
        self.node = rules.source.context.syntax.nodes[occurrence]
        self.role = rules.source.roles

    def site(self, name, item=None):
        return P.SlotRef(self.occurrence, 'FIELD', self.role.fields[self.node.constructor][name],
                         () if item is None else (item,))

    def value(self, site):
        return self.role.locate(site)[1]

    def mark(self, name, disposition):
        self.slots[self.site(name)] = disposition

    def selector(self, constructor, site):
        value = self.value(site)
        _require(value.kind == 'NODE', 'RULE_SHAPE', str(site), 'selector must be an original marker occurrence')
        name = self.rules.source.context.syntax.nodes[value.reference].constructor
        _require(name in _SELECTORS[constructor], 'RULE_SELECTOR', str(site), 'selector is outside its finite source domain')
        return name

    def region(self, source, parameters, parent=None):
        _require(len(self.regions) < self.max_regions, 'BUDGET_FRONTIER', 'regions', 'source region limit')
        region = _Draft(P.ProductionRegionID(self.key + ':r' + str(len(self.regions))),
            None if parent is None else parent.id,
            P.ProductionRegionKind.EXECUTION if parent is None else P.ProductionRegionKind.ALTERNATIVE,
            source, parameters)
        self.regions.append(region)
        return region

    def normal(self, types):
        return P.ProductionCompletion(C.FALLTHROUGH, types)

    def emit(self, region, instruction, arguments, types, *, may_raise=True, source=None):
        _require(len(self.steps) < self.max_steps, 'BUDGET_FRONTIER', 'steps', 'source step limit')
        completions = (self.normal(types),) + ((P.ProductionCompletion(C.RAISE, self.raised),) if may_raise else ())
        step = P.ProductionStep(P.ProductionStepID(self.key + ':s' + str(len(self.steps))), region.id,
            region.source if source is None else source, instruction, arguments, completions)
        self.steps.append(step)
        region.steps.append(step)
        return tuple(P.ProductionResult(step.id, i) for i in range(len(types)))

    def parameter(self, region, index):
        return P.ProductionParameter(region.id, index)

    def evaluate(self, region, site, state, purpose=P.ProductionPurpose.VALUE, value=None):
        _require(self.value(site).kind == 'NODE', 'RULE_SHAPE', str(site), 'evaluated child must be an expression occurrence')
        arguments = (state,) if value is None else (value, state)
        outputs = (_REF, self.world) if purpose is P.ProductionPurpose.VALUE else (self.world,)
        return self.emit(region, P.EvaluateChild(site, purpose), arguments, outputs, source=site)

    def action(self, region, kind, selectors, arguments, types=None):
        return self.emit(region, P.ApplyLanguageAction(kind, selectors), arguments,
                         (_REF, self.world) if types is None else types)

    def finish(self, region, values, types):
        self.emit(region, P.TransferCompletion(C.FALLTHROUGH), values, types, may_raise=False)

    def short_return(self, parent, source):
        child = self.region(source, (_REF, self.world), parent)
        self.finish(child, (self.parameter(child, 0), self.parameter(child, 1)), (_REF, self.world))
        return child

    def branch(self, region, condition, yes, yes_args, no, no_args):
        self.emit(region, P.BranchControl(P.ProductionRegionCall(yes.id, yes_args),
            P.ProductionRegionCall(no.id, no_args)), (condition,), (_REF, self.world))

    def build(self):
        root_source = P.ProductionOccurrence(self.occurrence)
        parameters = ((_REF, self.world) if self.purpose is P.ProductionPurpose.STORE else (self.world,))
        root = self.region(root_source, parameters)
        state = self.parameter(root, len(parameters) - 1)
        kind = self.node.constructor
        for name in _FIELDS[kind]:
            self.mark(name, P.ProductionDispositionKind.METADATA)
        if kind in _TARGETS:
            self.target(root, state)
        elif kind == 'Constant':
            # A literal source reference does not assert a fresh allocation.
            result = self.emit(root, P.ConstructValue(P.ConstructionKind.LITERAL,
                (self.site('value'), self.site('kind'))), (state,), (_REF, self.world))
            self.finish(root, result, (_REF, self.world))
        elif kind in ('BinOp', 'UnaryOp'):
            operands = ('left', 'right') if kind == 'BinOp' else ('operand',)
            refs = []
            for name in operands:
                self.mark(name, P.ProductionDispositionKind.EVALUATED_CHILD)
                ref, state = self.evaluate(root, self.site(name), state)
                refs.append(ref)
            self.selector(kind, self.site('op'))
            self.mark('op', P.ProductionDispositionKind.MARKER)
            result = self.action(root, P.LanguageActionKind.BINARY if kind == 'BinOp' else P.LanguageActionKind.UNARY,
                                 (self.site('op'),), (*refs, state))
            self.finish(root, result, (_REF, self.world))
        elif kind == 'Slice':
            refs = []
            for name in ('lower', 'upper', 'step'):
                value = self.value(self.site(name))
                if value.kind == 'NODE':
                    self.mark(name, P.ProductionDispositionKind.EVALUATED_CHILD)
                    ref, state = self.evaluate(root, self.site(name), state)
                    refs.append(ref)
                else:
                    _require(value.kind == 'SCALAR' and value.scalar.to_python() is None,
                             'RULE_SHAPE', str(self.site(name)), 'slice holes must be explicit None fields')
            result = self.emit(root, P.ConstructValue(P.ConstructionKind.SLICE,
                tuple(self.site(n) for n in ('lower', 'upper', 'step'))), (*refs, state), (_REF, self.world))
            self.finish(root, result, (_REF, self.world))
        elif kind == 'NamedExpr':
            self.mark('value', P.ProductionDispositionKind.EVALUATED_CHILD)
            self.mark('target', P.ProductionDispositionKind.TARGET_ADDRESS)
            value, state = self.evaluate(root, self.site('value'), state)
            target = self.value(self.site('target'))
            _require(target.kind == 'NODE' and self.rules.source.context.syntax.nodes[target.reference].constructor == 'Name',
                     'RULE_SHAPE', str(self.site('target')), 'named expression requires a Name target')
            state, = self.evaluate(root, self.site('target'), state, P.ProductionPurpose.STORE, value)
            self.finish(root, (value, state), (_REF, self.world))
        elif kind == 'IfExp':
            self.conditional(root, state)
        elif kind == 'BoolOp':
            self.boolean(root, state)
        elif kind == 'Compare':
            self.comparison(root, state)
        records = []
        for region in self.regions:
            exits = {}
            for ordinal, step in enumerate(region.steps):
                for completion in step.completions:
                    if completion.kind is not C.FALLTHROUGH or ordinal == len(region.steps) - 1:
                        key = completion.kind, completion.target
                        _require(key not in exits or exits[key].types == completion.types,
                                 'RULE_INTERFACE', str(region.id), 'region completion interfaces disagree')
                        exits[key] = completion
            source = region.source
            context = (self.rules.source.context.entry_context(source.occurrence)
                if type(source) is P.ProductionOccurrence else self.rules.source.context.context_at_slot(source).state)
            records.append(P.ProductionRegion(region.id, region.parent, region.kind, source, context,
                region.parameters, tuple(exits.values()), tuple(step.id for step in region.steps)))
        return P.SourceProductionPlan(self.rules.source.input, root_source, self.purpose, root.id,
            tuple(records), tuple(self.steps), tuple(P.ProductionSlotDisposition(site, disposition)
                for site, disposition in self.slots.items()))

    def target(self, region, state):
        kind = self.node.constructor
        context = self.value(self.site('ctx'))
        expected = {P.ProductionPurpose.VALUE: 'Load', P.ProductionPurpose.STORE: 'Store',
                    P.ProductionPurpose.DELETE: 'Del'}[self.purpose]
        _require(context.kind == 'NODE' and self.rules.source.context.syntax.nodes[context.reference].constructor == expected,
                 'PURPOSE_SOURCE_MISMATCH', str(self.occurrence), 'target context does not match the requested purpose')
        self.mark('ctx', P.ProductionDispositionKind.MARKER)
        assigned = (self.parameter(region, 0),) if self.purpose is P.ProductionPurpose.STORE else ()
        types = (_REF, self.world) if self.purpose is P.ProductionPurpose.VALUE else (self.world,)
        if kind == 'Name':
            self.mark('id', P.ProductionDispositionKind.ROLE_PORT)
            action, interface = {
                P.ProductionPurpose.VALUE: (P.BindingActionKind.READ, 'read_plan'),
                P.ProductionPurpose.STORE: (P.BindingActionKind.WRITE, 'write_target'),
                P.ProductionPurpose.DELETE: (P.BindingActionKind.DELETE, 'delete_target'),
            }[self.purpose]
            ports = [p for p in self.rules._ports.get(self.site('id'), ())
                     if getattr(self.rules.source.frontend.bindings.ports[p], interface) is not None]
            _require(len(ports) == 1, 'BINDING_INTERFACE_FRONTIER', str(self.occurrence),
                     'no unique original namespace access for this Name/purpose')
            result = self.emit(region, P.AccessBinding(action, ports[0]), (*assigned, state), types)
        else:
            self.mark('value', P.ProductionDispositionKind.EVALUATED_CHILD)
            receiver, state = self.evaluate(region, self.site('value'), state)
            if kind == 'Attribute':
                self.mark('attr', P.ProductionDispositionKind.ROLE_PORT)
                action = {P.ProductionPurpose.VALUE: P.LanguageActionKind.ATTRIBUTE_GET,
                    P.ProductionPurpose.STORE: P.LanguageActionKind.ATTRIBUTE_SET,
                    P.ProductionPurpose.DELETE: P.LanguageActionKind.ATTRIBUTE_DELETE}[self.purpose]
                args, selectors = (receiver, *assigned, state), (self.site('attr'), self.site('ctx'))
            else:
                self.mark('slice', P.ProductionDispositionKind.EVALUATED_CHILD)
                index, state = self.evaluate(region, self.site('slice'), state)
                action = {P.ProductionPurpose.VALUE: P.LanguageActionKind.ITEM_GET,
                    P.ProductionPurpose.STORE: P.LanguageActionKind.ITEM_SET,
                    P.ProductionPurpose.DELETE: P.LanguageActionKind.ITEM_DELETE}[self.purpose]
                args, selectors = (receiver, index, *assigned, state), (self.site('ctx'),)
            result = self.action(region, action, selectors, args, types)
        self.finish(region, result, types)

    def conditional(self, region, state):
        for name in ('test', 'body', 'orelse'):
            self.mark(name, P.ProductionDispositionKind.EVALUATED_CHILD)
        value, state = self.evaluate(region, self.site('test'), state)
        condition, state = self.action(region, P.LanguageActionKind.TRUTH, (), (value, state), (_BOOL, self.world))
        alternatives = []
        for name in ('body', 'orelse'):
            child = self.region(self.site(name), (self.world,), region)
            result = self.evaluate(child, self.site(name), self.parameter(child, 0))
            self.finish(child, result, (_REF, self.world))
            alternatives.append(child)
        self.branch(region, condition, alternatives[0], (state,), alternatives[1], (state,))

    def boolean(self, region, state):
        self.mark('op', P.ProductionDispositionKind.MARKER)
        self.mark('values', P.ProductionDispositionKind.EVALUATED_CHILD)
        selector = self.selector('BoolOp', self.site('op'))
        values = self.value(self.site('values'))
        _require(values.kind == 'LIST' and len(values.items) >= 2, 'RULE_SHAPE', str(self.occurrence),
                 'boolean operation requires at least two operands')
        for ordinal in range(len(values.items)):
            site = self.site('values', ordinal)
            value, state = self.evaluate(region, site, state)
            if ordinal == len(values.items) - 1:
                self.finish(region, (value, state), (_REF, self.world))
                break
            condition, state = self.action(region, P.LanguageActionKind.TRUTH, (), (value, state), (_BOOL, self.world))
            done = self.short_return(region, site)
            continuation = self.region(self.site('values', ordinal + 1), (self.world,), region)
            if selector == 'And':
                self.branch(region, condition, continuation, (state,), done, (value, state))
            else:
                self.branch(region, condition, done, (value, state), continuation, (state,))
            region, state = continuation, self.parameter(continuation, 0)

    def comparison(self, region, state):
        self.mark('left', P.ProductionDispositionKind.EVALUATED_CHILD)
        self.mark('ops', P.ProductionDispositionKind.MARKER)
        self.mark('comparators', P.ProductionDispositionKind.EVALUATED_CHILD)
        operators, comparators = self.value(self.site('ops')), self.value(self.site('comparators'))
        _require(operators.kind == comparators.kind == 'LIST' and len(operators.items) == len(comparators.items)
            and bool(operators.items), 'RULE_SHAPE', str(self.occurrence), 'comparison operand/selector lengths differ')
        left, state = self.evaluate(region, self.site('left'), state)
        for ordinal in range(len(operators.items)):
            operator, site = self.site('ops', ordinal), self.site('comparators', ordinal)
            self.selector('Compare', operator)
            right, state = self.evaluate(region, site, state)
            result, state = self.action(region, P.LanguageActionKind.COMPARE, (operator,), (left, right, state))
            if ordinal == len(operators.items) - 1:
                self.finish(region, (result, state), (_REF, self.world))
                break
            condition, state = self.action(region, P.LanguageActionKind.TRUTH, (), (result, state), (_BOOL, self.world))
            done = self.short_return(region, operator)
            continuation = self.region(self.site('comparators', ordinal + 1), (_REF, self.world), region)
            self.branch(region, condition, continuation, (right, state), done, (result, state))
            region = continuation
            left, state = self.parameter(region, 0), self.parameter(region, 1)
