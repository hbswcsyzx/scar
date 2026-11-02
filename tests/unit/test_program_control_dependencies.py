"""Control dependencies differ from CFG predecessors and sequence order."""
import hashlib

from scar.analysis.program_control_dependencies import ControlDependencyProvider
from scar.analysis.program_dependencies import ProgramDependencyGraph
from scar.ir.program.codec import SCHEMA_VERSION, dumps
from scar.ir.program.dependencies import DependencyFrame, DependencyKind as K, DependencyPoint, DependencyStrength, GraphNamespace
from scar.ir.program.ids import BlockID, OperationID, RegionID, UseID, ValueID
from scar.ir.program.model import (
    Behavior, Block, BlockArgument, CompletionSignature, CompletionSuccessor, DataValue, ExitKind, ExitPort, Operation,
    ProgramGraph, Region, Successor, Terminator, TerminatorKind, Use, UseRole,
)
from scar.ir.program.providers import ProviderArtifact
from scar.ir.program.queries import ProgramIndex
from scar.ir.program.source_references import SourceArtifactLocator


def test_postdom_control_diamond_loop_raise_closed_scc_and_bounded_cache(tmp_path):
    regions, operations, values = [], [], []

    def region(prefix, layout, *, parent=None):
        identity = RegionID(prefix)
        blocks = {name: BlockID(prefix + ':' + name) for name in layout}
        condition = ValueID(prefix + ':condition')
        values.append(DataValue(condition, identity, BlockArgument(blocks['entry'], 0), 'builtins.bool'))
        records = []
        for name, (action, arguments) in layout.items():
            opids = []
            work = Operation(OperationID(prefix + ':' + name + ':work'), 'original work',
                (Behavior.COMPUTE,), effects_complete=True)
            operations.append(work)
            opids.append(work.id)
            opid = OperationID(prefix + ':' + name + ':term')
            if action == 'branch':
                use = Use(UseID(prefix + ':' + name + ':condition-use'), condition, UseRole.DATA)
                term = Terminator(TerminatorKind.BRANCH,
                    tuple(Successor(blocks[target], ()) for target in arguments), condition=use.id)
                op = Operation(opid, 'original branch', (Behavior.CONTROL,), (use,),
                    effects_complete=True, terminator=term)
            elif action == 'invoke':
                term = Terminator(TerminatorKind.INVOKE, (
                    CompletionSuccessor(ExitKind.NORMAL, blocks[arguments[0]], ()),
                    CompletionSuccessor(ExitKind.RAISE, blocks[arguments[1]], ())))
                op = Operation(opid, 'native/protocol invocation', (Behavior.CONTROL,),
                    effects_complete=True, terminator=term, completions=(
                        CompletionSignature(ExitKind.NORMAL, ()), CompletionSignature(ExitKind.RAISE, ())))
            elif action == 'jump':
                op = Operation(opid, 'original jump', (Behavior.CONTROL,), effects_complete=True,
                    terminator=Terminator(TerminatorKind.JUMP, (Successor(blocks[arguments[0]], ()),)))
            else:
                kind = TerminatorKind.RETURN if action == 'return' else TerminatorKind.RAISE
                op = Operation(opid, 'original completion', (Behavior.CONTROL,), effects_complete=True,
                    terminator=Terminator(kind, exit='normal' if action == 'return' else 'raise'))
            operations.append(op)
            opids.append(opid)
            records.append(Block(blocks[name], (condition,) if name == 'entry' else (), tuple(opids)))
        exits = (ExitPort('normal', ExitKind.NORMAL, ()),)
        if any(action == 'raise' for action, _ in layout.values()):
            exits += (ExitPort('raise', ExitKind.RAISE, ()),)
        regions.append(Region(identity, prefix, blocks['entry'], tuple(records), exits, parent=parent))
        return identity

    root = region('diamond', {
        'entry': ('branch', ('yes', 'no')), 'yes': ('jump', ('join',)),
        'no': ('jump', ('join',)), 'join': ('return', ()),
    })
    region('loop', {
        'entry': ('jump', ('header',)), 'header': ('branch', ('body', 'after')),
        'body': ('jump', ('header',)), 'after': ('return', ()),
    }, parent=root)
    region('exception', {
        'entry': ('branch', ('normal', 'error')), 'normal': ('return', ()), 'error': ('raise', ()),
    }, parent=root)
    region('closed', {
        'entry': ('branch', ('a', 'finish')), 'a': ('jump', ('b',)),
        'b': ('jump', ('a',)), 'finish': ('return', ()),
    }, parent=root)
    region('native', {
        'entry': ('invoke', ('normal', 'handled')), 'normal': ('jump', ('join',)),
        'handled': ('jump', ('join',)), 'join': ('return', ()),
    }, parent=root)
    region('gatedcall', {
        'entry': ('branch', ('invoke', 'other')), 'invoke': ('invoke', ('normal', 'error')),
        'normal': ('return', ()), 'error': ('raise', ()), 'other': ('return', ()),
    }, parent=root)
    graph = ProgramGraph(root, tuple(regions), tuple(operations), tuple(values))
    index = ProgramIndex(graph)
    payload = dumps(graph).encode()
    path = tmp_path / 'original-graph.json'
    path.write_bytes(payload)
    sha = hashlib.sha256(payload).hexdigest()
    locator = SourceArtifactLocator(ProviderArtifact(str(path), sha, len(payload), 'scar.program-graph'),
        sha, len(payload), 'canonical-json')
    namespace = GraphNamespace(locator, 'scar.program-graph/' + str(SCHEMA_VERSION), graph.root)
    provider = ControlDependencyProvider(lambda ns: index)
    view = ProgramDependencyGraph(lambda ns: index, providers=(provider,))

    def incoming(node, context=()):
        return view.incoming(DependencyPoint(namespace, node, context), kinds=(K.CONTROL,))

    controller = OperationID('diamond:entry:term')
    yes = incoming(OperationID('diamond:yes:work'))
    no = incoming(OperationID('diamond:no:work'))
    assert any(edge.source.node == controller and edge.conditions[0].index == 0 for edge in yes.edges)
    assert any(edge.source.node == controller and edge.conditions[0].index == 1 for edge in no.edges)
    assert not incoming(OperationID('diamond:join:work')).edges  # Both paths join here.
    assert not incoming(OperationID('diamond:entry:work')).edges
    assert not yes.frontiers
    assert all(edge.strength is DependencyStrength.EXACT for edge in yes.edges)
    assert all(edge.kind is K.CONTROL for edge in (*yes.edges, *no.edges))
    assert any(edge.target.node == BlockID('diamond:yes')
        for edge in provider.outgoing(DependencyPoint(namespace, controller)).edges)

    normal = incoming(OperationID('exception:normal:work'))
    raised = incoming(OperationID('exception:error:work'))
    assert any(edge.conditions[0].index == 0 for edge in normal.edges)
    assert any(edge.conditions[0].index == 1 for edge in raised.edges)
    assert not normal.frontiers and not raised.frontiers

    body = incoming(OperationID('loop:body:work'))
    after = incoming(OperationID('loop:after:work'))
    assert any(edge.source.node == OperationID('loop:header:term')
        and edge.conditions[0].index == 0 for edge in body.edges)
    assert any(edge.source.node == OperationID('loop:header:term')
        and edge.conditions[0].index == 1 for edge in after.edges)
    assert any(note.kind == 'CONTROL_TERMINATION_OPEN' for note in after.frontiers)
    assert all(edge.strength is DependencyStrength.MAY for edge in after.edges
        if edge.evidence[0].rule == 'CFG_POSTDOM_DIVERGENCE_EXTENDED_CONTROL_V1')
    assert any(edge.strength is DependencyStrength.EXACT
        and edge.evidence[0].rule == 'CFG_ENTRY_EDGE_DOMINANCE_CONTROL_NECESSITY_V1'
        and edge.conditions[0].index == 1 for edge in after.edges)
    assert any(edge.source.node == OperationID('closed:entry:term')
        for edge in incoming(OperationID('closed:a:work')).edges)
    assert any(note.kind == 'CONTROL_TERMINATION_OPEN'
        for note in incoming(OperationID('closed:b:work')).frontiers)
    assert any(edge.source.node == OperationID('closed:entry:term')
        and edge.evidence[0].rule == 'CFG_ENTRY_EDGE_DOMINANCE_CONTROL_NECESSITY_V1'
        for edge in incoming(OperationID('closed:b:work')).edges)
    assert not view.walk((DependencyPoint(namespace, OperationID('closed:b:work')),),
        kinds=(K.CONTROL,)).dependence_closed
    native_join = incoming(OperationID('native:join:work'))
    assert any(edge.source.node == OperationID('native:entry:term') for edge in native_join.edges)
    assert all(edge.strength is DependencyStrength.MAY for edge in native_join.edges)
    assert any(note.kind == 'CONTROL_INVOKE_TERMINATION_OPEN' for note in native_join.frontiers)

    # An acyclic normal landing requires its original NORMAL edge even when
    # the producer might diverge. This exact *necessary* entry predicate is
    # not a proof the invocation completes, or that a shared join chose it.
    required = incoming(OperationID('gatedcall:normal:work'))
    necessities = [edge for edge in required.edges
        if edge.evidence[0].rule == 'CFG_ENTRY_EDGE_DOMINANCE_CONTROL_NECESSITY_V1']
    assert len(necessities) == 1
    assert necessities[0].source.node == OperationID('gatedcall:invoke:term')
    assert necessities[0].strength is DependencyStrength.EXACT
    assert necessities[0].conditions[0].index == 0
    assert necessities[0].conditions[1].name == 'ORIGINAL_EDGE_REQUIRED_FOR_ENTRY_REACHABILITY'
    outer = incoming(OperationID('gatedcall:invoke:term'))
    assert any(edge.source.node == OperationID('gatedcall:entry:term')
        and edge.evidence[0].rule == 'CFG_ENTRY_EDGE_DOMINANCE_CONTROL_NECESSITY_V1'
        for edge in outer.edges)
    assert not any(edge.evidence[0].rule == 'CFG_ENTRY_EDGE_DOMINANCE_CONTROL_NECESSITY_V1'
        for edge in native_join.edges)
    assert any(note.kind == 'CONTROL_INVOKE_TERMINATION_OPEN' for note in required.frontiers)

    # Same original local graph, selected through an existing region-call
    # frame. Context belongs on edge endpoints, guards and witness anchors.
    frame = DependencyFrame(namespace, controller, None, None, namespace, entry=RegionID('loop'))
    contextual = incoming(OperationID('diamond:yes:work'), (frame,))
    assert contextual.edges
    assert all(e.source.context == e.target.context == (frame,) for e in contextual.edges)
    assert all(a.context == (frame,) for e in contextual.edges for evidence in e.evidence for a in evidence.anchors)
    assert all(c.subject.context == (frame,) for e in contextual.edges for c in e.conditions if c.subject is not None)
    assert path.read_bytes() == payload

    # A valid frame chain must also end at the endpoint's graph namespace.
    # Reject an unrelated namespace before a provider can activate its facts.
    import pytest
    from dataclasses import replace
    unrelated = replace(namespace, root=RegionID('unrelated'))
    bad_frame = DependencyFrame(namespace, controller, None, None, unrelated, entry=RegionID('loop'))
    with pytest.raises(ValueError, match='context does not end'):
        view.incoming(DependencyPoint(namespace, OperationID('diamond:yes:work'), (bad_frame,)))

    bounded = ControlDependencyProvider(lambda ns: index, max_cached_records=1, max_control_edges=1)
    result = bounded.incoming(DependencyPoint(namespace, OperationID('diamond:yes:work')))
    assert any(note.kind == 'CONTROL_EDGE_BUDGET' for note in result.frontiers)
    assert bounded._cache_records == 0  # No free retention for a large zero-edge graph.
