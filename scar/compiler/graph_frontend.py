"""Lower admitted F4 body plans into the guarded CPU array-region profile.

Operation semantics, order, bindings and returns come exclusively from original
production plans and their UnitFacts. F2 supplies source coordinates; compiling
retained F0 bytes supplies code identity only. No target code is executed.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from hashlib import sha256
import math
from pathlib import Path
from types import CodeType

from scar.analysis.program_view import ProgramView
from scar.analysis.source_body_interfaces import BodyInterfaceResolver
from scar.analysis.source_bytes import read_source_bytes
from scar.analysis.source_reference_slice import source_port
from scar.analysis.static_query import _Fragments
from scar.compiler.model import ArrayRegion, Expr, SourceRef
from scar.ir.program import source_productions as P, normal_links as F, normal_graph as G
from scar.ir.program.control import LanguageCompletionKind as C
from scar.ir.program.normal_targets import Body
from scar.ir.program.source_syntax import SourceSyntaxMaterial
from scar.ir.record_codec import decode, encode
from scar.trace.code_snapshot import code_key


_WORLD, _ENV = object(), object()
_OPS = {'Add': 'add', 'Sub': 'sub', 'Mult': 'mul', 'Div': 'div', 'USub': 'neg'}


@dataclass(frozen=True)
class _Array:
    node: str


@dataclass(frozen=True)
class _Scalar:
    value: object
    origin: dict


@dataclass(frozen=True)
class _Slice:
    bounds: tuple


class GraphRegionRejected(ValueError):
    def __init__(self, code, detail, origin=None):
        self.code, self.detail, self.origin = code, detail, origin
        super().__init__(detail)


def _reject(code, detail, origin=None):
    raise GraphRegionRejected(code, detail, origin)


def _origin(context, region, step=None, **extra):
    result = dict(kind='original_f4', unit=context.unit, template=encode(context.key),
        region=region.wire, **extra)
    if step is not None:
        result.update(step=step.id.wire, source=encode(step.source, record_tags=P.PRODUCTION_RECORD_TAGS),
            results=[encode(context.gp(context.emitter.port(step.id,G.PortKind.RESULT,i,completion)))
                for completion in step.completions for i in range(len(completion.types))])
        if type(step.instruction) is P.AccessBinding:
            result['binding_port'] = step.instruction.port
    return result


class _GraphLowerer:
    """Walk every action in a bounded straight-line body, including dead work."""
    def __init__(self, source, function, resolver):
        self.source, self.function, self.resolver = source, function, resolver
        self.facts = source.facts
        self.nodes, self.origins, self.locals = [], [], {}
        self.by_id, self.active = {}, set()
        self.operations = {source_port(self.facts, row.result).port: row for row in self.facts.operations}
        self.constants = {source_port(self.facts, row.value).port: row.literal for row in self.facts.constants}
        self.names = defaultdict(list)
        for row in self.facts.names:
            self.names[source_port(self.facts, row.value).port, row.write].append(row.namespace)

    def emit(self, op, origin, inputs=(), attrs=None):
        node = Expr('n'+str(len(self.nodes)), op, tuple(inputs), {} if attrs is None else attrs)
        self.nodes.append(node); self.by_id[node.id] = node
        self.origins.append(dict(origin, expression=node.id))
        return _Array(node.id)

    def scalar_node(self, value):
        if isinstance(value, _Array):
            return value.node
        if not isinstance(value, _Scalar):
            _reject('UNSUPPORTED_OPERAND', 'arithmetic requires an ndarray or finite numeric literal')
        numeric = value.value
        if (type(numeric) not in (int, float)
                or type(numeric) is int and abs(numeric) > 2**53
                or type(numeric) is float and not math.isfinite(numeric)):
            _reject('UNSUPPORTED_CONSTANT', 'numeric constants must be finite and integers exactly representable in float64', value.origin)
        return self.emit('const', value.origin, attrs={'value': numeric}).node

    def binding(self, context, step, args):
        write = step.instruction.action is P.BindingActionKind.WRITE
        if step.instruction.action not in (P.BindingActionKind.READ, P.BindingActionKind.WRITE):
            _reject('UNSUPPORTED_BINDING', 'binding deletion is outside the pure-array profile')
        port = context.value(step.arguments[0]).port if write else context.result(step).port
        namespaces = tuple(dict.fromkeys(self.names.get((port, write), ())))
        if not namespaces or any(ns.kind is not F.NamespaceKind.LEXICAL for ns in namespaces):
            _reject('EXTERNAL_BINDING', 'namespace access is not an original local lexical binding')
        if write:
            for namespace in namespaces:
                self.locals[namespace] = args[0]
            return (_WORLD,)
        if len(namespaces) != 1 or namespaces[0] not in self.locals:
            _reject('UNBOUND_LOCAL', 'local read has no preceding parameter or assignment binding')
        return (self.locals[namespaces[0]], _WORLD)

    def action(self, context, step, args, origin):
        ins = step.instruction
        if ins.action in (P.LanguageActionKind.BINARY, P.LanguageActionKind.UNARY):
            operation = self.operations.get(context.result(step).port)
            if operation is None or operation.selector.value not in _OPS:
                _reject('UNSUPPORTED_OPERATOR', 'operation has no supported original normalized selector', origin)
            if (operation.action.value != ins.action.value or
                    tuple(source_port(self.facts,index).port for index in operation.operands) !=
                    tuple(context.value(value).port for value in step.arguments[:-1])):
                _reject('OPERATION_FACT_MISMATCH', 'normalized operation operands differ from the original F4 action',origin)
            selector = operation.selector.value
            operands = args[:-1]
            expected = 1 if selector == 'USub' else 2
            if len(operands) != expected:
                _reject('OPERATOR_ARITY', 'original array operator arity differs', origin)
            if selector == 'USub' and isinstance(operands[0], _Scalar):
                value = operands[0].value
                if type(value) not in (int, float):
                    _reject('UNSUPPORTED_CONSTANT', 'unary minus requires a numeric value', origin)
                return (_Scalar(-value, origin), _WORLD)
            if not any(isinstance(value, _Array) for value in operands):
                _reject('SCALAR_ARITHMETIC', 'computed scalar arithmetic is outside this array profile', origin)
            ids = tuple(self.scalar_node(value) for value in operands)
            return (self.emit(_OPS[selector], origin, ids), _WORLD)
        if ins.action is P.LanguageActionKind.ITEM_GET:
            if len(args) != 3 or not isinstance(args[0], _Array) or type(args[1]) is not tuple or len(args[1]) != 2:
                _reject('UNSUPPORTED_SLICE', 'indexing requires two original constant-bound slice axes', origin)
            base = self.by_id[args[0].node]
            if base.op not in ('input', 'slice') or any(not isinstance(axis, _Slice) for axis in args[1]):
                _reject('UNSUPPORTED_SLICE', 'slices must address an input array or its slice', origin)
            bounds = [list(axis.bounds) for axis in args[1]]
            return (self.emit('slice', origin, (base.id,), {'bounds': bounds}), _WORLD)
        _reject('UNSUPPORTED_ACTION', ins.action.value+' is outside the pure-array profile', origin)

    def construct(self, context, step, args, evaluated, origin):
        ins = step.instruction
        if ins.construction is P.ConstructionKind.LITERAL:
            literal = self.constants.get(context.result(step).port)
            if literal is None:
                _reject('LITERAL_FACT_MISSING', 'literal has no admitted original constant fact', origin)
            value = literal.to_python()
            if value is not None and type(value) not in (int,float):
                _reject('UNSUPPORTED_CONSTANT', 'only numeric literals and slice None are admitted', origin)
            return (_Scalar(value, origin), _WORLD)
        if ins.construction is P.ConstructionKind.SLICE:
            bounds = []
            for field in ins.payload:
                item = evaluated.get(field, _Scalar(None, origin))
                if not isinstance(item, _Scalar) or (item.value is not None and
                        (type(item.value) is not int or abs(item.value) > 2**63-1)):
                    _reject('NONCONSTANT_SLICE', 'slice bounds must be original int64 literals or None', origin)
                bounds.append(item.value)
            if len(bounds) != 3 or bounds[2] not in (None, 1):
                _reject('UNSUPPORTED_SLICE_STEP', 'only original unit-step slices are admitted', origin)
            return (_Slice(tuple(bounds[:2])), _WORLD)
        if ins.construction is P.ConstructionKind.TUPLE and ins.tuple_layout is P.TupleConstructionLayout.ITEMS:
            if not all(isinstance(value, _Slice) for value in args[:-1]):
                _reject('UNSUPPORTED_TUPLE', 'only tuples of slice selectors are admitted', origin)
            return (tuple(args[:-1]), _WORLD)
        _reject('UNSUPPORTED_CONSTRUCTION', ins.construction.value+' is outside this array profile', origin)

    def run(self, context, region_id, parameters):
        identity = context.key, region_id
        if identity in self.active:
            _reject('CYCLIC_BODY', 'recursive production control is outside the bounded straight-line profile')
        if context.owner(region_id).owner != self.function.body_scope.owner:
            _reject('CODE_SCOPE_CROSSING', 'operation crosses the original function code owner')
        region = context.regions[region_id]
        if len(parameters) != len(region.parameters):
            _reject('REGION_ARITY', 'original production region parameter count differs')
        self.active.add(identity)
        values = {P.ProductionParameter(region_id, i): value for i, value in enumerate(parameters)}
        evaluated = {}
        try:
            for step_id in region.steps:
                step = context.steps[step_id]; ins = step.instruction
                origin = _origin(context, region_id, step,
                    arguments=[encode(context.value(value)) for value in step.arguments])
                self.origins.append(origin)
                args = tuple(values[value] for value in step.arguments)
                if type(ins) is P.TransferCompletion:
                    if ins.kind not in (C.FALLTHROUGH, C.RETURN):
                        _reject('UNSUPPORTED_COMPLETION', 'only ordinary fallthrough and return are admitted', origin)
                    return ins.kind, args
                if type(ins) is P.EvaluateChild:
                    link = self.source.material.interfaces['links'][context.key, step.id]
                    child = self.resolver.plan(self.source.unit, link.callee)
                    kind, result = self.run(child, child.plan.root, args)
                    if kind is not C.FALLTHROUGH:
                        return kind, result
                    if result: evaluated[ins.field] = result[0]
                elif type(ins) is P.ApplyRegion:
                    kind, result = self.run(context, ins.invocation.region,
                        tuple(values[value] for value in ins.invocation.arguments))
                    if kind is not C.FALLTHROUGH:
                        return kind, result
                elif type(ins) is P.EnterDeferredBody:
                    result = (_WORLD,)
                elif type(ins) is P.AccessBinding:
                    result = self.binding(context, step, args)
                elif type(ins) is P.ConstructValue:
                    result = self.construct(context, step, args, evaluated, origin)
                elif type(ins) is P.DefineLiteral:
                    result = (_Scalar(ins.value.to_python(), origin),)
                elif type(ins) is P.ApplyLanguageAction:
                    result = self.action(context, step, args, origin)
                elif type(ins) is P.ApplyPythonProtocol and ins.protocol.value == 'FRAME_RELEASE_TEMPORARY':
                    # Exact ndarray/numeric/slice values have no user destructor.
                    result = (_WORLD,)
                else:
                    _reject('UNSUPPORTED_INSTRUCTION', type(ins).__name__+' may contain control, calls or state effects', origin)
                normal = next((completion for completion in step.completions if completion.kind is C.FALLTHROUGH), None)
                if normal is None or len(result) != len(normal.types):
                    _reject('RESULT_ARITY', 'lowered result differs from original fallthrough ABI', origin)
                for i, value in enumerate(result): values[P.ProductionResult(step.id, i)] = value
            _reject('MISSING_TRANSFER', 'original body region has no final transfer')
        finally:
            self.active.remove(identity)

    def lower(self):
        function = self.function
        if (function.body_scope is None or function.environment.kind is not P.DeferredBodyKind.FUNCTION
                or function.environment.captures or function.environment.owned_cells):
            _reject('UNSUPPORTED_ENVIRONMENT', 'only ordinary functions with local parameter bindings are admitted')
        if any(parameter.kind.value in ('VAR_POSITIONAL', 'VAR_KEYWORD') for parameter in function.environment.parameters):
            _reject('VARIADIC_SIGNATURE', 'variadic arguments are outside the fixed-array profile')
        context = self.resolver.plan(self.source.unit, function.template)
        self.check_decorators(context)
        arguments = [_ENV]
        for i, name in enumerate(function.parameter_names):
            formal = source_port(self.facts, function.formals[i+1])
            value = self.emit('input', _origin(context, function.body, value=encode(formal)), attrs={'name': name, 'index': i})
            arguments.append(value)
            namespaces = self.names.get((formal.port, True), ())
            if len(namespaces) != 1 or namespaces[0].kind is not F.NamespaceKind.LEXICAL:
                _reject('PARAMETER_BINDING', 'array formal has no unique original lexical binding')
            self.locals[namespaces[0]] = value
        arguments.append(_WORLD)
        kind, result = self.run(context, function.body, tuple(arguments))
        if kind is not C.RETURN or len(result) != 2 or not isinstance(result[0], _Array):
            _reject('SCALAR_OR_MISSING_RETURN', 'body must return a fresh ndarray computation')
        output = result[0].node
        if self.by_id[output].op in ('input', 'slice'):
            _reject('ALIASED_OUTPUT', 'returning an input/view violates fresh-output semantics')
        needed, pending = set(), [output]
        while pending:
            key = pending.pop()
            if key not in needed:
                needed.add(key); pending.extend(self.by_id[key].inputs)
        if any(node.id not in needed and node.op not in ('input', 'const') for node in self.nodes):
            _reject('UNUSED_ARRAY_WORK', 'discarded original array operations may still raise NumPy exceptions')
        return tuple(self.nodes), output, tuple(self.origins)

    def check_decorators(self, context):
        """Recognize the existing bare staticmethod allowance through F4 reads."""
        for step in context.plan.steps:
            if type(step.instruction) is not P.ApplyDecorator:
                continue
            origin = _origin(context,step.region,step)
            value = step.arguments[0]
            producer = context.steps.get(value.step) if type(value) is P.ProductionResult else None
            if producer is None or type(producer.instruction) is not P.EvaluateChild:
                _reject('UNSUPPORTED_DECORATOR', 'decorator is not a bare staticmethod binding read',origin)
            link = self.source.material.interfaces['links'][context.key,producer.id]
            child = self.resolver.plan(self.source.unit,link.callee)
            instructions = [child.steps[key] for key in child.regions[child.plan.root].steps]
            reads = [row for row in instructions if type(row.instruction) is P.AccessBinding
                and row.instruction.action is P.BindingActionKind.READ]
            if (len(reads) != 1 or any(type(row.instruction) not in (P.AccessBinding,P.TransferCompletion)
                    for row in instructions)):
                _reject('UNSUPPORTED_DECORATOR', 'only a bare staticmethod binding read is admitted',origin)
            namespaces = self.names.get((child.result(reads[0]).port,False),())
            if not namespaces or any(namespace.name != 'staticmethod' for namespace in namespaces):
                _reject('UNSUPPORTED_DECORATOR', 'only bare staticmethod is admitted',origin)
            self.origins.append(origin)


def _source_identity(catalog, unit):
    """Recover metadata only; this compiler output never selects IR semantics."""
    facts = catalog.fact_store
    model = facts.model_units[unit]
    reader = _Fragments(Path(facts.model_for(unit)))
    f0 = reader.read(model['artifacts']['source_bytes'])
    raw = read_source_bytes(f0)
    syntax = decode(SourceSyntaxMaterial, reader.read(model['artifacts']['source_syntax']))
    if syntax.status != 'PARSED' or syntax.input.raw_sha256 != sha256(raw).hexdigest():
        _reject('SOURCE_IDENTITY_MISMATCH', 'retained F0 bytes and F2 source identity differ')
    profile = getattr(catalog, 'replay_profiles', {}).get(unit)
    recipe = (profile['recipe'] if profile is not None else
        dict(filename=model['path'], mode='exec', flags=0, dont_inherit=True, optimize=0))
    root = compile(raw, recipe['filename'], recipe['mode'], flags=recipe['flags'],
        dont_inherit=True, optimize=recipe['optimize'])
    if profile is not None and code_key(root) != profile['root_code']['key']:
        _reject('SOURCE_IDENTITY_MISMATCH', 'compile-only identity differs from the retained root code mapping')
    objects, pending = [], [root]
    while pending:
        code = pending.pop(); objects.append(code)
        pending.extend(value for value in code.co_consts if type(value) is CodeType)
    return model, syntax, objects, recipe, sha256(raw).hexdigest()


def _metadata(syntax, occurrence):
    row = syntax.nodes[occurrence]
    schema = next(schema for schema in syntax.profile.ast_schema if schema.name == row.constructor)
    fields = dict(zip(schema.fields, row.fields)); attributes = dict(zip(schema.attributes, row.attributes))
    name = fields['name'].scalar.to_python() if 'name' in fields else None
    span = {label: attributes[field].scalar.to_python() for label, field in
        [('line','lineno'),('column','col_offset'),('end_line','end_lineno'),('end_column','end_col_offset')]}
    lines = {span['line']}
    if 'decorator_list' in fields:
        for value in fields['decorator_list'].items:
            if value.kind == 'NODE': lines.add(_metadata_span(syntax, value.reference)['line'])
    return name, span, lines


def _metadata_span(syntax, occurrence):
    row = syntax.nodes[occurrence]
    schema = next(schema for schema in syntax.profile.ast_schema if schema.name == row.constructor)
    attrs = dict(zip(schema.attributes,row.attributes))
    return {'line': attrs['lineno'].scalar.to_python()}


def discover_graph_regions(catalog, source=None) -> tuple[list[ArrayRegion], list[dict]]:
    """Lower requested admitted source bodies; retain every original ID in origins."""
    view = catalog if isinstance(catalog, ProgramView) else ProgramView(catalog)
    catalog = view.catalog
    units = (tuple(catalog.fact_store.rows) if source is None else
        tuple(sorted(catalog.units_for_source(str(Path(source).absolute())) or ())))
    regions, rejected = [], []
    if source is not None and not units:
        return regions, [dict(path=str(Path(source).absolute()),code='SOURCE_NOT_IN_CATALOG',
            reason='SOURCE_NOT_IN_CATALOG',detail='source has no admitted units in this catalog')]
    resolver = BodyInterfaceResolver(view)
    for unit in units:
        source_view = view.unit(unit); functions = source_view.facts.functions
        resolver.prepare_many(Body(unit, function.template, function.body) for function in functions)
        try:
            model, syntax, codes, recipe, raw_digest = _source_identity(catalog, unit)
        except (ValueError, KeyError, SyntaxError, OSError) as error:
            rejected.append(dict(unit=unit, code='SOURCE_IDENTITY_UNAVAILABLE', detail=str(error)))
            continue
        for ordinal, function in enumerate(functions):
            name, span, lines = _metadata(syntax, function.template.occurrence)
            candidates = [code for code in codes if code.co_name == name and code.co_firstlineno in lines
                and code.co_varnames[:code.co_argcount+code.co_kwonlyargcount] == function.parameter_names]
            base = dict(unit=unit, function=ordinal, template=encode(function.template),
                region=function.body.wire, path=model['path'], sha256=raw_digest, **span)
            try:
                if len(candidates) != 1:
                    _reject('CODE_IDENTITY_UNAVAILABLE', 'original function has no unique complete code identity')
                code = candidates[0]
                lowerer = _GraphLowerer(source_view, function, resolver)
                nodes, output, origins = lowerer.lower()
                key = code_key(code)
                identity = dict(kind='source_identity', method='COMPILE_ONLY_RETAINED_F0',
                    semantic_authority='ORIGINAL_F4_PRODUCTION_PLANS_AND_UNIT_FACTS', unit=unit,
                    f0_sha256=model['artifacts']['source_bytes']['decoded_sha256'],
                    f2_sha256=model['artifacts']['source_syntax']['decoded_sha256'],
                    occurrence=function.template.occurrence, span=span, recipe=recipe, code_key=key)
                reference = SourceRef(model['path'], raw_digest,
                    code.co_qualname, span['line'], span['column'], key, (identity, *origins))
                region_id = 'graph-array-region:'+sha256((unit+'\0'+function.body.wire+'\0'+key).encode()).hexdigest()[:24]
                regions.append(ArrayRegion(region_id, reference, function.parameter_names, nodes, output))
            except GraphRegionRejected as error:
                rejected.append(dict(base, qualname=candidates[0].co_qualname if len(candidates)==1 else name,
                    code=error.code, reason=error.code, detail=error.detail, origin=error.origin))
    return regions, rejected


__all__ = ['discover_graph_regions']
