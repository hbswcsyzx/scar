"""Scoped synchronous comprehensions using shared iterator-loop templates.

Reference-valued invariant ports do not certify invariant referent contents.
The changing namespace/container/iterator state remains in the carried world.
Physical inlining, frame cleanup and escaped-cell lifetime are not proved here.
"""
from scar.analysis.source_expression_rules import _REF, _BOOL, _require
from scar.ir.program import source_productions as P
from scar.ir.program.signature_patterns import CountBinding, ChoiceBinding
from scar.ir.program.structured import PythonProtocolKind as K


def comprehension_clauses(b):
    generators = b.value(b.site('generators'))
    _require(generators.kind == 'LIST' and bool(generators.items), 'RULE_SHAPE', str(b.occurrence),
             'comprehension requires at least one original clause')
    b.mark('generators', P.ProductionDispositionKind.EVALUATED_CHILD)
    clauses = []
    for item in generators.items:
        _require(item.kind == 'NODE' and b.rules.source.context.syntax.nodes[item.reference].constructor == 'comprehension',
                 'RULE_SHAPE', str(b.occurrence), 'expected an original comprehension descriptor')
        target = b.auxiliary(item.reference, 'target', P.ProductionDispositionKind.TARGET_ADDRESS)
        iterable = b.auxiliary(item.reference, 'iter', P.ProductionDispositionKind.EVALUATED_CHILD)
        filters = b.auxiliary(item.reference, 'ifs', P.ProductionDispositionKind.EVALUATED_CHILD)
        asynchronous = b.auxiliary(item.reference, 'is_async', P.ProductionDispositionKind.METADATA)
        raw = b.value(asynchronous)
        _require(raw.kind == 'SCALAR' and type(raw.scalar.to_python()) is int and raw.scalar.to_python() in (0, 1),
                 'RULE_SHAPE', str(asynchronous), 'async marker must be an explicit compiler flag')
        _require(raw.scalar.to_python() == 0, 'ASYNC_COMPREHENSION_FRONTIER', str(asynchronous),
                 'async clauses require suspension/async exhaustion rules')
        _require(b.value(filters).kind == 'LIST', 'RULE_SHAPE', str(filters), 'filters require an original expression list')
        clauses.append((target, iterable, filters))
    return clauses


def emit_comprehension(b, root, state):
    clauses = comprehension_clauses(b)
    output_names = ('key', 'value') if b.node.constructor == 'DictComp' else ('elt',)
    for name in output_names:
        b.mark(name, P.ProductionDispositionKind.EVALUATED_CHILD)
    # Only the outermost iterable is evaluated in the enclosing environment.
    iterable, state = b.evaluate(root, clauses[0][1], state)
    iterator, state = b.protocol(root, K.GET_ITERATOR, (iterable,), state, selectors=(clauses[0][1],))
    scope = b.region(b.site(output_names[0]), (_REF, b.world), root, P.ProductionRegionKind.COMPREHENSION)
    result = b.emit(root, P.ApplyRegion(P.ProductionRegionCall(scope.id, (iterator, state))), (), (_REF, b.world))
    b.finish(root, result, (_REF, b.world))

    world = b.parameter(scope, 1)
    kind = {'ListComp':'LIST', 'SetComp':'SET', 'DictComp':'DICT'}[b.node.constructor]
    build = {'LIST':K.BUILD_DISPLAY_LIST, 'SET':K.BUILD_SET_DISPLAY, 'DICT':K.BUILD_MAP}[kind]
    count = 'pair_count' if kind == 'DICT' else 'item_count'
    container, world = b.protocol(scope, build, (), world, (CountBinding(count, 0),), (b.site(output_names[0]),))
    world = emit_clause_loops(b, scope, clauses, b.parameter(scope, 0), world, container)
    b.finish(scope, (container, world), (_REF, b.world))


def emit_clause_loops(b, scope, clauses, initial, world, container=None):
    """One loop per clause; generator bodies have no synthetic container."""
    pending = []
    invariant_types = (_REF,) if container is None else (_REF, _REF)
    world_index = len(invariant_types)

    def inputs(iterator, container):
        return (iterator,) if container is None else (iterator, container)

    def unpack(region):
        return (b.parameter(region, 0), None if container is None else b.parameter(region, 1),
            b.parameter(region, world_index), b.parameter(region, world_index+1))

    def launch(parent, index, iterator, container, world):
        loop = b.region(clauses[index][0], (*invariant_types, b.world), parent, P.ProductionRegionKind.LOOP)
        pending.append((loop, index))
        world, = b.emit(parent, P.ApplyRegion(P.ProductionRegionCall(loop.id, (*inputs(iterator, container), world))), (), (b.world,))
        return world

    result = launch(scope, 0, initial, container, world)
    while pending:
        loop, index = pending.pop()
        target, iterable, filters = clauses[index]
        advance = b.region(target, (_REF, b.world), loop, P.ProductionRegionKind.LOOP_CONDITION)
        next_item = b.protocol(advance, K.COMPREHENSION_NEXT,
            (b.parameter(advance, 0),), b.parameter(advance, 1), selectors=(iterable,))
        b.finish(advance, next_item, (_REF, b.world))
        exhausted = b.region(target, b.raised, loop, P.ProductionRegionKind.HANDLER)
        stopped, = b.protocol(exhausted, K.MATCH_STOP_ITERATION,
            (b.parameter(exhausted, 0),), b.parameter(exhausted, len(b.raised)-1), selectors=(iterable,))
        b.finish(exhausted, (stopped,), (_BOOL,))
        body = b.region(target, (*loop.parameters, _REF), loop, P.ProductionRegionKind.LOOP_BODY)
        condition = P.IterationCondition(P.ProductionRegionCall(advance.id,
            (b.parameter(loop, 0), b.parameter(loop, world_index))), exhausted.id, world_index)
        b.emit(loop, P.LoopControl(condition, body.id, invariant_count=world_index),
            tuple(b.parameter(loop, i) for i in range(len(loop.parameters))), (b.world,))
        iterator, current_container, world, item = unpack(body)
        world, = b.evaluate(body, target, world, P.ProductionPurpose.STORE, item)
        for ordinal in range(len(b.value(filters).items)):
            site = P.SlotRef(filters.occurrence, filters.group, filters.ordinal, (ordinal,))
            value, world = b.evaluate(body, site, world)
            test, world = b.action(body, P.LanguageActionKind.TRUTH, (), (value, world), (_BOOL, b.world))
            skip = b.region(site, (b.world,), body)
            b.finish(skip, (b.parameter(skip, 0),), (b.world,))
            follow = b.region(site, body.parameters, body)
            b.emit(body, P.BranchControl(P.ProductionRegionCall(follow.id, (*inputs(iterator, current_container), world, item)),
                P.ProductionRegionCall(skip.id, (world,))), (test,), (b.world,))
            body = follow
            iterator, current_container, world, item = unpack(body)
        if index+1 < len(clauses):
            value, world = b.evaluate(body, clauses[index+1][1], world)
            nested, world = b.protocol(body, K.GET_ITERATOR, (value,), world, selectors=(clauses[index+1][1],))
            world = launch(body, index+1, nested, current_container, world)
        else:
            values = []
            output_names = ('key', 'value') if b.node.constructor == 'DictComp' else ('elt',)
            for name in output_names:
                value, world = b.evaluate(body, b.site(name), world)
                values.append(value)
            if current_container is None:
                from scar.analysis.source_suspension_rules import emit_suspension
                _, world = emit_suspension(b, body, P.SuspensionKind.YIELD, values[0], world)
            else:
                kind = {'ListComp':'LIST', 'SetComp':'SET', 'DictComp':'DICT'}[b.node.constructor]
                world, = b.protocol(body, K.COMPREHENSION_ADD, (current_container, *values), world,
                    (ChoiceBinding('comprehension_kind', kind),), tuple(b.site(name) for name in output_names))
        b.finish(body, (world,), (b.world,))
    return result
