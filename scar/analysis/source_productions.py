"""Closed source-recipe shapes and local graph references.

This is the input grammar for source lowering. Acceptance here does not prove
that a recipe implements its Python constructor, effects or cleanup semantics.
The canonical program graph remains the later lowering target.
"""
from dataclasses import fields
from hashlib import sha256
import json
from pathlib import Path, PurePosixPath
import sys

from scar.analysis.program_types import _build_types
from scar.ir.program import source_productions as P
from scar.ir.program.control import LanguageCompletionKind as C
from scar.ir.program.model import ValueKind, ValueType
from scar.ir.record_codec import decode, encode


class ProductionError(ValueError):
    def __init__(self, code, path, detail):
        self.code, self.path, self.detail = code, path, detail
        super().__init__(code + ' at ' + path + ': ' + detail)


def _require(condition, code, path, detail):
    if not condition:
        raise ProductionError(code, path, detail)


def _digest(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
        ensure_ascii=True, allow_nan=False).encode('ascii')).hexdigest()


def _record_children(members, value, path):
    for member in members:
        _require(hasattr(value, member['name']), 'RECORD_FIELD', path, 'missing declared field')
        yield member['type'], getattr(value, member['name']), path + '.' + member['name']


def _tuple_children(expressions, values, path, variadic):
    for index, value in enumerate(values):
        yield expressions[0] if variadic else expressions[index], value, path + '[' + str(index) + ']'


def production_type_catalog():
    root, rows, registry, counts = _build_types(P.SourceProductionPlan)
    modules = {cls.__module__: sha256(Path(sys.modules[cls.__module__].__file__).read_bytes()).hexdigest()
        for cls in registry.values()}
    modules[__name__] = sha256(Path(__file__).read_bytes()).hexdigest()
    for name in ('scar.analysis.program_types', 'scar.ir.record_codec'):
        modules[name] = sha256(Path(sys.modules[name].__file__).read_bytes()).hexdigest()
    payload = dict(schema='scar.source-production-type-catalog', schema_version=1,
        root=root, types=rows, counts=counts, modules=dict(sorted(modules.items())),
        instruction_variants=[kind.__name__ for kind in P.ProductionInstruction.__args__],
        authority='SOURCE_RECIPE_SHAPE_ONLY',
        source_rule_semantics_closed=False, canonical_graph_generated=False)
    return {**payload, 'content_sha256': _digest(payload)}


def read_production_type_catalog(document):
    expected = production_type_catalog()
    _require(_digest(document) == _digest(expected), 'CATALOG_MISMATCH', 'catalog', 'type declarations or source pins differ')
    return expected


def _shape(plan, max_visits):
    """Exact nominal walk over the generated finite grammar, never recursion."""
    _require(type(max_visits) is int and max_visits >= 0, 'QUERY_ARGUMENT', 'max_visits',
             'expected an exact nonnegative integer')
    root, declarations, registry, _ = _build_types(P.SourceProductionPlan)
    rows = {row['key']: row for row in declarations}
    atoms = {'NoneType': type(None), 'bool': bool, 'int': int, 'float': float, 'str': str, 'bytes': bytes}

    def accepts(expr, value):
        if expr['kind'] == 'REF':
            return type(value) is registry[expr['name']]
        if expr['kind'] == 'ATOM':
            return type(value) is atoms[expr['name']]
        return expr['kind'] in ('TUPLE', 'FIXED_TUPLE') and type(value) is tuple

    pending, active, visits = [('ENTER', root, plan, 'plan')], set(), 0
    while pending:
        action, expr, value, path = pending.pop()
        if action == 'LEAVE':
            active.remove(id(value))
            if expr is not None and hasattr(expr, '__post_init__'):
                try:
                    expr.__post_init__(value)
                except (ValueError, TypeError, AttributeError) as error:
                    raise ProductionError('CONSTRUCTOR_INVARIANT', path, str(error)) from error
            continue
        if action == 'CHILDREN':
            child = next(value, None)
            if child is not None:
                pending.append(('CHILDREN', None, value, path))
                pending.append(('ENTER', *child))
            continue
        _require(visits < max_visits, 'BUDGET_FRONTIER', path, 'recipe shape traversal limit')
        visits += 1
        if expr['kind'] == 'UNION':
            choices = [arg for arg in expr['args'] if accepts(arg, value)]
            _require(len(choices) == 1, 'TYPE_MISMATCH', path, 'expected one exact declared variant')
            expr = choices[0]
        _require(accepts(expr, value), 'TYPE_MISMATCH', path, 'value is outside its exact declared type')
        if expr['kind'] == 'ATOM':
            continue
        constructor = None
        if expr['kind'] == 'REF':
            cls, row = registry[expr['name']], rows[expr['name']]
            if row['kind'] == 'ENUM':
                _require(any(value is member for member in cls), 'TYPE_MISMATCH', path,
                         'enum must be a declared singleton')
                continue
            if row['kind'] == 'IDENTIFIER':
                _require(type(getattr(value, 'value', None)) is str and bool(value.value)
                    and type(value.prefix) is str and value.prefix == row['prefix'],
                         'IDENTIFIER_PAYLOAD', path, 'identifier payload or namespace differs')
                continue
            # Check fields first, then the reviewed original constructor.
            constructor = cls
            children = _record_children(row['fields'], value, path)
        else:
            variadic = expr['kind'] == 'TUPLE'
            _require(variadic or len(value) == len(expr['args']), 'TYPE_MISMATCH', path, 'fixed tuple length differs')
            children = _tuple_children(expr['args'], value, path, variadic)
        _require(id(value) not in active, 'VALUE_CYCLE', path, 'use graph IDs rather than cyclic value objects')
        active.add(id(value))
        pending.extend((('LEAVE', constructor, value, path), ('CHILDREN', None, children, path)))
    return visits


def validate_production_plan(plan, *, max_visits=1_000_000):
    """Check recipe structure, ownership, ordered values and local interfaces.

    Source field existence/context, constructor recipes, effect signatures and
    full control/cleanup semantics require separate source-rule replay.
    """
    visits = _shape(plan, max_visits)
    _require((plan.schema, plan.schema_version, plan.authority) == (
        'scar.source-production-plan', 1, 'SOURCE_RECIPE_SHAPE_ONLY'),
        'SCHEMA', 'plan', 'unsupported recipe schema or authority')
    source = plan.input
    _require(bool(source.path) and bool(source.namespace_root), 'INPUT', 'plan.input', 'source paths must be nonempty')
    _require(PurePosixPath(source.path).is_absolute() and PurePosixPath(source.namespace_root).is_absolute()
        and PurePosixPath(source.path).is_relative_to(source.namespace_root)
        and '..' not in PurePosixPath(source.path).parts
        and '..' not in PurePosixPath(source.namespace_root).parts,
        'INPUT', 'plan.input', 'original path must be within the absolute source namespace')
    for field in fields(source):
        if field.name.endswith('_sha256'):
            digest = getattr(source, field.name)
            _require(len(digest) == 64 and all(char in '0123456789abcdef' for char in digest),
                     'INPUT', 'plan.input.' + field.name, 'expected a lowercase SHA-256')
    regions, steps = {}, {}
    for table, rows in ((regions, plan.regions), (steps, plan.steps)):
        for row in rows:
            _require(row.id not in table, 'DUPLICATE_ID', str(row.id), 'duplicate local record identity')
            table[row.id] = row
    _require(plan.root in regions, 'DANGLING_REGION', 'plan.root', 'missing root region')
    _require(regions[plan.root].source == plan.source, 'SOURCE', 'plan.root', 'root and plan source differ')
    done = {plan.root}
    _require(regions[plan.root].parent is None, 'REGION_PARENT', 'plan.root', 'root must have no parent')
    for region in plan.regions:
        chain, active, current = [], set(), region.id
        while current not in done:
            _require(current in regions, 'DANGLING_REGION', str(region.id), 'unknown lexical parent')
            _require(current not in active, 'REGION_CYCLE', str(region.id), 'cyclic lexical ownership')
            chain.append(current)
            active.add(current)
            current = regions[current].parent
        done.update(chain)

    # One ownership index also proves loop-target ancestry, without repeated
    # scans of deep parent chains or expanding any loop iterations.
    children = {r.id: [] for r in plan.regions}
    for region in plan.regions:
        if region.parent is not None:
            children[region.parent].append(region.id)
    intervals, boundaries, clock = {}, {}, 0
    pending = [('ENTER', plan.root, None)]
    while pending:
        action, identity, boundary = pending.pop()
        if action == 'LEAVE':
            intervals[identity] = (intervals[identity][0], clock)
            continue
        if regions[identity].kind is P.ProductionRegionKind.DEFERRED:
            boundary = identity
        boundaries[identity] = boundary
        intervals[identity] = (clock, None)
        clock += 1
        pending.append(('LEAVE', identity, boundary))
        pending.extend(('ENTER', child, boundary) for child in reversed(children[identity]))

    def completions(rows, owner, path):
        result = {}
        _require(bool(rows), 'COMPLETION', path, 'declare at least one completion')
        for row in rows:
            key = row.kind, row.target
            _require(key not in result, 'COMPLETION', path, 'duplicate completion kind/target')
            if row.kind in (C.BREAK, C.CONTINUE):
                _require(row.target in regions and regions[row.target].kind is P.ProductionRegionKind.LOOP,
                         'COMPLETION', path, 'break/continue must target a declared loop')
                start, end = intervals[row.target]
                _require(owner in intervals and start <= intervals[owner][0] < end
                    and boundaries[owner] == boundaries[row.target],
                    'COMPLETION', path, 'loop target must enclose the region without crossing deferred code')
            else:
                _require(row.target is None, 'COMPLETION', path, 'only break/continue carry a loop target')
            result[key] = row.types
        return result

    _require(all(s.region in regions for s in plan.steps), 'STEP_OWNER', 'plan.steps', 'unknown region owner')
    region_outputs = {r.id: completions(r.completions, r.id, str(r.id)) for r in plan.regions}
    step_outputs = {s.id: completions(s.completions, s.region, str(s.id)) for s in plan.steps}
    claimed, referenced_regions = set(), {plan.root}
    for region in plan.regions:
        _require(bool(region.steps), 'REGION_EXIT', str(region.id), 'region needs an explicit result/transfer step')
        available = {}

        def value_type(value):
            if type(value) is P.ProductionParameter:
                _require(value.region == region.id and 0 <= value.index < len(region.parameters),
                         'VALUE_SCOPE', str(region.id), 'parameter belongs to another region or ordinal')
                return region.parameters[value.index]
            _require(value.step in available, 'VALUE_ORDER', str(region.id),
                     'value must be defined earlier in the same region')
            types = available[value.step].get((C.FALLTHROUGH, None), ())
            _require(0 <= value.index < len(types), 'VALUE_ORDINAL', str(value.step), 'missing normal result ordinal')
            return types[value.index]

        def child(identity, kind=None):
            _require(identity in regions and regions[identity].parent == region.id,
                     'REGION_REFERENCE', str(region.id), 'nested template must be owned by this region')
            target = regions[identity]
            referenced_regions.add(identity)
            _require(kind is None or target.kind is kind, 'REGION_KIND', str(identity), 'wrong nested region kind')
            return target

        def invoke(call):
            target = child(call.region)
            _require(tuple(value_type(v) for v in call.arguments) == target.parameters,
                     'PORT_TYPES', str(call.region), 'region call arguments differ from declared parameters')
            return region_outputs[target.id]

        for ordinal, identity in enumerate(region.steps):
            _require(identity in steps, 'DANGLING_STEP', str(region.id), 'owned step is missing')
            _require(identity not in claimed and steps[identity].region == region.id,
                     'STEP_OWNER', str(identity), 'step must be owned exactly once')
            claimed.add(identity)
            step, outputs = steps[identity], step_outputs[identity]
            args = tuple(value_type(v) for v in step.arguments)
            instruction = step.instruction
            if type(instruction) is P.AccessBinding:
                _require(instruction.port >= 0, 'SOURCE_PORT', str(identity), 'source port must be nonnegative')
            elif type(instruction) is P.ApplyRegion:
                _require(not args and invoke(instruction.invocation) == outputs, 'PORT_TYPES', str(identity),
                         'region application completions differ or duplicate explicit call arguments')
            elif type(instruction) is P.HandleCompletions:
                _require(not args and bool(instruction.routes), 'COMPLETION_ROUTE', str(identity),
                         'handler control uses explicit call/capture arguments and nonempty routes')
                protected = invoke(instruction.protected)
                merged, routed = {}, set()
                for route in instruction.routes:
                    key = route.kind, route.target
                    _require(key in protected and key not in routed, 'COMPLETION_ROUTE', str(identity),
                             'route must select one distinct declared protected completion')
                    routed.add(key)
                    handler = child(route.handler, P.ProductionRegionKind.HANDLER)
                    _require(handler.parameters == (*protected[key], *(value_type(v) for v in route.captures)),
                             'PORT_TYPES', str(identity), 'handler inputs must be payload followed by captures')
                    for result, types in region_outputs[handler.id].items():
                        _require(result not in merged or merged[result] == types, 'PORT_TYPES', str(identity),
                                 'handler completion interfaces disagree')
                        merged[result] = types
                for key, types in protected.items():
                    if key not in routed:
                        _require(key not in merged or merged[key] == types, 'PORT_TYPES', str(identity),
                                 'unhandled completion interface disagrees with handler output')
                        merged[key] = types
                _require(merged == outputs, 'PORT_TYPES', str(identity), 'handled completion union differs')
            elif type(instruction) is P.BranchControl:
                _require(args == (ValueType(ValueKind.DATA, 'builtins.bool'),), 'PORT_TYPES', str(identity),
                         'branch requires exactly one boolean decision')
                alternatives = {}
                for call in (instruction.on_true, instruction.on_false):
                    for key, types in invoke(call).items():
                        _require(key not in alternatives or alternatives[key] == types,
                                 'PORT_TYPES', str(identity), 'alternative completion interfaces disagree')
                        alternatives[key] = types
                _require(alternatives == outputs, 'PORT_TYPES', str(identity), 'branch completion union differs')
            elif type(instruction) is P.LoopControl:
                _require(region.kind is P.ProductionRegionKind.LOOP and args == region.parameters,
                         'LOOP_INTERFACE', str(identity), 'loop control needs its carried parameter interface')
                _require(0 <= instruction.invariant_count <= len(args), 'LOOP_INTERFACE', str(identity),
                         'invariant prefix must fit the explicit input interface')
                carried = args[instruction.invariant_count:]
                condition = child(instruction.condition, P.ProductionRegionKind.LOOP_CONDITION)
                body = child(instruction.body, P.ProductionRegionKind.LOOP_BODY)
                _require(condition.parameters == body.parameters == region.parameters,
                         'LOOP_INTERFACE', str(identity), 'loop condition/body carry ports differ')
                _require(region_outputs[condition.id].get((C.FALLTHROUGH, None)) == (
                    ValueType(ValueKind.DATA, 'builtins.bool'), *carried),
                    'LOOP_INTERFACE', str(identity), 'loop condition returns decision then carried values')
                for key in ((C.FALLTHROUGH, None), (C.CONTINUE, region.id), (C.BREAK, region.id)):
                    if key in region_outputs[body.id]:
                        _require(region_outputs[body.id][key] == carried,
                                 'LOOP_INTERFACE', str(identity), 'loop body backedge/exit carry ports differ')
                if instruction.otherwise is not None:
                    otherwise = child(instruction.otherwise, P.ProductionRegionKind.ALTERNATIVE)
                    _require(otherwise.parameters == region.parameters, 'LOOP_INTERFACE', str(identity),
                             'loop otherwise carry ports differ')
            elif type(instruction) is P.DeferRegion:
                child(instruction.body, P.ProductionRegionKind.DEFERRED)
            elif type(instruction) is P.CleanupControl:
                invoke(instruction.protected)
                child(instruction.cleanup, P.ProductionRegionKind.CLEANUP)
            elif type(instruction) is P.SuspendExecution:
                child(instruction.resume, P.ProductionRegionKind.RESUME)
            elif type(instruction) is P.TransferCompletion:
                _require(outputs == {(instruction.kind, instruction.target): args}
                    and region_outputs[region.id].get((instruction.kind, instruction.target)) == args,
                    'COMPLETION', str(identity), 'explicit transfer differs from region/step completion')
                _require(ordinal == len(region.steps) - 1, 'VALUE_ORDER', str(identity), 'transfer must end its region')
            if (C.FALLTHROUGH, None) not in outputs:
                _require(ordinal == len(region.steps) - 1, 'VALUE_ORDER', str(identity), 'no step may follow terminal control')
            available[identity] = outputs
        _require(available[region.steps[-1]] == region_outputs[region.id], 'REGION_EXIT', str(region.id),
                 'last step and declared region completion interfaces differ')
    _require(claimed == set(steps), 'STEP_OWNER', 'plan.steps', 'unowned steps remain')
    _require(referenced_regions == set(regions), 'REGION_REFERENCE', 'plan.regions', 'unreferenced region templates remain')
    sites = [item.field for item in plan.slots]
    _require(len(set(sites)) == len(sites), 'SOURCE_SLOT', 'plan.slots', 'each source slot gets one disposition')
    # Every source reference is nonnegative even when original material is not attached.
    for row in (*plan.regions, *plan.steps):
        if type(row.source) is P.ProductionOccurrence:
            _require(row.source.occurrence >= 0, 'SOURCE', str(row.id), 'negative source occurrence')
    return dict(complete=True, visits=visits, regions=len(regions), steps=len(steps),
        recipe_shape_checked=True, local_references_checked=True, source_rules_replayed=False,
        operation_signatures_checked=False, control_semantics_checked=False, rewrite_authorized=False)


class ProductionSourceIndex:
    """Reuse accepted F2/F3 views; do not parse, copy ASTs or replay F3 per plan.

    Construction checks input identity, not fresh upstream acceptance. Callers
    must obtain the views from the existing strict parent readers.
    """
    def __init__(self, f0, context_view, frontend_view):
        from scar.analysis.frontend_bindings import FrontendBindingView
        from scar.analysis.source_context_view import SourceContextView
        _require(type(context_view) is SourceContextView and type(frontend_view) is FrontendBindingView,
                 'INPUT', 'views', 'expected original typed F2/F3 views')
        syntax = context_view.syntax
        _require(type(f0) is dict and syntax.input.f0_document_sha256 == _digest(f0)
            and syntax.input.path == f0.get('path') and context_view.roles == frontend_view.roles
            and context_view.material == frontend_view.contexts,
            'INPUT_LINEAGE', 'views', 'views do not share the original source/context material')
        self.context, self.frontend = context_view, frontend_view
        self.roles = context_view.role_view
        self._role_sites = frozenset(port.site for port in frontend_view.roles.ports)
        self.input = P.ProductionInput(f0['path'], f0['namespace_root'], _digest(encode(syntax)),
            _digest(encode(context_view.roles)), _digest(encode(context_view.material)),
            _digest(encode(frontend_view.declarations)), _digest(encode(frontend_view.bindings)))

    def match(self, plan, *, max_visits=1_000_000):
        summary = validate_production_plan(plan, max_visits=max_visits)
        _require(plan.input == self.input, 'INPUT_LINEAGE', 'plan.input', 'recipe refers to different F2/F3 materials')

        def source(ref):
            if type(ref) is P.ProductionOccurrence:
                _require(0 <= ref.occurrence < len(self.context.syntax.nodes), 'SOURCE_REFERENCE', 'source',
                         'occurrence outside original F2')
                return self.context.entry_context(ref.occurrence)
            return self.context.context_at_slot(ref).state

        try:
            for region in plan.regions:
                _require(region.context == source(region.source), 'SOURCE_CONTEXT', str(region.id),
                         'region context differs from its original F2/F3 source reference')
            for step in plan.steps:
                source(step.source)
                instruction = step.instruction
                if type(instruction) is P.EvaluateChild:
                    _, value = self.roles.locate(instruction.field)
                    _require(instruction.field.group == 'FIELD' and value.kind in ('NODE', 'LIST'),
                             'SOURCE_REFERENCE', str(step.id), 'evaluated child must be an original child field')
                elif type(instruction) is P.ApplyLanguageAction:
                    for site in instruction.selectors:
                        self.roles.locate(site)
                elif type(instruction) is P.ConstructValue:
                    for site in instruction.payload:
                        self.roles.locate(site)
                elif type(instruction) is P.AccessBinding:
                    _require(0 <= instruction.port < len(self.frontend.roles.ports),
                             'SOURCE_PORT', str(step.id), 'port outside original F3 role table')
                    site = self.frontend.roles.ports[instruction.port].site
                    _require(site == step.source if type(step.source) is P.SlotRef else
                        site.occurrence == step.source.occurrence,
                        'SOURCE_PORT', str(step.id), 'binding port is from another source occurrence/slot')
                    binding = self.frontend.bindings.ports[instruction.port]
                    field = {P.BindingActionKind.READ: 'read_plan', P.BindingActionKind.WRITE: 'write_target',
                             P.BindingActionKind.DELETE: 'delete_target'}[instruction.action]
                    _require(getattr(binding, field) is not None, 'SOURCE_PORT', str(step.id),
                             'role port has no declared namespace access for this action')
            for disposition in plan.slots:
                self.roles.locate(disposition.field)
                if disposition.disposition is P.ProductionDispositionKind.ROLE_PORT:
                    _require(disposition.field in self._role_sites, 'SOURCE_PORT', 'plan.slots',
                             'role disposition must refer to an original F3 role port')
        except ProductionError:
            raise
        except (ValueError, TypeError, KeyError, IndexError) as error:
            raise ProductionError('SOURCE_REFERENCE', 'plan', str(error)) from error
        return {**summary, 'original_source_references_checked': True,
                'upstream_fresh_replayed': False}


def production_plan_document(plan, *, max_visits=1_000_000):
    validate_production_plan(plan, max_visits=max_visits)
    return encode(plan, record_tags=P.PRODUCTION_RECORD_TAGS)


def read_production_plan(document, *, max_visits=1_000_000):
    # Bound/cycle-check the untrusted wire before the recursive strict codec.
    _require(type(max_visits) is int and max_visits >= 0, 'QUERY_ARGUMENT', 'max_visits',
             'expected an exact nonnegative integer')
    pending, active, visits = [('ENTER', document)], set(), 0
    while pending:
        action, value = pending.pop()
        if action == 'LEAVE':
            active.remove(id(value))
            continue
        if action == 'CHILDREN':
            sentinel = object()
            child = next(value, sentinel)
            if child is not sentinel:
                pending.extend((('CHILDREN', value), ('ENTER', child)))
            continue
        _require(visits < max_visits, 'BUDGET_FRONTIER', 'document', 'wire traversal limit')
        visits += 1
        if type(value) not in (dict, list):
            _require(value is None or type(value) in (bool, int, str), 'WIRE_TYPE', 'document', 'unsupported wire scalar')
            continue
        _require(id(value) not in active, 'VALUE_CYCLE', 'document', 'cyclic wire object')
        active.add(id(value))
        children = _wire_children(value)
        pending.extend((('LEAVE', value), ('CHILDREN', children)))
    try:
        plan = decode(P.SourceProductionPlan, document, record_tags=P.PRODUCTION_RECORD_TAGS)
    except (ValueError, TypeError, AttributeError, RecursionError) as error:
        raise ProductionError('WIRE_SCHEMA', 'document', str(error)) from error
    validate_production_plan(plan, max_visits=max_visits)
    return plan


def _wire_children(value):
    if type(value) is dict:
        for key, child in value.items():
            _require(type(key) is str, 'WIRE_TYPE', 'document', 'non-string key')
            yield key
            yield child
    else:
        yield from value
