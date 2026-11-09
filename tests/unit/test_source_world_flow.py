"""Iterator exhaustion carries a world; loops remain shared and cyclic."""
from types import SimpleNamespace as NS

from scar.analysis.source_world_flow import project_world_flow
from scar.analysis.source_productions import _digest
from scar.ir.program import source_productions as P, normal_graph as G, normal_targets as T
from scar.ir.program.source_template_links import SourceTemplateKey
from scar.ir.program.source_contexts import ContextState, OwnerRef
from scar.ir.program.control import LanguageCompletionKind as C
from scar.ir.program.model import ValueKind, ValueType
from scar.ir.program.ids import LocationID
from scar.ir.program.providers import ProviderArtifact, ProviderFactReference
from scar.ir.record_codec import encode


def test_iteration_exit_world_and_backedge_without_unrolling():
    ref = ValueType(ValueKind.REFERENCE); boolean = ValueType(ValueKind.DATA, 'builtins.bool')
    world = ValueType(ValueKind.STATE, location=LocationID('world'))
    source = P.ProductionOccurrence(0); key = SourceTemplateKey(0, P.ProductionPurpose.VALUE)
    context = ContextState(OwnerRef(0, 'ROOT'), 0, 0, 0)
    rid = lambda n: P.ProductionRegionID(n)
    sid = lambda n: P.ProductionStepID(n)
    parameter = lambda region, i: P.ProductionParameter(rid(region), i)
    normal = lambda *types: P.ProductionCompletion(C.FALLTHROUGH, types)
    exhausted = P.ProductionCompletion(C.RAISE, (ref, world))
    def region(name, parent, kind, params, completions, names):
        return P.ProductionRegion(rid(name), None if parent is None else rid(parent), kind, source,
            context, params, completions, tuple(sid(n) for n in names))
    def step(name, region, instruction, args, completions):
        return P.ProductionStep(sid(name), rid(region), source, instruction, args, completions)
    regions = (
        region('loop', None, P.ProductionRegionKind.LOOP, (ref, world), (normal(world),), ('drive',)),
        region('advance', 'loop', P.ProductionRegionKind.LOOP_CONDITION, (ref, world),
            (normal(ref, world), exhausted), ('next', 'advanced')),
        region('classify', 'loop', P.ProductionRegionKind.HANDLER, (ref, world), (normal(boolean),), ('match', 'classified')),
        region('body', 'loop', P.ProductionRegionKind.LOOP_BODY, (ref, world, ref), (normal(world),), ('body_return',)),
        region('else', 'loop', P.ProductionRegionKind.ALTERNATIVE, (ref, world), (normal(world),), ('else_return',)))
    steps = (
        step('drive', 'loop', P.LoopControl(P.IterationCondition(
            P.ProductionRegionCall(rid('advance'), (parameter('loop', 0), parameter('loop', 1))), rid('classify'), 1),
            rid('body'), rid('else'), invariant_count=1),
            (parameter('loop', 0), parameter('loop', 1)), (normal(world),)),
        step('next', 'advance', P.ApplyLanguageAction(P.LanguageActionKind.CALL),
            (parameter('advance', 0), parameter('advance', 1)), (normal(ref, world), exhausted)),
        step('advanced', 'advance', P.TransferCompletion(C.FALLTHROUGH),
            (P.ProductionResult(sid('next'), 0), P.ProductionResult(sid('next'), 1)), (normal(ref, world),)),
        step('match', 'classify', P.ApplyLanguageAction(P.LanguageActionKind.TRUTH),
            (parameter('classify', 0), parameter('classify', 1)), (normal(boolean),)),
        step('classified', 'classify', P.TransferCompletion(C.FALLTHROUGH),
            (P.ProductionResult(sid('match'), 0),), (normal(boolean),)),
        step('body_return', 'body', P.TransferCompletion(C.FALLTHROUGH), (parameter('body', 1),), (normal(world),)),
        step('else_return', 'else', P.TransferCompletion(C.FALLTHROUGH), (parameter('else', 1),), (normal(world),)))
    basis = P.ProductionInput('/source/loop.py', '/source', *('a'*64 for _ in range(8)))
    plan = P.SourceProductionPlan(basis, source, P.ProductionPurpose.VALUE, rid('loop'), regions, steps, ())
    node = NS(origin=NS(plan_sha256=_digest(encode(plan, record_tags=P.PRODUCTION_RECORD_TAGS))))
    fn = NS(template=key, body=rid('loop'), body_scope=NS(owner=NS()))
    unit = NS(unit='unit', functions=(fn,), scope_groups=())
    artifact = ProviderArtifact('/source/templates/result.json', '0'*64, 0, 'test')
    material = NS(unit='unit', closure=lambda *args, **kwargs: {key: plan},
        interfaces=dict(nodes={key: node}, links={}), result_artifact=artifact,
        fact_store=NS(load=lambda identity: unit), validate_parents=lambda: None)
    body = T.Body('unit', key, rid('loop'))
    anchor = T.GlobalPort('unit', G.Port(key, rid('loop'), G.PortKind.PARAMETER, 1))
    exit = T.GlobalPort('unit', G.Port(key, rid('loop'), G.PortKind.RESULT, 0, C.FALLTHROUGH))
    flow = project_world_flow(material, body, ProviderFactReference(artifact, '#/projection/0'), anchor, exit)
    assert flow.anchor_reaches_exit
    assert any(e.transition is G.Transition.BACKEDGE for e in flow.edges)
    assert any(o.after.port.completion is C.RAISE and o.after.port.owner == sid('next') for o in flow.operations)
    assert any(e.condition is not None for e in flow.edges)  # Exhaustion decision remains explicit.
    assert len({o.after.port.owner for o in flow.operations}) == 1
    assert 'NO_CONTENT_PRESERVATION_OR_EFFECT_DISCHARGE' in flow.conditions
