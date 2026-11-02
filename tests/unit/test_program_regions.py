"""An operation cut preserves state/completions without granting replacement."""
import hashlib

from scar.analysis.program_dependencies import ProgramDependencyGraph
from scar.analysis.program_regions import analyze_boundary, BoundaryKnowledge
from scar.ir.program.codec import SCHEMA_VERSION, dumps
from scar.ir.program.dependencies import DependencyFrame, DependencyPoint as P, GraphNamespace
from scar.ir.program.ids import BlockID as B, LocationID as L, OperationID as O, RegionID as R, ResourceDefinitionID as RD, ResourceRequirementID as RR, UseID as U, ValueID as V
from scar.ir.program.model import (
    AccessMode, Behavior, Block, BlockArgument, CompletionResult, CompletionSignature, CompletionSuccessor,
    DataValue, ExitKind, ExitPort, Footprint, FootprintKind, LiteralOrigin, Operation, OperationResult, OrderEdge,
    ProgramGraph, ReferenceValue, Region, StateAccess, StateLocation, StateVersionValue, Successor,
    Terminator, TerminatorKind, Use, UseRole, ValueKind, ValueType,
)
from scar.ir.program.providers import ProviderArtifact
from scar.ir.program.queries import ProgramIndex
from scar.ir.program.resources import CreatedResource, ExternalResource, ResourceDefinition, ResourceKind, ResourceLocation, ResourceRequirement, ResourceRole, ResourceUse
from scar.ir.program.source_references import SourceArtifactLocator
from scar.ir.program.state_addresses import AddressCoverage, AddressEffect, AddressUnit, ExistingAccess, InvokeStateOperand, ObjectField, ReferenceOwner, StateAddressRefinement, StorageRange
from scar.ir.program.stored_values import StoredValueWrite


def test_boundary_keeps_direct_and_invoke_state_interfaces_and_separates_escape(tmp_path):
    root, callee, location = R('root'), R('callee'), L('contents')
    ref, state = ValueType(ValueKind.REFERENCE), ValueType(ValueKind.STATE, location=location)
    values = [
        ReferenceValue(V('input'), root, BlockArgument(B('entry'), 0), targets=(location,), selector=Footprint(FootprintKind.WHOLE)),
        StateVersionValue(V('s0'), root, BlockArgument(B('entry'), 1), location),
        DataValue(V('condition'), root, BlockArgument(B('entry'), 2), 'builtins.bool'),
        DataValue(V('offset'), root, LiteralOrigin(0), 'builtins.int'),
        DataValue(V('count'), root, LiteralOrigin(4), 'builtins.int'),
        StateVersionValue(V('s1'), root, OperationResult(O('mutate'), 0), location),
        ReferenceValue(V('normal-ref'), root, BlockArgument(B('normal'), 0)),
        StateVersionValue(V('s2'), root, BlockArgument(B('normal'), 1), location),
        ReferenceValue(V('exception'), root, BlockArgument(B('raised'), 0)),
        ReferenceValue(V('traceback'), root, BlockArgument(B('raised'), 1)),
        StateVersionValue(V('s3'), root, BlockArgument(B('raised'), 2), location),
        StateVersionValue(V('callee-normal-state'), callee, BlockArgument(B('callee-normal'), 0), location),
        StateVersionValue(V('callee-raised-state'), callee, BlockArgument(B('callee-raised'), 0), location),
    ]
    callee_args = ('arg-ref', 'arg-offset', 'arg-count', 'arg-condition', 'arg-state')
    for i, name in enumerate(callee_args):
        origin = BlockArgument(B('callee-entry'), i)
        values.append(StateVersionValue(V(name), callee, origin, location) if i == 4 else
            ReferenceValue(V(name), callee, origin) if i == 0 else
            DataValue(V(name), callee, origin, 'builtins.bool' if i == 3 else 'builtins.int'))
    mutate = Operation(O('mutate'), 'declared slot update', (Behavior.READ, Behavior.WRITE),
        (Use(U('owner'), V('input'), UseRole.REFERENCE), Use(U('payload'), V('offset')),
         Use(U('before'), V('s0'), UseRole.STATE_CONTENT)), (V('s1'),),
        (StateAccess(location, U('before'), AccessMode.READ_WRITE, V('s1'),
            footprint=Footprint(FootprintKind.INTERVAL, 0, 4), reference=U('owner')),), effects_complete=True)
    invoke_uses = (Use(U('invoke-owner'), V('input'), UseRole.REFERENCE), Use(U('invoke-offset'), V('offset')),
        Use(U('invoke-count'), V('count')), Use(U('invoke-condition'), V('condition')),
        Use(U('invoke-world'), V('s1'), UseRole.STATE_CONTENT))
    invoke = Operation(O('invoke'), 'unknown operation with known interfaces',
        (Behavior.CONTROL, Behavior.READ, Behavior.WRITE, Behavior.MEMORY), invoke_uses, effects_complete=False,
        terminator=Terminator(TerminatorKind.INVOKE, (
            CompletionSuccessor(ExitKind.NORMAL, B('normal'), (CompletionResult(0), CompletionResult(1))),
            CompletionSuccessor(ExitKind.RAISE, B('raised'), (CompletionResult(0), CompletionResult(1), CompletionResult(2))))),
        callee=callee, completions=(CompletionSignature(ExitKind.NORMAL, (ref, state)),
            CompletionSignature(ExitKind.RAISE, (ref, ref, state))), invoke_arguments=tuple(u.id for u in invoke_uses))
    consumer = Operation(O('consumer'), 'outside data consumer', (Behavior.READ,),
        (Use(U('consume-ref'), V('normal-ref'), UseRole.REFERENCE), Use(U('consume-state'), V('s2'), UseRole.STATE_CONTENT)),
        accesses=(StateAccess(location, U('consume-state'), AccessMode.READ),), effects_complete=True)

    def finish(name, region, kind, value_names):
        uses = tuple(Use(U(name + ':' + str(i)), V(value),
            UseRole.STATE_CONTENT if value in ('s2', 's3', 'arg-state', 'callee-normal-state', 'callee-raised-state') else UseRole.REFERENCE)
            for i, value in enumerate(value_names))
        return Operation(O(name), name, (Behavior.CONTROL,), uses, effects_complete=True,
            terminator=Terminator(TerminatorKind.RETURN if kind is ExitKind.NORMAL else TerminatorKind.RAISE,
                exit='normal' if kind is ExitKind.NORMAL else 'raise', values=tuple(u.id for u in uses)))

    normal = finish('return', root, ExitKind.NORMAL, ('normal-ref', 's2'))
    raised = finish('raise', root, ExitKind.RAISE, ('exception', 'traceback', 's3'))
    branch_use = Use(U('callee-condition'), V('arg-condition'))
    branch_state = Use(U('callee-world-normal'), V('arg-state'), UseRole.STATE_CONTENT)
    branch_raised_state = Use(U('callee-world-raised'), V('arg-state'), UseRole.STATE_CONTENT)
    branch = Operation(O('callee-branch'), 'callee branch', (Behavior.CONTROL,), (branch_use, branch_state, branch_raised_state), effects_complete=True,
        terminator=Terminator(TerminatorKind.BRANCH, (Successor(B('callee-normal'), (branch_state.id,)), Successor(B('callee-raised'), (branch_raised_state.id,))),
            condition=branch_use.id))
    inner_normal = finish('callee-return', callee, ExitKind.NORMAL, ('arg-ref', 'callee-normal-state'))
    inner_raise = finish('callee-raise', callee, ExitKind.RAISE, ('arg-ref', 'arg-ref', 'callee-raised-state'))
    exits = (ExitPort('normal', ExitKind.NORMAL, (ref, state)), ExitPort('raise', ExitKind.RAISE, (ref, ref, state)))
    graph = ProgramGraph(root, (
        Region(root, 'original caller', B('entry'), (
            Block(B('entry'), (V('input'), V('s0'), V('condition')), (mutate.id, invoke.id)),
            Block(B('normal'), (V('normal-ref'), V('s2')), (consumer.id, normal.id)),
            Block(B('raised'), (V('exception'), V('traceback'), V('s3')), (raised.id,))), exits),
        Region(callee, 'shared implementation', B('callee-entry'), (
            Block(B('callee-entry'), tuple(V(n) for n in callee_args), (branch.id,)),
            Block(B('callee-normal'), (V('callee-normal-state'),), (inner_normal.id,)),
            Block(B('callee-raised'), (V('callee-raised-state'),), (inner_raise.id,))), exits, parent=root)),
        (mutate, invoke, consumer, normal, raised, branch, inner_normal, inner_raise), tuple(values),
        (StateLocation(location, 'contents', extent=4),), ordering=(OrderEdge(mutate.id, invoke.id),),
        resources=(ResourceDefinition(RD('memory'), ResourceKind.MEMORY, ResourceRole.MEMORY_POOL, ExternalResource(root, 'memory')),
            ResourceDefinition(RD('scratch'), ResourceKind.MEMORY, ResourceRole.MEMORY_POOL, CreatedResource(invoke.id))),
        resource_requirements=(ResourceRequirement(RR('storage'), invoke.id, ResourceKind.MEMORY, ResourceRole.MEMORY_POOL),),
        resource_uses=(ResourceUse(invoke.id, RR('storage'), RD('memory'), U('invoke-owner')),),
        resource_locations=(ResourceLocation(location, RD('memory')),), state_address_refinements=(
            StateAddressRefinement(ExistingAccess(mutate.id, 0),
                (AddressEffect(ReferenceOwner(U('owner')), (ObjectField('slot'),), AccessMode.READ_WRITE),), AddressCoverage.PARTIAL),
            StateAddressRefinement(InvokeStateOperand(invoke.id, U('invoke-world')),
                (AddressEffect(ReferenceOwner(U('invoke-owner')), (StorageRange(AddressUnit.ELEMENT, U('invoke-offset'), U('invoke-count')),),
                    AccessMode.READ_WRITE),), AddressCoverage.PARTIAL)),
        stored_value_writes=(StoredValueWrite(ExistingAccess(mutate.id, 0), 0, U('payload')),))
    index = ProgramIndex(graph)
    payload = dumps(graph).encode(); path = tmp_path / 'original.json'; path.write_bytes(payload)
    sha = hashlib.sha256(payload).hexdigest()
    locator = SourceArtifactLocator(ProviderArtifact(str(path), sha, len(payload), 'scar.program-graph'), sha, len(payload), 'canonical-json')
    namespace = GraphNamespace(locator, 'scar.program-graph/' + str(SCHEMA_VERSION), root)
    view = ProgramDependencyGraph(lambda ns: index)
    analysis = analyze_boundary(view, (P(namespace, mutate.id), P(namespace, invoke.id)))
    assert not analysis.transformation_authorized
    assert analysis.field('control').knowledge is BoundaryKnowledge.KNOWN
    assert analysis.field('rng').knowledge is BoundaryKnowledge.UNKNOWN
    assert analysis.field('aliases').knowledge is BoundaryKnowledge.PARTIAL
    assert analysis.implementation_interfaces
    assert analysis.control_dependencies
    assert analysis.field('control_dependencies').knowledge is BoundaryKnowledge.PARTIAL
    assert all(e.observable is None for e in analysis.escapes)
    assert any(e.interface_only for e in analysis.escapes)
    assert any(not e.interface_only and e.kind == 'OUTSIDE_CONSUMER' for e in analysis.escapes)
    direct, native = analysis.state
    assert direct.mode is AccessMode.READ_WRITE and direct.footprint.stop == 4
    assert direct.before_value.node == V('s0') and not direct.before_is_member
    assert native.before_value.node == V('s1') and native.before_is_member
    assert native.mode is None and {x.kind for x in native.outcomes} == {'NORMAL', 'RAISE'}
    assert native.refinements[0].effects[0].path[0].unit is AddressUnit.ELEMENT
    assert {p.node for p in native.address_operands} == {U('invoke-owner'), U('invoke-offset'), U('invoke-count')}
    assert any(r.value.node == V('normal-ref') and r.targets is None for r in analysis.references)
    assert {c.kind for c in analysis.control} >= {'NORMAL', 'RAISE'}
    assert analysis.resources[0].requirement.id == RR('storage')
    assert analysis.resources[0].locations[0].location == location
    assert P(namespace, RD('scratch')) in analysis.created_resources
    assert any(e.source == P(namespace, invoke.id) for e in view.incoming(P(namespace, RD('scratch'))).edges)
    resource_walk = view.walk((P(namespace, RD('scratch')),))
    assert not resource_walk.dependence_closed
    assert any(f.kind == 'EFFECT_SUMMARY_OPEN' for f in resource_walk.frontiers)
    external_resource = view.incoming(P(namespace, RD('memory')))
    assert any(e.source == P(namespace, root) for e in external_resource.edges)
    assert any(f.kind == 'EXTERNAL_RESOURCE_INPUT' for f in external_resource.frontiers)
    assert any(e.source.node == mutate.id and e.target.node == invoke.id for e in analysis.ordering)
    # CompletionResult.index is known port structure, not a runtime guard.
    # Normal and exception slot0 keep their own original successor mapping.
    normal_projection = next(e for e in view.incoming(P(namespace, V('normal-ref'))).edges
        if e.source.node == invoke.id and e.kind.value == 'RESULT')
    assert [c.name for c in normal_projection.conditions] == ['SUCCESSOR_SELECTED']
    projection_source = normal_projection.evidence[0].sources[0]
    import json
    original_slot = json.loads(payload)
    for segment in projection_source.pointer.removeprefix('#/').split('/'):
        original_slot = original_slot[int(segment)] if isinstance(original_slot, list) else original_slot[segment]
    assert original_slot == {'index': 0}
    assert any(e.kind == 'DECLARED_STATE_SLOT_STORE' for e in analysis.escapes)
    frame = DependencyFrame(namespace, invoke.id, None, None, namespace, entry=callee)
    branch_boundary = analyze_boundary(view, (P(namespace, branch.id, (frame,)),))
    assert len(branch_boundary.state) == 2
    assert all(s.kind == 'CONTROL_TRANSFER' and s.before_value.node == V('arg-state')
        and s.before_value.context == (frame,) for s in branch_boundary.state)
    assert all(s.mode_knowledge is BoundaryKnowledge.NOT_APPLICABLE for s in branch_boundary.state)
    assert {s.outcomes[0].value.node for s in branch_boundary.state} == {V('callee-normal-state'), V('callee-raised-state')}
    assert not branch_boundary.reads and not branch_boundary.writes
    import json
    from scar.analysis.program_dependency_export import export_boundary_analysis
    exported = export_boundary_analysis(analysis)
    json.dumps(exported, allow_nan=False)
    assert not exported['whole_program_complete'] and not exported['transformation_authorized']
    assert exported['boundary']['record_type'] == 'BoundaryAnalysis'
    assert exported['namespaces'] and exported['points']
    # Raw typed state/address/resource records remain present in the export.
    assert exported['boundary']['state'][1]['refinements']
    assert exported['boundary']['resources'][0]['requirement']['id']['original_id'] == RR('storage').wire
    # A complete readonly INVOKE can pass the original state through distinct
    # control Uses instead of producing a fresh CompletionResult. Associate
    # both landing ports with the actual call-state input without merging IDs.
    from dataclasses import replace
    passes = (Use(U('normal-state-pass'), V('s1'), UseRole.STATE_CONTENT),
        Use(U('raised-state-pass'), V('s1'), UseRole.STATE_CONTENT))
    readonly = replace(invoke, uses=(*invoke.uses, *passes), callee=None, effects_complete=True,
        behaviors=(Behavior.CONTROL, Behavior.READ, Behavior.MEMORY), completions=(
            CompletionSignature(ExitKind.NORMAL, (ref,)), CompletionSignature(ExitKind.RAISE, (ref, ref))),
        terminator=Terminator(TerminatorKind.INVOKE, (
            CompletionSuccessor(ExitKind.NORMAL, B('normal'), (CompletionResult(0), passes[0].id)),
            CompletionSuccessor(ExitKind.RAISE, B('raised'), (CompletionResult(0), CompletionResult(1), passes[1].id)))))
    readonly_graph = replace(graph, operations=tuple(readonly if op.id == invoke.id else op for op in graph.operations),
        state_address_refinements=tuple(r for r in graph.state_address_refinements if r.site.operation != invoke.id))
    readonly_index = ProgramIndex(readonly_graph)
    readonly_payload = dumps(readonly_graph).encode()
    readonly_path = tmp_path / 'readonly.json'; readonly_path.write_bytes(readonly_payload)
    readonly_sha = hashlib.sha256(readonly_payload).hexdigest()
    readonly_locator = SourceArtifactLocator(ProviderArtifact(str(readonly_path), readonly_sha, len(readonly_payload), 'scar.program-graph'),
        readonly_sha, len(readonly_payload), 'canonical-json')
    readonly_namespace = GraphNamespace(readonly_locator, namespace.representation, root)
    readonly_boundary = analyze_boundary(ProgramDependencyGraph(lambda ns: readonly_index), (P(readonly_namespace, readonly.id),))
    call_state = next(s for s in readonly_boundary.state if s.kind == 'INVOKE')
    assert {(s.kind, s.value.node) for s in call_state.outcomes} == {('NORMAL', V('s2')), ('RAISE', V('s3'))}
    assert call_state.before_value.node == V('s1')

    # Enumeration completeness must not depend on a provider inventing a
    # particular frontier name. The graph cut preserves its false marker.
    from scar.ir.program.dependencies import DependencyNeighborhood
    class IncompleteProvider:
        def incoming(self, point):
            return DependencyNeighborhood(enumerated=False)
        def outgoing(self, point):
            return DependencyNeighborhood(enumerated=False)
    view.register(IncompleteProvider())
    incomplete_boundary = analyze_boundary(view, (P(namespace, mutate.id),))
    assert any(f.kind == 'DEPENDENCY_BOUNDARY_ENUMERATION_OPEN' for f in incomplete_boundary.frontiers)
    assert incomplete_boundary.field('inputs').knowledge is BoundaryKnowledge.PARTIAL
    assert incomplete_boundary.field('consumers').knowledge is BoundaryKnowledge.PARTIAL

    # Reuse the existing valid binding fixture: its ordinary BOUND read may
    # return the original payload, rather than create a new ReferenceValue.
    # The binding-result edge therefore crosses the selected read's cut.
    from test_program_bindings import _bound_graph
    from scar.ir.program.dependencies import DependencyKind as DK
    binding_graph = _bound_graph()
    binding_index = ProgramIndex(binding_graph)
    binding_payload = dumps(binding_graph).encode()
    binding_path = tmp_path / 'bindings.json'; binding_path.write_bytes(binding_payload)
    binding_sha = hashlib.sha256(binding_payload).hexdigest()
    binding_locator = SourceArtifactLocator(ProviderArtifact(str(binding_path), binding_sha, len(binding_payload), 'scar.program-graph'),
        binding_sha, len(binding_payload), 'canonical-json')
    binding_namespace = GraphNamespace(binding_locator, namespace.representation, binding_graph.root)
    binding_view = ProgramDependencyGraph(lambda ns: binding_index)
    binding_boundary = analyze_boundary(binding_view, (P(binding_namespace, O('read')),))
    assert any(edge.kind is DK.BINDING_READ and edge.source.node == U('read.binding')
        and edge.target.node == V('payload') for edge in binding_boundary.consumers)
    assert any(edge.kind is DK.BINDING_PAYLOAD and edge.target.node == V('binding')
        for edge in binding_view.outgoing(P(binding_namespace, U('bind.payload'))).edges)
    assert path.read_bytes() == payload

    # Declaration membership is navigable without becoming value equality,
    # points-to or an executed language-completion transfer.
    from types import SimpleNamespace
    from test_program_environments import _environment_graph
    from tests.fixtures.program_control_graphs import _source
    from scar.analysis.program_value_analysis import ProgramValueAnalysis
    from scar.ir.program.control import ControlPort, ControlScope, ControlScopeKind, LanguageCompletionKind
    from scar.ir.program.dependencies import DependencyMeaning as DM
    from scar.ir.program.ids import ControlPortID, ControlScopeID
    env_graph = _environment_graph(invoke=True, unknown_targets=True)
    environment = env_graph.environments[0]
    owner = next(r for r in env_graph.regions if r.id == environment.region)
    scope = ControlScope(ControlScopeID('environment.function'), owner.id, None,
        ControlScopeKind.FUNCTION, _source('environment-declaration'), tuple(b.id for b in owner.blocks))
    block_port = ControlPort(ControlPortID('declared.block'), scope.id,
        LanguageCompletionKind.FALLTHROUGH, block=owner.entry)
    exit_port = ControlPort(ControlPortID('declared.exit'), scope.id,
        LanguageCompletionKind.RETURN, exit='normal')
    env_graph = replace(env_graph, control_scopes=(scope,), control_ports=(block_port, exit_port))
    env_index = ProgramIndex(env_graph)
    env_document = {'graph': json.loads(dumps(env_graph))}
    env_payload = json.dumps(env_document, sort_keys=True).encode()
    env_path = tmp_path / 'declarations.json'; env_path.write_bytes(env_payload)
    env_sha = hashlib.sha256(env_payload).hexdigest()
    env_locator = SourceArtifactLocator(ProviderArtifact(str(env_path), env_sha, len(env_payload), 'scar.program-graph'),
        env_sha, len(env_payload), 'canonical-json', pointer='#/graph')
    env_namespace = GraphNamespace(env_locator, namespace.representation, env_graph.root)
    env_view = ProgramDependencyGraph(lambda ns: env_index)
    env_point = P(env_namespace, environment.id)
    member = environment.members[-1]
    member_point = P(env_namespace, member.reference)
    declaration_edges = env_view.outgoing(env_point).edges
    assert {edge.target.node for edge in declaration_edges} == {m.reference for m in environment.members}
    assert all(edge.kind is DK.CONTAINS and edge.meaning is DM.STRUCTURE and not edge.conditions for edge in declaration_edges)
    member_edge = next(edge for edge in declaration_edges if edge.target == member_point)
    assert member_edge.evidence[0].sources[0].pointer == '#/graph/environments/0/members/5'
    assert member_edge.evidence[0].anchors == (env_point, member_point)
    assert env_document['graph']['environments'][0]['members'][5]['role'] == 'CAPTURED_CELL'
    assert env_document['graph']['environments'][0]['members'][5]['cell_position'] == 0
    member_inputs = env_view.incoming(member_point)
    assert any(edge.source.node == env_graph.locations[0].id and edge.kind is DK.STATE_LOCATION
        and edge.meaning is DM.STRUCTURE for edge in member_inputs.edges)
    assert not any(edge.kind is DK.ALIAS for edge in member_inputs.edges)
    assert any(edge.source.node == owner.id for edge in env_view.incoming(env_point).edges)
    block_declaration = env_view.outgoing(P(env_namespace, block_port.id))
    assert any(edge.target.node == owner.entry and edge.kind is DK.CONTROL_FLOW
        and edge.meaning is DM.STRUCTURE for edge in block_declaration.edges)
    named_exit = env_view.outgoing(P(env_namespace, exit_port.id))
    assert any(edge.target.node == owner.id and edge.kind is DK.CONTROL_FLOW
        and edge.meaning is DM.STRUCTURE
        and any(source.pointer == '#/graph/regions/1/exits/0' for source in edge.evidence[0].sources)
        for edge in named_exit.edges)
    assert any(f.kind == 'CONTROL_PORT_TRANSFER_RELATIONS_OPEN' for f in named_exit.frontiers)
    assert not any(f.kind == 'PROTOCOL_ENTITY_RELATIONS_OPEN' for f in env_view.outgoing(env_point).frontiers)
    env_caller = next(op for op in env_graph.operations if op.callee == owner.id)
    env_frame = DependencyFrame(env_namespace, env_caller.id, None, None, env_namespace, entry=owner.id)
    contextual_edge = next(edge for edge in env_view.outgoing(P(env_namespace, environment.id, (env_frame,))).edges
        if edge.target.node == member.reference)
    assert all(anchor.context == (env_frame,) for anchor in contextual_edge.evidence[0].anchors)
    env_session = SimpleNamespace(index=lambda ns: env_index, check=lambda: None)
    value_result = ProgramValueAnalysis(env_session, env_view).analyze((env_point, member_point))
    assert not value_result.edges  # Structural declaration edges never enter the value solver.
    assert not value_result.for_point(member_point).fields.reference_sources.alternatives
