"""Static context interfaces over finite shared source-recipe templates.

No code is executed and no native context is guessed. An edge denotes a
symbolic environment qualification at a schema-addressed reference site.
Concrete code/path/offset bindings are a separate compilation query.
"""
from dataclasses import fields
from functools import lru_cache

from scar.ir.program import source_productions as P


def _require(condition, path, detail):
    if not condition:
        from scar.analysis.source_productions import ProductionError
        raise ProductionError('COMPILATION_FLOW', str(path), detail)


@lru_cache(None)
def _field(kind, name):
    return P.CompilationPathPart(P.CompilationPathKind.FIELD,
        tuple(f.name for f in fields(kind)).index(name))


def _at(record, name):
    return (_field(type(record), name),)


def _item(index):
    return P.CompilationPathPart(P.CompilationPathKind.ITEM, index)


_DECLARATIONS = (P.DeferRegion, P.DeferClassBody, P.BuildFunctionAnnotations,
    P.BuildLazyExpression, P.BuildClassAnnotations, P.BuildScopeAnnotations)


def references(instruction):
    """Enumerate entry references, excluding values and completion targets.

    A break/continue target is a control destination, not a new template entry.
    Call argument ProductionParameter.region references likewise are not calls.
    Paths address the exact field/tuple slot in the pinned instruction schema.
    """
    K = P.CompilationEdgeKind
    if type(instruction) is P.EvaluateChild:
        yield (), K.CHILD, instruction
    elif type(instruction) in _DECLARATIONS:
        yield _at(instruction, 'body'), K.CODE_DECLARATION, instruction.body
    elif type(instruction) in (P.ApplyRegion, P.InvokeTypeParameterFactory):
        kind = K.TYPE_FACTORY if type(instruction) is P.InvokeTypeParameterFactory else K.CALL
        yield _at(instruction, 'invocation') + _at(instruction.invocation, 'region'), kind, instruction.invocation.region
    elif type(instruction) is P.BranchControl:
        for name in ('on_true', 'on_false'):
            call = getattr(instruction, name)
            yield _at(instruction, name) + _at(call, 'region'), K.CALL, call.region
    elif type(instruction) is P.LoopControl:
        condition = instruction.condition; path = _at(instruction, 'condition')
        if type(condition) is P.ProductionRegionID:
            yield path, K.LOOP_CONDITION, condition
        elif type(condition) is P.IterationCondition:
            yield path + _at(condition, 'advance') + _at(condition.advance, 'region'), K.LOOP_CONDITION, condition.advance.region
            yield path + _at(condition, 'exhausted'), K.LOOP_EXIT, condition.exhausted
        yield _at(instruction, 'body'), K.LOOP_BODY, instruction.body
        if instruction.otherwise is not None:
            yield _at(instruction, 'otherwise'), K.LOOP_EXIT, instruction.otherwise
    elif type(instruction) is P.HandleCompletions:
        yield _at(instruction, 'protected') + _at(instruction.protected, 'region'), K.CALL, instruction.protected.region
        for index, route in enumerate(instruction.routes):
            yield _at(instruction, 'routes') + (_item(index),) + _at(route, 'handler'), K.COMPLETION_HANDLER, route.handler
    elif type(instruction) is P.SuspendExecution:
        for index, route in enumerate(instruction.routes):
            yield _at(instruction, 'routes') + (_item(index),) + _at(route, 'region'), K.RESUME, route.region


def _uses(plan):
    for step in plan.steps:
        instruction = step.instruction
        if type(instruction) is P.ReadCompilationOption:
            yield P.CompilationFactUse(step.id, instruction.option)
        elif type(instruction) in (P.ReadCompilationAnnotationIndex, P.AddAnnotationIndex):
            # Literal singleton indices still retain the source/compiler fact.
            yield P.CompilationFactUse(step.id, instruction.parameter.publication.annotation)


def _transition(caller, target):
    return (P.CompilationTransition.QUALIFY_SITE if caller.code_scope == target.code_scope
        else P.CompilationTransition.ENTER_CODE)


def _edges(plan, ports, child):
    for step in plan.steps:
        caller = ports[step.region]
        for path, kind, target in references(step.instruction):
            destination = child(target) if type(target) is P.EvaluateChild else target
            context = destination if type(destination) is P.CompilationChildTarget else ports[destination]
            yield P.CompilationContextEdge(step.id, path, kind, destination, _transition(caller, context))


def _entry_scope(instruction):
    if type(instruction) in (P.EnterDeferredBody, P.EnterTypeParameters, P.EnterEvaluationRequest):
        return instruction.environment.scope
    if type(instruction) in (P.EnterRootBody, P.EnterClassBody):
        return instruction.interface.scope
    return None


class CompilationFlowIndex:
    def __init__(self, source):
        self.source = source
        self._code_scopes = {}

    def code_scope(self, scope):
        """Inline scopes share their parent's code unit, not its namespace."""
        topology = self.source.frontend.topology
        chain = []; current = scope
        while current not in self._code_scopes:
            _require(type(current) is int and 0 <= current < len(topology.scopes), scope, 'source scope outside original topology')
            row = topology.scopes[current]
            chain.append(current)
            if row.disposition != 'INLINED':
                self._code_scopes[current] = current
                break
            _require(row.block is not None, scope, 'inlined scope needs its original compiler block')
            block = topology.blocks[row.block]
            parent = block.parent
            while parent is not None and topology.blocks[parent].source_scope is None:
                parent = topology.blocks[parent].parent
            _require(parent is not None, scope, 'inlined scope must have a source code owner')
            current = topology.blocks[parent].source_scope
            _require(current not in chain, scope, 'cyclic inlined code ownership')
        owner = self._code_scopes[current]
        for original in chain:
            self._code_scopes[original] = owner
        return owner

    def build(self, plan):
        regions = {r.id: r for r in plan.regions}; steps = {s.id: s for s in plan.steps}; ports = {}
        for initial in plan.regions:
            chain = []; seen = set(); current = initial.id
            while current not in ports:
                _require(current not in seen, current, 'cyclic region ownership')
                seen.add(current); region = regions[current]; chain.append(region)
                if region.parent is None:
                    break
                current = region.parent
            for region in reversed(chain):
                scope = _entry_scope(steps[region.steps[0]].instruction)
                if scope is None:
                    scope = (ports[region.parent].source_scope if region.parent is not None else region.context.environment)
                ports[region.id] = P.CompilationContextPort(region.id, scope, self.code_scope(scope))

        def child(instruction):
            scope = self.source.context.context_at_slot(instruction.field).state.environment
            return P.CompilationChildTarget(instruction.field, instruction.purpose, scope, self.code_scope(scope))

        return P.CompilationContextFlow(tuple(ports[r.id] for r in plan.regions),
            tuple(_edges(plan, ports, child)), tuple(_uses(plan)))


def validate_flow(plan):
    """Check exact finite reference coverage; original scope proof is separate."""
    flow = plan.compilation_flow
    if flow is None:
        return
    _require(tuple(p.region for p in flow.ports) == tuple(r.id for r in plan.regions), 'ports', 'one ordered context port is required per region')
    ports = {p.region: p for p in flow.ports}
    _require(all(p.source_scope >= 0 and p.code_scope >= 0 for p in flow.ports), 'ports', 'negative scope')
    expected = [(step, path, kind, target) for step in plan.steps for path, kind, target in references(step.instruction)]
    _require(len(flow.edges) == len(expected), 'edges', 'entry reference coverage differs')
    for edge, (step, path, kind, target) in zip(flow.edges, expected):
        _require((edge.step, edge.path, edge.kind) == (step.id, path, kind), step.id, 'reference identity/path/kind differs')
        if type(target) is P.EvaluateChild:
            _require(type(edge.target) is P.CompilationChildTarget and edge.target.field == target.field
                and edge.target.purpose is target.purpose and edge.target.source_scope >= 0 and edge.target.code_scope >= 0,
                step.id, 'external child interface differs')
            destination = edge.target
        else:
            _require(edge.target == target and target in ports, step.id, 'local target differs')
            destination = ports[target]
        _require(edge.transition is _transition(ports[step.region], destination), step.id, 'code environment transition differs')
        if kind not in (P.CompilationEdgeKind.CHILD, P.CompilationEdgeKind.CODE_DECLARATION, P.CompilationEdgeKind.TYPE_FACTORY):
            _require(edge.transition is P.CompilationTransition.QUALIFY_SITE, step.id, 'control edge cannot change its code unit')
    _require(flow.uses == tuple(_uses(plan)), 'uses', 'compilation fact use coverage differs')
