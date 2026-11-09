"""Track one lexical binding through matched shared recipe control states.

Only explicit name WRITE/DELETE normal exits kill definitions. All worldful
primitive operations can weakly introduce opaque effects. Neither missing
paths in this NORMAL_SUCCESS view nor exhausted budgets prove impossibility.
"""
from collections import defaultdict, deque

from scar.analysis.source_graph_material import source_graph_material
from scar.analysis.source_name_access_anchors import anchor_name_accesses
from scar.analysis.source_reference_slice import ReferenceSlicer, source_port
from scar.analysis.source_value_flow import project_value_flow
from scar.analysis.source_world_flow import _state
from scar.ir.program import normal_graph as G, normal_links as F, normal_targets as T
from scar.ir.program import source_productions as P, source_name_access_anchors as A, source_name_definitions as D
from scar.ir.program import source_value_flow as V
from scar.ir.program.control import LanguageCompletionKind as C


def _ids(bits):
    result = []
    while bits:
        bit = bits & -bits; result.append(bit.bit_length()-1); bits ^= bit
    return tuple(result)


def _exit(entry, completion=C.FALLTHROUGH, target=None):
    return G.Port(entry.template, entry.owner, G.PortKind.EXIT, completion=completion, target=target)


def reaching_name_definitions(snapshot, source_function, namespace, *, anchor_graph=None,
        material=None, flow=None, max_states=20000, max_stack=128, max_updates=1000000):
    """Track may definitions under original binding/frame and branch guards.

    Reuse a caller's original material/anchor graph/SourceBodyValueFlow when
    available. Injected flow records are reused after exact function, body and
    source-template artifact checks; the caller remains responsible for their
    original evidence and snapshot/anchor validation. Recipe stacks qualify
    shared regions, not Python invocations.
    """
    if (type(source_function) is not T.GlobalPort or type(namespace) is not F.Namespace
            or namespace.kind is not F.NamespaceKind.LEXICAL or type(namespace.owner) is not int
            or namespace.owner < 0 or type(namespace.name) is not str or not namespace.name):
        raise TypeError('name definitions require an original function and complete LEXICAL Namespace')
    if any(type(n) is not int or n < 1 for n in (max_states, max_stack, max_updates)):
        raise ValueError('name definition budgets must be positive integers')
    unit = snapshot.fact_store.load(source_function.unit)
    matches = [(i, f) for i, f in enumerate(unit.functions) if source_port(unit, f.value) == source_function]
    if len(matches) != 1 or matches[0][1].body_scope is None:
        raise ValueError('name definition source is not one scope-qualified original function')
    function_ordinal, function = matches[0]; scope = function.body_scope.owner
    body = T.Body(unit.unit, function.template, function.body)
    if material is None:
        material = source_graph_material(getattr(snapshot, 'catalog', snapshot), unit.unit)
    if material.fact_store is not snapshot.fact_store or material.unit != unit.unit:
        raise ValueError('name definition material belongs to another original fact catalog/unit')
    if anchor_graph is None:
        anchor_graph = anchor_name_accesses(snapshot, unit.unit, scopes=(scope,), material=material)
    if (type(anchor_graph) is not A.NameAccessAnchorGraph or anchor_graph.unit != unit.unit
            or scope not in anchor_graph.scopes or material.result_artifact not in anchor_graph.materials):
        raise ValueError('name definitions require the original unit/scope/material anchors')
    if flow is None:
        flow = project_value_flow(material, source_function, body)
    elif (type(flow) is not V.SourceBodyValueFlow or flow.source_function != source_function
            or flow.body != body or flow.source_templates != material.result_artifact):
        raise ValueError('name definition flow differs from its original function/body/material')
    edges = tuple(e for e in flow.edges if e.kind is G.EdgeKind.CONTROL)
    adjacency = defaultdict(list)
    for ordinal, edge in enumerate(edges): adjacency[edge.source].append(ordinal)
    slicer = ReferenceSlicer(snapshot); function_fact = slicer.fact(unit, 'functions', function_ordinal)
    root = G.Port(body.template, body.region, G.PortKind.ENTER)
    definitions = []; strong = defaultdict(int); weak = defaultdict(int); seeds = 0
    reads_by_site = defaultdict(lambda: defaultdict(list)); frontiers = []; frontier_ids = set()
    operations = {op.entry: i for i, op in enumerate(flow.operations)}

    def frontier(state, edge, access, reason, evidence=()):
        key = state, edge, access, reason, evidence
        if key not in frontier_ids:
            frontier_ids.add(key); frontiers.append(D.NameDefinitionFrontier(*key))

    def definition(kind, site, value=None, access=None, formal=None, operation=None, evidence=(), conditions=()):
        ordinal = len(definitions)
        definitions.append(D.NameDefinition(kind, site, value, access, formal, operation, evidence, conditions))
        return 1 << ordinal

    for ordinal, admission in enumerate(anchor_graph.formals):
        if admission.owner.owner != scope or admission.record.namespace != namespace or admission.source_function != source_function:
            continue
        if admission.entry.port != root or admission.formal != source_port(unit, admission.record.value):
            raise ValueError('name definition formal admission changed its original entry/value')
        seeds |= definition(D.NameDefinitionKind.FORMAL, root, admission.formal, formal=ordinal,
            evidence=(admission.fact, admission.function), conditions=('SELECTED_CALL_ADMITS_RECORDED_FORMAL_REFERENCE',))
    if not seeds:
        seeds = definition(D.NameDefinitionKind.ENTRY_OPEN, root, conditions=(
            'BINDING_CONTENT_AT_BODY_ENTRY_UNRESOLVED_NOT_NONE_OR_UNBOUND',))
    tracked_facts = {slicer.fact(unit, 'names', i): row for i, row in enumerate(unit.names) if row.namespace == namespace}
    for ordinal, anchor in enumerate(anchor_graph.anchors):
        if anchor.scope != scope or anchor.namespace != namespace:
            continue
        access = anchor_graph.accesses[anchor.access]
        if (tracked_facts.get(anchor.fact) != anchor.record or anchor.record.namespace != namespace
                or access.owner.owner != scope or access.site.unit != unit.unit
                or access.value != source_port(unit, anchor.record.value)):
            raise ValueError('name definition anchor changed its original name/scope/value')
        operation = operations.get(access.site.port)
        if operation is None:
            frontier(None, None, anchor.access, 'ACCESS_OUTSIDE_RETAINED_NORMAL_BODY_CONTROL', (anchor.fact,)); continue
        ins = flow.operations[operation].instruction
        if type(ins) is not P.AccessBinding or ins.port != access.binding_port or ins.action is not access.action:
            raise ValueError('name definition access does not match its original F4 operation')
        if access.action is P.BindingActionKind.READ:
            reads_by_site[access.site.port][anchor.access].append(ordinal)
        elif access.action is P.BindingActionKind.WRITE:
            site = _exit(access.site.port)
            strong[site] |= definition(D.NameDefinitionKind.WRITE, site, access.value, access=anchor.access,
                operation=operation, evidence=(anchor.fact,), conditions=(
                    'NORMAL_EXPLICIT_LEXICAL_WRITE_TO_SELECTED_SAME_FRAME_SLOT',))
    for delete in anchor_graph.deletes:
        access = anchor_graph.accesses[delete.access]
        if delete.namespace != namespace or access.owner.owner != scope:
            continue
        operation = operations.get(access.site.port)
        if operation is None:
            frontier(None, None, delete.access, 'DELETE_OUTSIDE_RETAINED_NORMAL_BODY_CONTROL'); continue
        ins = flow.operations[operation].instruction
        if type(ins) is not P.AccessBinding or ins.action is not P.BindingActionKind.DELETE or ins.port != access.binding_port:
            raise ValueError('name definition delete changed its original F4 operation')
        site = _exit(access.site.port)
        strong[site] |= definition(D.NameDefinitionKind.DELETE, site, access=delete.access, operation=operation,
            conditions=('NORMAL_LEXICAL_DELETE_NOT_A_NONE_REFERENCE_VALUE',))
    for value in anchor_graph.frontiers:
        if value.scope not in (None, scope) or value.fact is not None and value.fact not in tracked_facts:
            continue
        frontier(None, None, value.access, 'ANCHOR_'+value.reason, () if value.fact is None else (value.fact,))
    # Unknown hooks/callbacks are weak alternatives, including at explicit
    # accesses themselves. A successful explicit update kills prior defs;
    # it does not grant absence of opaque effects of that operation.
    for ordinal, operation in enumerate(flow.operations):
        if not any(_state(port.value_type) for port in operation.inputs): continue
        completions = {(port.port.completion, port.port.target) for port in operation.outputs if _state(port.value_type)}
        for completion, target in sorted(completions, key=lambda pair: (pair[0].value, str(pair[1]))):
            site = _exit(operation.entry, completion, target)
            weak[site] |= definition(D.NameDefinitionKind.OPAQUE_EFFECT, site, operation=ordinal, conditions=(
                'OPERATION_MAY_CHANGE_TRACKED_SLOT_THROUGH_UNRESOLVED_CALLBACK_OR_CAPTURE',
                'OPAQUE_EFFECT_IS_UNKNOWN_NOT_NONE_AND_NOT_REFERENCE_ALIAS',))
    frontier(None, None, None, 'APPLICATION_EXCEPTION_PATHS_OUTSIDE_NORMAL_SUCCESS_VIEW')
    frontier(None, None, None, 'OPAQUE_CALLBACK_AND_CAPTURE_SLOT_IDENTITY_REMAIN_OPEN')

    coordinates = [(root, ())]; index = {(root, ()): 0}; queue = deque((0,)); transitions = []
    successors = defaultdict(list); traversal_complete = True
    while queue:
        source = queue.popleft(); port, stack = coordinates[source]
        for edge_ordinal in adjacency.get(port, ()):
            edge = edges[edge_ordinal]; following = stack
            if edge.transition is G.Transition.CALL:
                if edge.site is None:
                    traversal_complete = False; frontier(source, edge_ordinal, None, 'STRUCTURAL_CALLSITE_UNRESOLVED'); continue
                if len(stack) >= max_stack:
                    traversal_complete = False; frontier(source, edge_ordinal, None, 'RECIPE_STACK_BUDGET_OPEN'); continue
                following = (*stack, edge.site)
            elif edge.transition is G.Transition.RETURN:
                if not stack or stack[-1] != edge.site: continue
                following = stack[:-1]
            elif edge.transition is G.Transition.RESUME:
                traversal_complete = False; frontier(source, edge_ordinal, None, 'RESUME_ACTIVATION_CONTEXT_UNRESOLVED'); continue
            coordinate = edge.target, following
            if coordinate not in index:
                if len(coordinates) >= max_states:
                    traversal_complete = False; frontier(source, edge_ordinal, None, 'CONTROL_STATE_BUDGET_OPEN'); continue
                index[coordinate] = len(coordinates); coordinates.append(coordinate); queue.append(index[coordinate])
            target = index[coordinate]
            transitions.append(D.NameDefinitionTransition(source, target, edge_ordinal)); successors[source].append(target)
    incoming = [0]*len(coordinates); outgoing = [0]*len(coordinates); incoming[0] = seeds
    queue = deque((0,)); queued = {0}; updates = 0; dataflow_complete = True
    while queue:
        if updates >= max_updates:
            dataflow_complete = False; frontier(None, None, None, 'DEFINITION_WORKLIST_BUDGET_OPEN'); break
        source = queue.popleft(); queued.remove(source); updates += 1
        port = coordinates[source][0]
        # Strong GEN/KILL occurs at the actual successful store/delete EXIT,
        # never at its RHS reference port or source-table ordinal.
        result = strong[port] if strong[port] else incoming[source]
        result |= weak[port]
        if result == outgoing[source]: continue
        outgoing[source] = result
        for target in successors.get(source, ()):
            combined = incoming[target] | result
            if combined != incoming[target]:
                incoming[target] = combined
                if target not in queued: queued.add(target); queue.append(target)
    reads = []; seen_reads = set()
    for state, (port, _) in enumerate(coordinates):
        for access, anchors in reads_by_site.get(port, {}).items():
            reads.append(D.NameDefinitionRead(state, access, tuple(anchors), _ids(incoming[state]))); seen_reads.add(access)
    for accesses in reads_by_site.values():
        for access in accesses:
            if access not in seen_reads:
                frontier(None, None, access, 'READ_NOT_REACHED_IN_RETAINED_NORMAL_CONTROL_VIEW')
    states = tuple(D.NameDefinitionState(port, stack, _ids(incoming[i]), _ids(outgoing[i]))
        for i, (port, stack) in enumerate(coordinates))
    material.validate_parents()
    return D.NameDefinitionGraph(source_function, function_fact, body, scope, namespace, anchor_graph,
        edges, flow.operations, tuple(definitions), states, tuple(transitions), tuple(reads), tuple(frontiers),
        traversal_complete, dataflow_complete)
