"""F4-B local expression schedules over accepted original F2/F3 references.

Child evaluations are typed obligations, not recursively completed lowerings.
One conservative state domain threads every potentially effectful protocol.
No effect is certified pure and no physical allocation/transfer is inferred.
"""
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
import re
import sysconfig

from scar.analysis.source_productions import ProductionError, ProductionSourceIndex, _digest, production_type_catalog
from scar.ir.program import source_productions as P
from scar.ir.program.control import LanguageCompletionKind as C
from scar.ir.program.model import ValueKind, ValueType
from scar.ir.program.protocol_signatures import ExceptionABI, protocol_signature_catalog, _resolve_protocol_rule
from scar.ir.program.signature_patterns import (ResolvedSignature, SignatureForm, validate_resolved_signature,
    TypeBinding, ChoiceBinding, CountBinding)
from scar.ir.program.structured import PythonProtocolKind as K
from scar.ir.program.model import ExitKind
from scar.ir.program.delegation_signatures import delegation_signature_catalog, resolve_delegation_signature
from scar.ir.program.signature_patterns import SIGNATURE_RECORD_TAGS
from scar.ir.record_codec import encode
from scar.ir.literals import PythonLiteral


_REF = ValueType(ValueKind.REFERENCE)
_BOOL = ValueType(ValueKind.DATA, 'builtins.bool')
_FIELDS = {
    'Constant': ('value', 'kind'), 'Name': ('id', 'ctx'),
    'BinOp': ('left', 'op', 'right'), 'UnaryOp': ('op', 'operand'),
    'Attribute': ('value', 'attr', 'ctx'), 'Subscript': ('value', 'slice', 'ctx'),
    'Slice': ('lower', 'upper', 'step'), 'NamedExpr': ('target', 'value'),
    'IfExp': ('test', 'body', 'orelse'), 'BoolOp': ('op', 'values'),
    'Compare': ('left', 'ops', 'comparators'),
    'Call': ('func', 'args', 'keywords'),
    'List': ('elts', 'ctx'), 'Tuple': ('elts', 'ctx'), 'Set': ('elts',), 'Dict': ('keys', 'values'),
    'JoinedStr': ('values',), 'FormattedValue': ('value', 'conversion', 'format_spec'),
    'TemplateStr': ('values',), 'Interpolation': ('value', 'str', 'conversion', 'format_spec'),
    'ListComp': ('elt', 'generators'), 'SetComp': ('elt', 'generators'),
    'DictComp': ('key', 'value', 'generators'),
    'Yield': ('value',), 'YieldFrom': ('value',), 'Await': ('value',),
    'Lambda': ('args', 'body'), 'GeneratorExp': ('elt', 'generators'),
}
_AUX_FIELDS = {'keyword': ('arg', 'value'), 'Starred': ('value', 'ctx'),
               'comprehension': ('target', 'iter', 'ifs', 'is_async'),
               'arguments': ('posonlyargs', 'args', 'vararg', 'kwonlyargs', 'kw_defaults', 'kwarg', 'defaults'),
               'arg': ('arg', 'annotation', 'type_comment')}
_COMPREHENSIONS = ('ListComp', 'SetComp', 'DictComp')
_COMPREHENSION_PARENTS = (*_COMPREHENSIONS, 'GeneratorExp')
_SELECTORS = {
    'BinOp': frozenset(('Add', 'Sub', 'Mult', 'MatMult', 'Div', 'Mod', 'Pow', 'LShift',
                       'RShift', 'BitOr', 'BitXor', 'BitAnd', 'FloorDiv')),
    'UnaryOp': frozenset(('Invert', 'Not', 'UAdd', 'USub')),
    'BoolOp': frozenset(('And', 'Or')),
    'Compare': frozenset(('Eq', 'NotEq', 'Lt', 'LtE', 'Gt', 'GtE', 'Is', 'IsNot', 'In', 'NotIn')),
}
_TARGETS = frozenset(('Name', 'Attribute', 'Subscript', 'List', 'Tuple'))
_RULE_MODULES = ('source_display_rules.py', 'source_string_rules.py', 'source_comprehension_rules.py',
                 'source_suspension_rules.py', 'source_delegation_rules.py', 'source_callable_rules.py',
                 'source_deferred_interfaces.py', 'source_statement_atoms.py')


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
        self.protocols = {r.kind: r for r in protocol_signature_catalog()}
        header = Path(sysconfig.get_path('include')) / 'internal' / 'pycore_compile.h'
        raw = header.read_bytes()
        limits = re.findall(rb'^#define\s+_PY_STACK_USE_GUIDELINE\s+([0-9]+)\s*$', raw, re.MULTILINE)
        _require(len(limits) == 1 and int(limits[0]) > 0, 'COMPILER_PROFILE', str(header), 'no unique stack guideline')
        self.call_profile = dict(header=str(header), header_sha256=sha256(raw).hexdigest(), stack_guideline=int(limits[0]))
        self._ports = {}
        for ordinal, port in enumerate(source.frontend.roles.ports):
            self._ports.setdefault(port.site, []).append(ordinal)
        for constructor, expected in {**_FIELDS, **_AUX_FIELDS}.items():
            actual = tuple(source.roles.fields[constructor])
            _require(actual == expected, 'SOURCE_SCHEMA', constructor, 'original field grammar differs from the rule')

    def catalog(self):
        rows = []
        selectors = ('operator', 'unaryop', 'boolop', 'cmpop', 'expr_context')
        for row in self.source.context.syntax.profile.ast_schema:
            if row.abstract:
                continue
            supported = row.name in _FIELDS
            status = ('LOCAL_RULE' if supported else 'PARENT_CONTEXT_RULE' if row.name in _AUX_FIELDS else 'SELECTOR_METADATA' if any(
                base in selectors for base in row.bases) else 'RULE_FRONTIER')
            purposes = ((P.ProductionPurpose.VALUE, P.ProductionPurpose.STORE, P.ProductionPurpose.DELETE)
                        if row.name in _TARGETS else (P.ProductionPurpose.VALUE,)) if supported else ()
            rows.append(dict(constructor=row.name, fields=list(row.fields), status=status,
                purposes=[p.value for p in purposes], selectors=sorted(_SELECTORS.get(row.name, ())),
                context_frontiers=[],
                parent_contexts=([dict(constructor=p, field='args' if p == 'Call' else 'elts')
                    for p in ('Call', 'List', 'Tuple', 'Set')] if row.name == 'Starred' else
                    [dict(constructor=p, field='generators') for p in _COMPREHENSION_PARENTS] if row.name == 'comprehension' else
                    [dict(constructor='Lambda', field='args')] if row.name == 'arguments' else
                    [dict(constructor='arguments', field=p, owner='Lambda.args') for p in (
                        'posonlyargs', 'args', 'vararg', 'kwonlyargs', 'kwarg')] if row.name == 'arg' else
                    [dict(constructor='Call', field='keywords')] if row.name == 'keyword' else [])))
            if row.name in ('Name', 'Attribute', 'Subscript'):
                rows[-1]['parent_contexts'].extend((
                    dict(constructor='AugAssign', field='target', condition='READ_MODIFY_WRITE_ADDRESS'),
                    dict(constructor='AnnAssign', field='target', condition='DECLARATION_WITHOUT_RHS')))
            elif row.name in ('Slice', 'Tuple'):
                rows[-1]['parent_contexts'].append(dict(constructor='Subscript', field='slice',
                    owner='AnnAssign.target', condition='DECLARATION_COMPONENT_CHECKS_WITHOUT_RHS'))
                if row.name == 'Slice':
                    rows[-1]['parent_contexts'].append(dict(constructor='Subscript', field='slice',
                        owner='AugAssign.target', condition='NON_CONSTANT_TWO_PART_SLICE'))
        return dict(schema='scar.source-expression-rule-catalog', schema_version=1,
            source_schema_sha256=self.source.roles.catalog.f2_schema_sha256,
            recipe_type_catalog_sha256=production_type_catalog()['content_sha256'],
            rules=rows, implementation_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),
            production_modules={name: sha256(Path(__file__).with_name(name).read_bytes()).hexdigest() for name in _RULE_MODULES},
            delegation_protocols=[dict(protocol=kind.value, signature=encode(signature, record_tags=SIGNATURE_RECORD_TAGS))
                for kind, signature in delegation_signature_catalog().items()],
            state_parameter=encode(self.world), exception_abi=self.exception_abi.value,
            call_compiler_profile=self.call_profile,
            child_interfaces='VALUE:(WORLD)->(REFERENCE,WORLD);STORE:(REFERENCE,WORLD)->(WORLD);DELETE:(WORLD)->(WORLD)',
            effect_policy='CONSERVATIVE_STATE;NO_PURITY_OR_PHYSICAL_ACTION_PROOF')

    def descriptor_owner(self, occurrence):
        """An original parent edge, not a standalone executable expression."""
        syntax = self.source.context.syntax
        _require(type(occurrence) is int and 0 <= occurrence < len(syntax.nodes), 'SOURCE_REFERENCE',
                 'occurrence', 'expected an original descriptor occurrence')
        node = syntax.nodes[occurrence]
        site = self.source.roles.parents.get(occurrence)
        if site is None:
            return None
        parent = syntax.nodes[site.occurrence].constructor
        if node.constructor in ('Name', 'Attribute', 'Subscript'):
            if parent == 'AugAssign' and site.ordinal == self.source.roles.fields[parent]['target']:
                return site
            if parent == 'AnnAssign' and site.ordinal == self.source.roles.fields[parent]['target']:
                return site if self.source.roles.field(site.occurrence, 'value').kind != 'NODE' else None
        if node.constructor in ('Slice', 'Tuple'):
            outer = site
            while syntax.nodes[outer.occurrence].constructor == 'Tuple' and self.source.roles.locate(outer)[0].name == 'elts':
                outer = self.source.roles.parents[outer.occurrence]
            if syntax.nodes[outer.occurrence].constructor == 'Subscript' and self.source.roles.locate(outer)[0].name == 'slice':
                target = self.source.roles.parents.get(outer.occurrence)
                if target is not None and self.source.roles.locate(target)[0].name == 'target':
                    statement = syntax.nodes[target.occurrence].constructor
                    if statement == 'AnnAssign' and self.source.roles.field(target.occurrence, 'value').kind != 'NODE':
                        return site
                    if statement == 'AugAssign' and node.constructor == 'Slice' and outer == site and self.source.statements.two_part_slice(occurrence):
                        return site
        if node.constructor not in _AUX_FIELDS:
            return None
        if node.constructor == 'arguments':
            return site if parent == 'Lambda' and site.ordinal == self.source.roles.fields['Lambda']['args'] else None
        if node.constructor == 'arg':
            owner = self.source.roles.parents.get(site.occurrence)
            return site if parent == 'arguments' and owner is not None and (
                syntax.nodes[owner.occurrence].constructor == 'Lambda'
                and owner.ordinal == self.source.roles.fields['Lambda']['args']) else None
        allowed = (('Call', 'List', 'Tuple', 'Set') if node.constructor == 'Starred' else
                   _COMPREHENSION_PARENTS if node.constructor == 'comprehension' else ('Call',))
        if parent not in allowed:
            return None
        expected = (('args' if parent == 'Call' else 'elts') if node.constructor == 'Starred' else
                    'generators' if node.constructor == 'comprehension' else 'keywords')
        rule, _ = self.source.roles.locate(site)
        return site if site.group == 'FIELD' and rule.name == expected else None

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
        _require(self.descriptor_owner(occurrence) is None, 'PARENT_OWNED_SOURCE', str(occurrence),
            'target address/read/write schedule belongs to its original parent statement')
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
            scope_activation_proven=False, iterator_cleanup_proven=False,
            driver_admission_proven=False, resume_state_origin_proven=False, frame_context_lifetime_proven=False,
            native_delegation_expanded=False, driver_protocol_graph_generated=False,
            argument_admission_proven=False, closure_layout_proven=False, environment_activation_proven=False,
            compilation_options_resolved=False, annotation_request_bodies_lowered=False,
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

    def auxiliary(self, occurrence, name, disposition):
        kind = self.rules.source.context.syntax.nodes[occurrence].constructor
        site = P.SlotRef(occurrence, 'FIELD', self.role.fields[kind][name])
        self.slots[site] = disposition
        return site

    def selector(self, constructor, site):
        value = self.value(site)
        _require(value.kind == 'NODE', 'RULE_SHAPE', str(site), 'selector must be an original marker occurrence')
        name = self.rules.source.context.syntax.nodes[value.reference].constructor
        _require(name in _SELECTORS[constructor], 'RULE_SELECTOR', str(site), 'selector is outside its finite source domain')
        return name

    def region(self, source, parameters, parent=None, kind=None):
        _require(len(self.regions) < self.max_regions, 'BUDGET_FRONTIER', 'regions', 'source region limit')
        region = _Draft(P.ProductionRegionID(self.key + ':r' + str(len(self.regions))),
            None if parent is None else parent.id,
            kind if kind is not None else P.ProductionRegionKind.EXECUTION if parent is None else P.ProductionRegionKind.ALTERNATIVE,
            source, parameters)
        self.regions.append(region)
        return region

    def normal(self, types):
        return P.ProductionCompletion(C.FALLTHROUGH, types)

    def literal(self, region, value, state, source=None):
        return self.emit(region, P.DefineLiteral(PythonLiteral.from_python(value, exact=True)),
                         (state,), (_REF, self.world), source=source)

    def emit(self, region, instruction, arguments, types, *, may_raise=True, source=None, completion=C.FALLTHROUGH):
        completions = (P.ProductionCompletion(completion, types),) + ((P.ProductionCompletion(C.RAISE, self.raised),) if may_raise else ())
        return self.control(region, instruction, arguments, completions, source=source)

    def control(self, region, instruction, arguments, completions, *, source=None):
        _require(len(self.steps) < self.max_steps, 'BUDGET_FRONTIER', 'steps', 'source step limit')
        step = P.ProductionStep(P.ProductionStepID(self.key + ':s' + str(len(self.steps))), region.id,
            region.source if source is None else source, instruction, arguments, completions)
        self.steps.append(step)
        region.steps.append(step)
        types = next((c.types for c in completions if c.kind is C.FALLTHROUGH), ())
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

    def protocol(self, region, kind, arguments, state, extra=(), selectors=()):
        rule = self.rules.protocols[kind]
        invoke = rule.signature.form is SignatureForm.INVOKE
        bindings = (TypeBinding('world', self.world), *((ChoiceBinding('exception_abi', self.rules.exception_abi.value),) if invoke else ()), *extra)
        signature = _resolve_protocol_rule(rule, bindings)
        outputs = next(c.types for c in signature.completions if c.kind is ExitKind.NORMAL) if invoke else signature.results
        return self.emit(region, P.ApplyPythonProtocol(kind, bindings, selectors), (*arguments, state), outputs, may_raise=invoke)

    def delegation(self, region, kind, arguments, state):
        invoke = kind not in (P.DelegationProtocolKind.STOP_ITERATION_VALUE, P.DelegationProtocolKind.MATCH_STOP_ASYNC_ITERATION)
        bindings = (TypeBinding('world', self.world), *((ChoiceBinding('exception_abi',
            self.rules.exception_abi.value),) if invoke else ()))
        signature = resolve_delegation_signature(kind, bindings)
        outputs = next(c.types for c in signature.completions if c.kind is ExitKind.NORMAL) if invoke else signature.results
        return self.emit(region, P.ApplyDelegationProtocol(kind, bindings), (*arguments, state), outputs, may_raise=invoke)

    def environment(self, region, handle, state):
        return self.emit(region, P.ReferenceEnvironment(handle), (state,), (_REF, self.world), may_raise=False)

    def finish(self, region, values, types):
        self.transfer(region, C.FALLTHROUGH, values, types)

    def transfer(self, region, kind, values, types, target=None):
        self.control(region, P.TransferCompletion(kind, target), values, (P.ProductionCompletion(kind, types, target),))

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
        if kind in ('Name', 'Attribute', 'Subscript'):
            self.target(root, state)
        elif kind in ('List', 'Tuple', 'Set', 'Dict'):
            from scar.analysis.source_display_rules import emit_display
            emit_display(self, root, state)
        elif kind in ('JoinedStr', 'FormattedValue', 'TemplateStr', 'Interpolation'):
            from scar.analysis.source_string_rules import emit_string
            emit_string(self, root, state)
        elif kind in _COMPREHENSIONS:
            from scar.analysis.source_comprehension_rules import emit_comprehension
            emit_comprehension(self, root, state)
        elif kind == 'Yield':
            from scar.analysis.source_suspension_rules import emit_yield
            emit_yield(self, root, state)
        elif kind in ('YieldFrom', 'Await'):
            from scar.analysis.source_delegation_rules import emit_delegation
            emit_delegation(self, root, state)
        elif kind in ('Lambda', 'GeneratorExp'):
            from scar.analysis.source_callable_rules import emit_callable
            emit_callable(self, root, state)
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
        elif kind == 'Call':
            self.call(root, state)
        return self.plan(root, root_source)

    def completions(self, region):
        exits = {}
        for ordinal, step in enumerate(region.steps):
            for completion in step.completions:
                if completion.kind is not C.FALLTHROUGH or ordinal == len(region.steps) - 1:
                    key = completion.kind, completion.target
                    _require(key not in exits or exits[key].types == completion.types,
                             'RULE_INTERFACE', str(region.id), 'region completion interfaces disagree')
                    exits[key] = completion
        return tuple(exits.values())

    def plan(self, root, root_source):
        records = []
        for region in self.regions:
            source = region.source
            context = (self.rules.source.context.entry_context(source.occurrence)
                if type(source) is P.ProductionOccurrence else self.rules.source.context.context_at_slot(source).state)
            records.append(P.ProductionRegion(region.id, region.parent, region.kind, source, context,
                region.parameters, self.completions(region), tuple(step.id for step in region.steps)))
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

    def call(self, region, state):
        args, keywords = self.value(self.site('args')), self.value(self.site('keywords'))
        _require(args.kind == keywords.kind == 'LIST', 'RULE_SHAPE', str(self.occurrence), 'call inputs must be source lists')
        self.mark('func', P.ProductionDispositionKind.EVALUATED_CHILD)
        self.mark('args', P.ProductionDispositionKind.EVALUATED_CHILD)
        self.mark('keywords', P.ProductionDispositionKind.EVALUATED_CHILD)
        keyword_fields, seen = [], set()
        for item in keywords.items:
            _require(item.kind == 'NODE' and self.rules.source.context.syntax.nodes[item.reference].constructor == 'keyword',
                     'RULE_SHAPE', str(self.occurrence), 'call keyword must retain its original descriptor')
            occurrence = item.reference
            arg = P.SlotRef(occurrence, 'FIELD', self.role.fields['keyword']['arg'])
            raw = self.value(arg)
            _require(raw.kind == 'SCALAR', 'RULE_SHAPE', str(arg), 'keyword name must be a string or None')
            name = raw.scalar.to_python()
            _require(name is None or type(name) is str, 'RULE_SHAPE', str(arg), 'keyword name must be a string or None')
            if name is not None:
                _require(name not in seen, 'SOURCE_CODEGEN_CONFLICT', str(arg), 'repeated explicit keyword argument')
                seen.add(name)
            self.auxiliary(occurrence, 'arg', P.ProductionDispositionKind.METADATA if name is None else P.ProductionDispositionKind.ROLE_PORT)
            value = self.auxiliary(occurrence, 'value', P.ProductionDispositionKind.EVALUATED_CHILD)
            keyword_fields.append((arg, value, name))
        positionals = []
        for ordinal, item in enumerate(args.items):
            _require(item.kind == 'NODE', 'RULE_SHAPE', str(self.occurrence), 'call argument must be a child expression')
            starred = self.rules.source.context.syntax.nodes[item.reference].constructor == 'Starred'
            site = self.site('args', ordinal)
            if starred:
                context = self.auxiliary(item.reference, 'ctx', P.ProductionDispositionKind.MARKER)
                marker = self.value(context)
                _require(marker.kind == 'NODE' and self.rules.source.context.syntax.nodes[marker.reference].constructor == 'Load',
                         'RULE_SHAPE', str(context), 'starred call argument must be in Load context')
                site = self.auxiliary(item.reference, 'value', P.ProductionDispositionKind.EVALUATED_CHILD)
            positionals.append((site, starred))
        callee, state = self.evaluate(region, self.site('func'), state)
        expanded = any(star for _, star in positionals) or any(name is None for _, _, name in keyword_fields)
        if not expanded:
            values = []
            for site, _ in positionals:
                value, state = self.evaluate(region, site, state)
                values.append(value)
            for _, site, _ in keyword_fields:
                value, state = self.evaluate(region, site, state)
                values.append(value)
            result = self.action(region, P.LanguageActionKind.CALL, (self.site('args'), self.site('keywords')),
                                 (callee, *values, state))
        else:
            positional, state = self.call_positionals(region, positionals, state)
            mapping, index = None, 0
            while index < len(keyword_fields):
                arg, value, name = keyword_fields[index]
                if name is None:
                    if mapping is None:
                        mapping, state = self.protocol(region, K.BUILD_MAP, (), state,
                            (CountBinding('pair_count', 0),), (self.site('keywords'),))
                    update, state = self.evaluate(region, value, state)
                    state, = self.protocol(region, K.DICT_MERGE, (callee, mapping, update), state, selectors=(arg, value))
                    index += 1
                else:
                    end = index + 1
                    while end < len(keyword_fields) and keyword_fields[end][2] is not None:
                        end += 1
                    update, state = self.call_keyword_run(region, keyword_fields[index:end], state)
                    if mapping is None:
                        mapping = update
                    else:
                        state, = self.protocol(region, K.DICT_MERGE, (callee, mapping, update), state,
                            selectors=tuple(arg for arg, _, _ in keyword_fields[index:end]))
                    index = end
            result = self.protocol(region, K.CALL_FUNCTION_EX,
                (callee, positional, *((mapping,) if mapping is not None else ())), state,
                (ChoiceBinding('keyword_pack', 'PRESENT' if mapping is not None else 'ABSENT'),),
                (self.site('args'), self.site('keywords')))
        self.finish(region, result, (_REF, self.world))

    def call_positionals(self, region, items, state):
        # One *value remains unconverted until CALL_FUNCTION_EX, after kwargs.
        if len(items) == 1 and items[0][1]:
            return self.evaluate(region, items[0][0], state)
        sequence, held = None, []
        if len(items) > self.rules.call_profile['stack_guideline']:
            sequence, state = self.protocol(region, K.BUILD_CALL_POSITIONAL_LIST, (), state,
                (CountBinding('item_count', 0),), (self.site('args'),))
        for site, starred in items:
            if starred and sequence is None:
                sequence, state = self.protocol(region, K.BUILD_CALL_POSITIONAL_LIST, tuple(held), state,
                    (CountBinding('item_count', len(held)),), (self.site('args'),))
            value, state = self.evaluate(region, site, state)
            if sequence is None:
                held.append(value)
            else:
                state, = self.protocol(region, K.EXTEND_CALL_POSITIONALS if starred else K.APPEND_CALL_POSITIONAL,
                    (sequence, value), state, selectors=(site,))
        if sequence is None:
            return self.protocol(region, K.BUILD_CALL_POSITIONALS, tuple(held), state,
                (CountBinding('item_count', len(held)),), (self.site('args'),))
        return self.protocol(region, K.CALL_POSITIONALS_TO_TUPLE, (sequence,), state, selectors=(self.site('args'),))

    def call_keyword_run(self, region, items, state):
        mapping, pairs = None, []
        if len(items) * 2 > self.rules.call_profile['stack_guideline']:
            mapping, state = self.protocol(region, K.BUILD_MAP, (), state,
                (CountBinding('pair_count', 0),), tuple(arg for arg, _, _ in items))
        for arg, value, _ in items:
            key, state = self.emit(region, P.ConstructValue(P.ConstructionKind.LITERAL, (arg,)),
                                   (state,), (_REF, self.world), source=arg)
            ref, state = self.evaluate(region, value, state)
            if mapping is None:
                pairs.extend((key, ref))
            else:
                state, = self.protocol(region, K.MAP_ADD, (mapping, key, ref), state, selectors=(arg, value))
        if mapping is None:
            return self.protocol(region, K.BUILD_MAP, tuple(pairs), state,
                (CountBinding('pair_count', len(items)),), tuple(arg for arg, _, _ in items))
        return mapping, state
