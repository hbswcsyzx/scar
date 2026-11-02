"""Static scalar facts consume the shared contextual graph, not a second solver."""
import subprocess
import sys


def test_value_worklist_crosses_bindings_calls_and_preserves_unknown_paths(tmp_path):
    from scar.analysis.static_program import link_static_program
    from scar.analysis.program_dependency_session import ProgramDependencySession,ProgramDependencyBudget
    from scar.analysis.program_value_analysis import ProgramValueAnalysis,ValueAnalysisBudget,FieldPrecision
    from scar.ir.program.dependencies import DependencyPoint,GraphNamespace,DependencyKind as K
    from scar.ir.program.model import ExitKind,ValueKind
    from scar.ir.literals import PythonLiteral

    source=tmp_path/'source';source.mkdir();model=tmp_path/'model'
    text='''def add_one(value):
    return value + 1
def relay(value):
    return add_one(value)
def replaced(value):
    before = value
    value = 7
    return value + 1
def unresolved(value):
    value = opaque()
    return value
def accumulated(items):
    value = 0
    for item in items:
        value = value + 1
    return value
def make_pair(value):
    return (value, (8, 16))
def relay_pair(value):
    return make_pair(value)
def indexed_pair(value):
    return relay_pair(value)[1][-1]
def tuple_item(value, index):
    return value[index]
def overwritten_tuple(value):
    value = (value, 9)
    value = opaque()
    return value[0]
first = relay(4)
second = relay(9)
third = replaced(4)
fourth = unresolved(4)
looped = accumulated((1, 2, 3))
tuple_value = relay_pair(4)
tuple_selected = indexed_pair(4)
tuple_unknown_index = tuple_item((2, 3), fourth)
tuple_mutable = make_pair([])
tuple_overwritten = overwritten_tuple(4)
tuple_out_of_range = tuple_item((2, 3), 7)
tuple_bool_index = tuple_item((2, 3), True)
'''
    (source/'program.py').write_text(text)
    result=subprocess.run([sys.executable,'-B','-m','scar.cli','static',str(source),'--out',str(model),
        '--jobs','1','--phase','bodies'],capture_output=True,text=True)
    assert result.returncode==0,result.stdout+result.stderr
    link_static_program(model)
    with ProgramDependencySession(model,budget=ProgramDependencyBudget(max_graphs=32,max_seconds=120))as session:
        namespace,=session.select_bodies(file='program.py',entry='<module>')
        calls=[c for shard,locator in session.relation_shards(namespace)for c in shard.calls]
        roots=[]
        for line in ('first = relay(4)','second = relay(9)','third = replaced(4)','fourth = unresolved(4)',
                'looped = accumulated((1, 2, 3))','tuple_value = relay_pair(4)',
                'tuple_selected = indexed_pair(4)','tuple_unknown_index = tuple_item((2, 3), fourth)',
                'tuple_mutable = make_pair([])','tuple_overwritten = overwritten_tuple(4)',
                'tuple_out_of_range = tuple_item((2, 3), 7)','tuple_bool_index = tuple_item((2, 3), True)'):
            call,=[c for c in calls if c.source.start_line==text.splitlines().index(line)+1]
            target,=call.targets
            completion=next(r for r in target.completions if r.kind is ExitKind.NORMAL
                and r.value_kind is ValueKind.REFERENCE and r.completion_index==0)
            roots.append(DependencyPoint(GraphNamespace.from_source(namespace),completion.landing_value))
        analysis=ProgramValueAnalysis(session,budget=ValueAnalysisBudget(max_points=768,max_edges=2048,max_steps=8192))
        report=analysis.analyze(roots)
        assert report.exhausted,report.usage
        for point,expected in zip(roots,(5,10,8)):
            fact=report.for_point(point)
            values={alternative.value for alternative in fact.scalar_constant.alternatives}
            assert PythonLiteral.from_python(expected)in values,(expected,fact,report.frontiers)
            assert fact.scalar_constant.precision in(FieldPrecision.CONDITIONAL,FieldPrecision.CANDIDATE)
            assert all(a.evidence for a in fact.scalar_constant.alternatives)
            assert any(a.value=='builtins.int'for a in fact.builtin_type.alternatives)
        assert PythonLiteral.from_python(5)not in {a.value for a in report.for_point(roots[2]).scalar_constant.alternatives}
        assert not report.for_point(roots[3]).scalar_constant.alternatives
        assert report.for_point(roots[3]).scalar_constant.unknown_paths
        assert any(f.kind in('VALUE_FIELD_WIDENED','BUILTIN_ALTERNATIVE_BUDGET')for f in report.frontiers),report.usage
        assert len(report.for_point(roots[4]).scalar_constant.alternatives)<=analysis.budget.max_alternatives
        assert any(edge.kind is K.BINDING_PAYLOAD for edge in report.edges)
        assert any(edge.kind is K.BINDING_READ for edge in report.edges)
        assert any(edge.kind is K.ARGUMENT for edge in report.edges)
        assert any(edge.kind is K.COMPLETION for edge in report.edges)
        # Exact literal fields remain exact even though unrelated program
        # alias/effect information is open. Token content stays a named field.
        assert any(f.scalar_constant.precision is FieldPrecision.EXACT for f in report.facts)
        assert any(f.binding_payload is not None and f.scalar_constant.precision is FieldPrecision.NOT_APPLICABLE for f in report.facts)
        assert any(a.conditions for f in report.facts for a in f.scalar_constant.alternatives)
        tuple_fact=report.for_point(roots[5])
        assert {a.value for a in tuple_fact.immutable_tuple.alternatives}=={PythonLiteral.from_python((4,(8,16)),exact=True)}
        assert not tuple_fact.scalar_constant.alternatives
        assert {a.value for a in report.for_point(roots[6]).scalar_constant.alternatives}=={PythonLiteral.from_python(16)}
        for point in (roots[7],roots[8],roots[9],roots[10]):
            fact=report.for_point(point)
            assert not fact.scalar_constant.alternatives and not fact.immutable_tuple.alternatives
            assert fact.scalar_constant.unknown_paths or fact.immutable_tuple.unknown_paths
            assert fact.feasible is not False
        assert any(f.kind=='IMMUTABLE_INDEX_OUT_OF_RANGE'for f in report.frontiers)
        assert any(f.kind=='IMMUTABLE_INDEX_KEY_OPEN'for f in report.frontiers)
        assert any(f.kind=='IMMUTABLE_TUPLE_ELEMENT_OPEN'for f in report.frontiers)
        assert {a.value for a in report.for_point(roots[11]).scalar_constant.alternatives}=={PythonLiteral.from_python(3)}
        # Literal tuple contents remain independent of object identity and
        # cannot appear in the scalar field, including nested exact values.
        assert any(f.role=='LITERAL'and f.immutable_tuple.precision in(FieldPrecision.EXACT,FieldPrecision.CONDITIONAL)
            and f.scalar_constant.precision is FieldPrecision.NOT_APPLICABLE for f in report.facts)
        compiled_literal=next(f for f in report.facts if f.role=='LITERAL'and any(
            c.name=='ACTIVE_CODE_MATCHES_SOURCE_COMPILATION'for a in f.immutable_tuple.alternatives for c in a.conditions))
        assert analysis._compiled_bytes<=analysis.budget.max_compiled_bytes
        compile_limited=ProgramValueAnalysis(session,budget=ValueAnalysisBudget(max_compiled_bytes=1,
            max_points=1,max_edges=8,max_steps=8)).analyze((compiled_literal.point,))
        assert any(f.kind=='CODE_CONSTANT_CONTENT_BUDGET'for f in compile_limited.frontiers)
        literal=next(f for f in report.facts if f.role=='LITERAL'and f.scalar_constant.precision is FieldPrecision.EXACT)
        limited=ProgramValueAnalysis(session,budget=ValueAnalysisBudget(max_points=1,max_edges=8,max_steps=8)).analyze((literal.point,roots[0]))
        assert not limited.exhausted and any(f.kind=='VALUE_POINT_BUDGET'for f in limited.frontiers)
        assert limited.for_point(literal.point).scalar_constant.precision is FieldPrecision.EXACT
        # The public normalized record retains field uncertainty and original
        # qualified endpoints instead of dumping a second copy of each graph.
        import json
        from scar.analysis.program_dependency_export import export_value_analysis
        exported = export_value_analysis(report)
        json.dumps(exported, allow_nan=False)
        assert not exported['whole_program_complete'] and not exported['transformation_authorized']
        assert exported['schema_version']==2
        assert all('immutable_tuple'in f['fields']for f in exported['facts'])
        assert exported['fixed_point_reached'] == report.exhausted
        assert len(exported['facts']) == len(report.facts)
        assert all(0 <= fact['point'] < len(exported['points']) for fact in exported['facts'])
        exported_roots = {fact['point']: fact for fact in exported['facts']}
        for root in exported['roots'][:3]:
            assert exported_roots[root]['fields']['scalar_constant']['precision'] in ('CONDITIONAL', 'CANDIDATE')
            assert exported_roots[root]['fields']['scalar_constant']['alternatives']


def test_original_local_result_coverage_does_not_close_candidate_dispatch(tmp_path):
    """A declared interface differs from one possible target's completion.

    The candidate target's local read has a dormant, infeasible NORMAL port.
    That target cannot prove the unresolved dispatch itself has no normal
    result. No source program, callable, or target module executes here.
    """
    import hashlib
    import pytest
    from types import SimpleNamespace
    from scar.analysis.program_dependencies import ProgramDependencyGraph
    from scar.analysis.program_value_analysis import ProgramValueAnalysis,FieldPrecision,ValueFields,ValueField,ValueAlternative
    from scar.ir.program import (Behavior,BindingDefinition,BindingRead,BindingState,
        Block,BlockArgument,CompletionResult,CompletionSignature,CompletionSuccessor,
        DataValue,ExitKind,ExitPort,LocalBindingValue,LiteralOrigin,ExactLiteralOrigin,Operation,OperationResult,
        ProgramGraph,ReferenceValue,Region,StateLocation,StateVersionValue,
        Successor,Terminator,TerminatorKind,Use,UseRole,ValueKind,ValueType)
    from scar.ir.program.codec import SCHEMA_VERSION,dumps
    from scar.ir.program.dependencies import (DependencyCondition,DependencyEdge,DependencyEvidence,
        DependencyFrame,DependencyKind as K,DependencyMeaning as M,DependencyNeighborhood,
        DependencyPoint as P,DependencyStrength,GraphNamespace)
    from scar.ir.program.ids import (BlockID as B,LocationID as L,OperationID as O,
        RegionID as R,UseID as U,ValueID as V)
    from scar.ir.program.providers import ProviderArtifact
    from scar.ir.program.queries import ProgramIndex
    from scar.ir.program.source_references import SourceArtifactLocator
    from scar.ir.program.validation import validate
    from scar.ir.v2.ids import ValueSlotID
    from scar.ir.literals import PythonLiteral

    forged=PythonLiteral.from_python(((1,),),exact=True)
    object.__setattr__(forged.items[0],'items',([1],))
    with pytest.raises(TypeError,match='PythonLiteral'):
        ValueFields(immutable_tuple=ValueField((ValueAlternative(forged),)))

    root,good,bad=R('caller'),R('declared'),R('possible')
    world=L('world');ref=ValueType(ValueKind.REFERENCE);state=ValueType(ValueKind.STATE,location=world)
    signature=(ref,state)
    values=(
        ReferenceValue(V('known-result'),root,OperationResult(O('declared-call'),0)),
        ReferenceValue(V('candidate-result'),root,OperationResult(O('candidate-call'),0)),
        ReferenceValue(V('seven'),good,LiteralOrigin(7),targets=()),
        StateVersionValue(V('world-in'),bad,BlockArgument(B('bad-entry'),0),world),
        LocalBindingValue(V('unbound'),bad,OperationResult(O('unbind'),0),ValueSlotID('missing')),
        ReferenceValue(V('dormant-normal'),bad,BlockArgument(B('bad-normal'),0)),
        StateVersionValue(V('world-normal'),bad,BlockArgument(B('bad-normal'),1),world),
        ReferenceValue(V('exception'),bad,BlockArgument(B('bad-raise'),0)),
        StateVersionValue(V('world-raise'),bad,BlockArgument(B('bad-raise'),1),world))
    exact_literal=PythonLiteral.from_python((complex(-0.0,1.0),'\ud800',-0.0),exact=True)
    values=(*values,DataValue(V('exact-tuple-bits'),root,ExactLiteralOrigin(exact_literal),'builtins.tuple'))
    declared=Operation(O('declared-call'),'ordinary local region',(Behavior.CONTROL,),
        results=(V('known-result'),),effects_complete=True,callee=good)
    candidate=Operation(O('candidate-call'),'unresolved dispatch',(Behavior.COMPUTE,),
        results=(V('candidate-result'),),effects_complete=True)

    def finish(name,kind,names,exit_name):
        uses=tuple(Use(U(name+':'+str(i)),V(value),UseRole.STATE_CONTENT if value.startswith('world-')
            else UseRole.REFERENCE)for i,value in enumerate(names))
        return Operation(O(name),name,(Behavior.CONTROL,),uses,effects_complete=True,
            terminator=Terminator(kind,exit=exit_name,values=tuple(u.id for u in uses)))

    returned=finish('root-return',TerminatorKind.RETURN,('candidate-result',),'normal')
    seven=finish('seven-return',TerminatorKind.RETURN,('seven',),'normal')
    unbind=Operation(O('unbind'),'unbound slot',(Behavior.COMPUTE,),results=(V('unbound'),),effects_complete=True)
    binding=Use(U('read-binding'),V('unbound'),UseRole.LOCAL_BINDING)
    before=Use(U('read-world'),V('world-in'),UseRole.STATE_CONTENT)
    read=Operation(O('read'),'local read',(Behavior.CONTROL,Behavior.READ,Behavior.WRITE),(binding,before),
        effects_complete=False,terminator=Terminator(TerminatorKind.INVOKE,(
            CompletionSuccessor(ExitKind.NORMAL,B('bad-normal'),(CompletionResult(0),CompletionResult(1))),
            CompletionSuccessor(ExitKind.RAISE,B('bad-raise'),(CompletionResult(0),CompletionResult(1))))),
        completions=(CompletionSignature(ExitKind.NORMAL,signature),CompletionSignature(ExitKind.RAISE,signature)),
        invoke_arguments=(binding.id,before.id))
    dormant=finish('dormant-return',TerminatorKind.RETURN,('dormant-normal','world-normal'),'normal')
    raised=finish('bad-raised',TerminatorKind.RAISE,('exception','world-raise'),'raise')
    graph=ProgramGraph(root,(
        Region(root,'caller',B('entry'),(Block(B('entry'),(),(declared.id,candidate.id,returned.id)),),
            (ExitPort('normal',ExitKind.NORMAL,(ref,)),)),
        Region(good,'declared implementation',B('good-entry'),(Block(B('good-entry'),(),(seven.id,)),),
            (ExitPort('normal',ExitKind.NORMAL,(ref,)),),parent=root),
        Region(bad,'possible implementation',B('bad-entry'),(
            Block(B('bad-entry'),(V('world-in'),),(unbind.id,read.id)),
            Block(B('bad-normal'),(V('dormant-normal'),V('world-normal')),(dormant.id,)),
            Block(B('bad-raise'),(V('exception'),V('world-raise')),(raised.id,))),
            (ExitPort('normal',ExitKind.NORMAL,signature),ExitPort('raise',ExitKind.RAISE,signature)),parent=root)),
        (declared,candidate,returned,seven,unbind,read,dormant,raised),values,
        (StateLocation(world,'opaque frame world'),),
        binding_definitions=(BindingDefinition(V('unbound'),BindingState.UNBOUND),),
        binding_reads=(BindingRead(read.id,binding.id,V('dormant-normal')),))
    # A typed external input still has unknown scalar *content*. Its phi
    # alternative must remain open alongside the exact constant branch.
    from dataclasses import replace
    phi=R('typed-phi')
    unknown=DataValue(V('unknown-int'),phi,BlockArgument(B('phi-entry'),0),'builtins.int')
    predicate=DataValue(V('predicate'),phi,BlockArgument(B('phi-entry'),1),'builtins.bool')
    literal=DataValue(V('phi-seven'),phi,LiteralOrigin(7),'builtins.int')
    merged=DataValue(V('merged-int'),phi,BlockArgument(B('phi-join'),0),'builtins.int')
    phi_uses=(Use(U('phi-unknown'),unknown.id),Use(U('phi-literal'),literal.id),Use(U('phi-predicate'),predicate.id))
    branch=Operation(O('phi-branch'),'two alternatives',(Behavior.CONTROL,),phi_uses,effects_complete=True,
        terminator=Terminator(TerminatorKind.BRANCH,(
            Successor(B('phi-join'),(phi_uses[0].id,)),Successor(B('phi-join'),(phi_uses[1].id,))),
            condition=phi_uses[2].id))
    phi_return_use=Use(U('phi-return-value'),merged.id)
    phi_return=Operation(O('phi-return'),'return merged value',(Behavior.CONTROL,),(phi_return_use,),effects_complete=True,
        terminator=Terminator(TerminatorKind.RETURN,exit='normal',values=(phi_return_use.id,)))
    phi_region=Region(phi,'typed external input',B('phi-entry'),(
        Block(B('phi-entry'),(unknown.id,predicate.id),(branch.id,)),
        Block(B('phi-join'),(merged.id,),(phi_return.id,))),
        (ExitPort('normal',ExitKind.NORMAL,(ValueType(ValueKind.DATA,data_type='builtins.int'),)),),parent=root)
    graph=replace(graph,regions=(*graph.regions,phi_region),operations=(*graph.operations,branch,phi_return),
        values=(*graph.values,unknown,predicate,literal,merged))
    assert validate(graph)==()
    index=ProgramIndex(graph);payload=dumps(graph).encode();path=tmp_path/'original.json';path.write_bytes(payload)
    sha=hashlib.sha256(payload).hexdigest()
    locator=SourceArtifactLocator(ProviderArtifact(str(path),sha,len(payload),'scar.program-graph'),
        sha,len(payload),'canonical-json')
    namespace=GraphNamespace(locator,'scar.program-graph/'+str(SCHEMA_VERSION),root)
    frame=DependencyFrame(namespace,candidate.id,None,None,namespace,entry=bad)
    possible_source=P(namespace,dormant.uses[0].id,(frame,));possible_result=P(namespace,V('candidate-result'))
    condition=DependencyCondition('test.dispatch','TARGET_SELECTED',P(namespace,candidate.id))
    evidence=DependencyEvidence('POSSIBLE_TARGET_INTERFACE_V1',(locator,),(possible_source,possible_result))
    completion=DependencyEdge(possible_source,possible_result,K.COMPLETION,M.VALUE,(evidence,),(condition,),DependencyStrength.EXACT)

    class PossibleTarget:
        def incoming(self,point):return DependencyNeighborhood((completion,)if point==possible_result else())
        def outgoing(self,point):return DependencyNeighborhood((completion,)if point==possible_source else())

    view=ProgramDependencyGraph(lambda ns:index,providers=(PossibleTarget(),))
    # This original non-source fragment has no Python opcode metadata; an
    # absent operator contract is represented as uncertainty, not a crash.
    body=SimpleNamespace(graph=graph,index=index)
    session=SimpleNamespace(index=lambda ns:index,load=lambda ns:body,check=lambda:None)
    known=P(namespace,V('known-result'))
    merged_point=P(namespace,merged.id)
    exact_point=P(namespace,V('exact-tuple-bits'))
    analysis=ProgramValueAnalysis(session,view)
    report=analysis.analyze((known,possible_result,merged_point,exact_point))
    exact=report.for_point(known);uncertain=report.for_point(possible_result)
    assert exact.scalar_constant.precision is FieldPrecision.EXACT
    assert {a.value for a in exact.scalar_constant.alternatives}=={PythonLiteral.from_python(7)}
    assert not any(f.kind=='PRODUCER_VALUE_CONTRACT_OPEN'for f in exact.scalar_constant.unknown_paths)
    assert report.for_point(possible_source).feasible is False
    assert uncertain.feasible is None
    assert uncertain.scalar_constant.precision is FieldPrecision.UNKNOWN
    assert any(f.kind=='PRODUCER_VALUE_CONTRACT_OPEN'for f in uncertain.scalar_constant.unknown_paths)
    phi_fact=report.for_point(merged_point)
    assert {a.value for a in phi_fact.scalar_constant.alternatives}=={PythonLiteral.from_python(7)}
    assert phi_fact.scalar_constant.precision is FieldPrecision.CANDIDATE
    assert phi_fact.scalar_constant.unknown_paths
    assert phi_fact.builtin_type.precision is FieldPrecision.EXACT
    assert phi_fact.immutable_tuple.precision is FieldPrecision.NOT_APPLICABLE
    assert report.for_point(P(namespace,unknown.id)).scalar_constant.precision is FieldPrecision.UNKNOWN
    assert report.for_point(exact_point).immutable_tuple.precision is FieldPrecision.EXACT
    assert report.for_point(exact_point).immutable_tuple.alternatives[0].value==exact_literal
    assert report.for_point(exact_point).scalar_constant.precision is FieldPrecision.NOT_APPLICABLE
    scalar_source=next(f for f in report.facts if f.role=='LITERAL'and f.scalar_constant.alternatives)
    may=replace(completion,source=scalar_source.point,strength=DependencyStrength.MAY,
        evidence=(DependencyEvidence('DECLARED_MAY_VALUE_ALTERNATIVE_V1',(locator,),
            (scalar_source.point,possible_result)),))
    transferred=analysis._transfer(scalar_source.fields,may)
    assert transferred.immutable_tuple.applicable and transferred.immutable_tuple.unknown_paths
    joined=analysis._join(possible_result,ValueFields(),transferred)
    assert joined.immutable_tuple.precision is FieldPrecision.UNKNOWN and joined.immutable_tuple.unknown_paths
    # The same may alternative cannot change a declared builtin-int target
    # into a possible tuple. Its scalar content remains an open alternative.
    typed_may=replace(completion,source=P(namespace,U('phi-literal')),target=merged_point,
        kind=K.BLOCK_ARGUMENT,strength=DependencyStrength.MAY,
        evidence=(DependencyEvidence('DECLARED_MAY_PHI_ALTERNATIVE_V1',(locator,),
            (P(namespace,U('phi-literal')),merged_point)),))
    class TypedMay:
        def incoming(self,point):return DependencyNeighborhood((typed_may,)if point==merged_point else())
        def outgoing(self,point):return DependencyNeighborhood((typed_may,)if point==typed_may.source else())
    view.register(TypedMay())
    typed_report=ProgramValueAnalysis(session,view).analyze((merged_point,))
    assert typed_report.for_point(merged_point).immutable_tuple.precision is FieldPrecision.NOT_APPLICABLE
    assert typed_report.for_point(merged_point).scalar_constant.unknown_paths
