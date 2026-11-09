"""Build a shared post-call STATE/CONTROL graph from sealed F4 materials.

Protocol state changes are operations, never copy/alias edges. The graph keeps
branch guards, loop backedges and paired call-site labels. Reachability is a
may-path query, not a total order, a selected invocation, or effect discharge.
"""
import argparse
from collections import defaultdict, deque, Counter
from hashlib import sha256
import json
from pathlib import Path
import time

from scar.analysis.normal_graph import normal_edges, _Emitter
from scar.analysis.source_declared_state import read_declared_state
from scar.analysis.source_configuration_state_binding import read_configuration_state_bindings
from scar.analysis.source_reference_slice import ReferenceSlicer, source_port
from scar.analysis.source_world_material import WorldMaterial
from scar.analysis.source_context_query import ContextTargetGraph
from scar.analysis.normal_output import write_table
from scar.analysis.source_symbol_variants import _table
from scar.analysis.source_stage import _durable_bytes, _durable_mkdir
from scar.analysis.source_template_links import _json
from scar.ir.program import source_world_flow as W, normal_graph as G, normal_targets as T
from scar.ir.program import source_productions as P, normal_links as F
from scar.ir.program.model import ValueKind, ValueType
from scar.ir.program.control import LanguageCompletionKind as C
from scar.ir.program.providers import ProviderArtifact, ProviderFactReference
from scar.ir.record_codec import encode, decode


STRUCTURAL = (P.EvaluateChild, P.ApplyRegion, P.InvokeTypeParameterFactory, P.BranchControl,
    P.HandleCompletions, P.LoopControl, P.SuspendExecution, P.TransferCompletion)


def _state(value):
    return type(value) is ValueType and value.kind is ValueKind.STATE


def _walk(start, adjacency):
    seen = {start}; queue = deque((start,))
    while queue:
        for target in adjacency.get(queue.popleft(), ()):
            if target not in seen: seen.add(target); queue.append(target)
    return seen


def project_world_flow(material, caller, projection, anchor, normal_exit, *, max_templates=4000):
    plans = material.closure(caller.template, max_templates=max_templates)
    all_edges = []; operations = []
    for key, plan in plans.items():
        emitter = _Emitter(plan, key, material.interfaces)
        all_edges.extend(e for e in normal_edges(plan, material.interfaces)
            if e.kind in (G.EdgeKind.STATE, G.EdgeKind.CONTROL))
        for step in plan.steps:
            if isinstance(step.instruction, STRUCTURAL): continue
            before = [emitter.port(step.id, G.PortKind.ARGUMENT, i)
                for i, value in enumerate(step.arguments) if _state(emitter.value(value)[1])]
            for completion in step.completions:
                exhaustion = completion.kind is C.RAISE and step.region in emitter.exhaustion
                if completion.kind not in (C.FALLTHROUGH, C.RETURN) and not exhaustion: continue
                guards = ('NORMAL_OPERATION_COMPLETION_SELECTED', 'OPERATION_EFFECTS_REMAIN_OPEN') if not exhaustion else (
                    'ITERATOR_ADVANCE_RAISE_FOLLOWS_MATCHED_EXHAUSTION_CONTROL', 'OPERATION_EFFECTS_REMAIN_OPEN')
                for i, kind in enumerate(completion.types):
                    if not _state(kind): continue
                    after = emitter.port(step.id, G.PortKind.RESULT, i, completion)
                    operations.extend(W.OperationStateTransition(T.GlobalPort(material.unit, b),
                        T.GlobalPort(material.unit, after), type(step.instruction).__name__, guards) for b in before)
    # Restrict to the selected body. DECLARE edges never enter nested code.
    control = defaultdict(list)
    for e in all_edges:
        if e.kind is G.EdgeKind.CONTROL: control[e.source].append(e.target)
    entry = G.Port(caller.template, caller.region, G.PortKind.ENTER)
    reachable = _walk(entry, control)
    owners = {(p.template, p.owner) for p in reachable}
    inside = lambda p: (p.template, p.owner) in owners
    edges = tuple(e for e in all_edges if inside(e.source) and inside(e.target))
    operations = tuple(o for o in operations if inside(o.before.port) and inside(o.after.port))
    state = defaultdict(list); reverse = defaultdict(list)
    for e in edges:
        if e.kind is G.EdgeKind.STATE:
            state[e.source].append(e.target); reverse[e.target].append(e.source)
    for op in operations:
        state[op.before.port].append(op.after.port); reverse[op.after.port].append(op.before.port)
    forward = _walk(anchor.port, state); backward = _walk(normal_exit.port, reverse)
    cut = forward & backward
    # The post-anchor suffix is a projection; the unchanged original shared
    # program remains its source of truth, including other branches/consumers.
    suffix_ops = tuple(o for o in operations if o.before.port in cut and o.after.port in cut)
    # Keep all body control to retain guards/call-site/loop structure. State
    # edges carry only the anchored suffix and never become reference aliases.
    selected = tuple(e for e in edges if e.kind is G.EdgeKind.CONTROL or e.source in cut and e.target in cut)
    unit = material.fact_store.load(material.unit)
    slicer = ReferenceSlicer(type('SourceOnly', (), {'fact_store': material.fact_store})())
    function = next(f for f in unit.functions if T.Body(unit.unit, f.template, f.body) == caller)
    accesses = []
    for group in unit.scope_groups:
        if group.owner != function.body_scope.owner: continue
        for span in group.tables:
            if span.table not in (F.FactTable.CALLS, F.FactTable.ATTRIBUTES, F.FactTable.ITEMS): continue
            for ordinal in range(span.start, span.stop):
                row = getattr(unit, span.table.value)[ordinal]
                before, after = source_port(unit, row.world), source_port(unit, row.result_world)
                if before.port not in cut or after.port not in cut: continue
                action = 'CALL' if span.table is F.FactTable.CALLS else (
                    row.action.value if span.table is F.FactTable.ATTRIBUTES else 'SET' if row.write else 'GET')
                accesses.append(W.SequencedAccess(slicer.fact(unit, span.table.value, ordinal), span.table.value,
                    action, before, after))
    conditions = ('DECLARED_PARENT_CALL_CONTEXT_SELECTED', 'SOURCE_STATE_AND_CONTROL_ROUTES_SELECTED',
        'CALL_RETURN_SITE_PAIRING_AND_BRANCH_GUARDS_REQUIRED', 'LOOP_ITERATION_SELECTION_REMAINS_OPEN',
        'REACHABILITY_IS_MAY_NOT_MUST', 'NO_CONTENT_PRESERVATION_OR_EFFECT_DISCHARGE')
    material.validate_parents()
    return W.SourceWorldFlow(projection, material.result_artifact, material.unit, caller, anchor, normal_exit,
        selected, suffix_ops, tuple(accesses), normal_exit.port in forward, conditions)


def _artifact(path, schema):
    path = Path(path).absolute(); raw = path.read_bytes()
    return ProviderArtifact(str(path), sha256(raw).hexdigest(), len(raw), schema)


def _pins():
    from scar.analysis import source_world_material, normal_graph
    return {name: sha256(Path(path).read_bytes()).hexdigest() for name, path in (
        ('producer', __file__), ('types', W.__file__), ('material', source_world_material.__file__),
        ('emitter', normal_graph.__file__))}


def _derive(join, max_templates):
    join_report, connections, _ = read_declared_state(join)
    boundary_report, bindings = read_configuration_state_bindings(join_report['boundaries'])
    # Context parent remains the authority for the exact source catalog.
    contexts = json.loads((Path(join_report['contexts'])/'result.json').read_bytes())
    fields = json.loads((Path(contexts['parent'])/'result.json').read_bytes())
    catalog = ContextTargetGraph(fields['catalog'])
    receipt = boundary_report['bindings']
    artifact = ProviderArtifact(str(Path(join_report['boundaries'])/receipt['path']), receipt['sha256'],
        receipt['bytes'], 'scar.source-state-projections')
    connected = {c.projection.locator for c in connections}; queries = []; materials = {}
    for ordinal, b in enumerate(bindings):
        if '#/records/'+str(ordinal) not in connected: continue
        if b.receiver.unit not in materials: materials[b.receiver.unit] = WorldMaterial(catalog, b.receiver.unit)
        material = materials[b.receiver.unit]; unit = material.fact_store.load(material.unit)
        caller = next(f for f in unit.functions if f.body_scope == b.caller)
        body = T.Body(unit.unit, caller.template, caller.body)
        queries.append(project_world_flow(material, body, ProviderFactReference(artifact, '#/records/'+str(ordinal)),
            b.world_after, source_port(unit, caller.return_world), max_templates=max_templates))
    return tuple(queries)


def _counts(queries):
    return dict(queries=len(queries), edges=sum(len(q.edges) for q in queries),
        edge_kinds=dict(Counter(e.kind.value for q in queries for e in q.edges)),
        operation_state_transitions=sum(len(q.operations) for q in queries),
        accesses=sum(len(q.accesses) for q in queries),
        access_kinds=dict(Counter(a.table+':'+a.action for q in queries for a in q.accesses)),
        backedges=sum(e.transition is G.Transition.BACKEDGE for q in queries for e in q.edges),
        anchored_exits=sum(q.anchor_reaches_exit for q in queries))


def build_world_flow(join, out, *, max_templates=4000):
    started = time.monotonic(); out = Path(out).absolute(); join = Path(join).absolute(); pins = _pins()
    if out.exists(): raise ValueError('fresh world-flow output required')
    parent = _artifact(join/'result.json', 'scar.declared-state-connections')
    queries = _derive(join, max_templates)
    if _pins() != pins or parent != _artifact(join/'result.json', parent.schema): raise ValueError('world flow parent/rules changed')
    _durable_mkdir(out)
    table = write_table(out/'queries.jsonl.gz', queries)
    r = dict(schema='scar.source-world-flow', schema_version=1, status='SHARED_POST_CALL_STATE_GRAPH', pins=pins,
        join=str(join), parent=encode(parent), max_templates=max_templates, table=table, counts=_counts(queries),
        loops_unrolled=False, source_regions_shared=True, current_state_versions_proven=False,
        effects_discharged=False, target_executed=False, first_stage_complete=False, seconds=time.monotonic()-started)
    _durable_bytes(out/'result.json', _json(r), replace=False); return r


def read_world_flow(path):
    path = Path(path).absolute(); raw = (path/'result.json').read_bytes(); r = json.loads(raw)
    if (r['schema'], r['schema_version']) != ('scar.source-world-flow', 1) or r['pins'] != _pins(): raise ValueError('world flow producer differs')
    if r['parent'] != encode(_artifact(Path(r['join'])/'result.json', 'scar.declared-state-connections')): raise ValueError('world flow parent differs')
    queries = tuple(decode(W.SourceWorldFlow, w, record_tags=P.PRODUCTION_RECORD_TAGS) for w in _table(path, r['table']))
    if queries != _derive(r['join'], r['max_templates']) or _counts(queries) != r['counts']: raise ValueError('world flow original routes/effects differ')
    if (any(r[k] is not False for k in ('loops_unrolled', 'current_state_versions_proven', 'effects_discharged',
            'target_executed', 'first_stage_complete')) or r['source_regions_shared'] is not True): raise ValueError('world flow cannot prove runtime state')
    if (path/'result.json').read_bytes() != raw: raise ValueError('world flow changed during validation')
    return r, queries


def main():
    p = argparse.ArgumentParser(description=__doc__); p.add_argument('--join'); p.add_argument('--out'); p.add_argument('--read')
    p.add_argument('--max-templates', type=int, default=4000); a = p.parse_args()
    if a.read: r, _ = read_world_flow(a.read)
    else:
        if not a.join or not a.out: p.error('--join and --out required')
        r = build_world_flow(a.join, a.out, max_templates=a.max_templates)
    print(json.dumps(dict(status=r['status'], counts=r['counts'])), flush=True)


if __name__ == '__main__': main()
