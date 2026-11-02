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
        assert exported['fixed_point_reached'] == report.worklist_stable
        assert exported['query_scope_complete'] == report.exhausted
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
    from scar.analysis.program_value_analysis import (ProgramValueAnalysis,ValueAnalysisBudget,FieldPrecision,
        ValueFields,ValueField,ValueAlternative,BindingStateAlternative)
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
    # One original callee has three separate static activation contexts:
    # true, false and an unknown builtin bool. Closed facts never union them.
    call_x=DataValue(V('call-x'),root,LiteralOrigin(41),'builtins.int')
    call_true=DataValue(V('call-true'),root,LiteralOrigin(True),'builtins.bool')
    call_false=DataValue(V('call-false'),root,LiteralOrigin(False),'builtins.bool')
    call_unknown=DataValue(V('call-unknown'),root,BlockArgument(B('entry'),0),'builtins.bool')
    call_guarded=DataValue(V('call-guarded'),root,OperationResult(O('guarded-source'),0),'builtins.bool')
    guarded_source=Operation(O('guarded-source'),'conditional provider field',(Behavior.COMPUTE,),
        results=(call_guarded.id,),effects_complete=True)
    direct=[];direct_values=[]
    for name,flag in(('true',call_true),('false',call_false),('unknown',call_unknown),('guarded',call_guarded)):
        uses=(Use(U('call-'+name+'-x'),call_x.id),Use(U('call-'+name+'-flag'),flag.id))
        value=DataValue(V('call-'+name+'-result'),root,OperationResult(O('call-'+name),0),'builtins.int')
        direct.append(Operation(O('call-'+name),'declared phi call',(Behavior.CONTROL,),uses,(value.id,),
            effects_complete=True,callee=phi,call_arguments=tuple(u.id for u in uses)))
        direct_values.append(value)
    root_region=replace(graph.regions[0],blocks=(replace(graph.regions[0].blocks[0],arguments=(call_unknown.id,),
        operations=(declared.id,candidate.id,guarded_source.id,*(op.id for op in direct),returned.id)),))
    graph=replace(graph,regions=(root_region,*graph.regions[1:]),operations=(*graph.operations,guarded_source,*direct),
        values=(*graph.values,call_x,call_true,call_false,call_unknown,call_guarded,*direct_values))

    # A loop-carried predicate starts at True and can acquire False. It must
    # settle (or widen) before any branch choice is considered proved.
    loop=R('bool-loop')
    loop_true=DataValue(V('loop-true'),loop,LiteralOrigin(True),'builtins.bool')
    loop_false=DataValue(V('loop-false'),loop,LiteralOrigin(False),'builtins.bool')
    loop_phi=DataValue(V('loop-phi'),loop,BlockArgument(B('loop-header'),0),'builtins.bool')
    loop_seed_use=Use(U('loop-seed'),loop_true.id)
    loop_jump=Operation(O('loop-jump'),'initial loop edge',(Behavior.CONTROL,),(loop_seed_use,),effects_complete=True,
        terminator=Terminator(TerminatorKind.JUMP,(Successor(B('loop-header'),(loop_seed_use.id,)),)))
    loop_condition=Use(U('loop-condition'),loop_phi.id);loop_next=Use(U('loop-next'),loop_false.id)
    loop_branch=Operation(O('loop-branch'),'loop selection',(Behavior.CONTROL,),(loop_condition,loop_next),effects_complete=True,
        terminator=Terminator(TerminatorKind.BRANCH,(Successor(B('loop-header'),(loop_next.id,)),
            Successor(B('loop-exit'),())),condition=loop_condition.id))
    loop_return=Operation(O('loop-return'),'loop return',(Behavior.CONTROL,),effects_complete=True,
        terminator=Terminator(TerminatorKind.RETURN,exit='normal'))
    loop_region=Region(loop,'bool loop',B('loop-entry'),(Block(B('loop-entry'),(),(loop_jump.id,)),
        Block(B('loop-header'),(loop_phi.id,),(loop_branch.id,)),Block(B('loop-exit'),(),(loop_return.id,))),
        (ExitPort('normal',ExitKind.NORMAL,()),),parent=root)
    graph=replace(graph,regions=(*graph.regions,loop_region),operations=(*graph.operations,loop_jump,loop_branch,loop_return),
        values=(*graph.values,loop_true,loop_false,loop_phi))
    # Original diamonds carry values via JUMP Uses, not BRANCH actuals.
    # A wrapper adds a second genuine direct-call frame without cloning nodes.
    jump_region=R('jump-phi');jump_flag=DataValue(V('jump-flag'),jump_region,BlockArgument(B('jump-entry'),0),'builtins.bool')
    jump_yes=DataValue(V('jump-seven'),jump_region,LiteralOrigin(7),'builtins.int')
    jump_no=DataValue(V('jump-ninety-nine'),jump_region,LiteralOrigin(99),'builtins.int')
    jump_merged=DataValue(V('jump-merged'),jump_region,BlockArgument(B('jump-join'),0),'builtins.int')
    jump_condition=Use(U('jump-condition'),jump_flag.id)
    jump_branch=Operation(O('jump-branch'),'original selection',(Behavior.CONTROL,),(jump_condition,),effects_complete=True,
        terminator=Terminator(TerminatorKind.BRANCH,(Successor(B('jump-yes'),()),Successor(B('jump-no'),())),condition=jump_condition.id))
    jump_sources=[];jump_terms=[]
    for name,value in(('yes',jump_yes),('no',jump_no)):
        carried=Use(U('jump-'+name+'-value'),value.id);jump_sources.append(carried)
        jump_terms.append(Operation(O('jump-'+name),'original carry',(Behavior.CONTROL,),(carried,),effects_complete=True,
            terminator=Terminator(TerminatorKind.JUMP,(Successor(B('jump-join'),(carried.id,)),))))
    jump_return_use=Use(U('jump-return-value'),jump_merged.id)
    jump_return=Operation(O('jump-return'),'return original phi',(Behavior.CONTROL,),(jump_return_use,),effects_complete=True,
        terminator=Terminator(TerminatorKind.RETURN,exit='normal',values=(jump_return_use.id,)))
    int_port=ValueType(ValueKind.DATA,data_type='builtins.int')
    jump_body=Region(jump_region,'JUMP phi',B('jump-entry'),(Block(B('jump-entry'),(jump_flag.id,),(jump_branch.id,)),
        Block(B('jump-yes'),(),(jump_terms[0].id,)),Block(B('jump-no'),(),(jump_terms[1].id,)),
        Block(B('jump-join'),(jump_merged.id,),(jump_return.id,))),(ExitPort('normal',ExitKind.NORMAL,(int_port,)),),parent=root)
    wrapper=R('jump-wrapper');wrapper_flag=DataValue(V('wrapper-flag'),wrapper,BlockArgument(B('wrapper-entry'),0),'builtins.bool')
    wrapper_argument=Use(U('wrapper-argument'),wrapper_flag.id)
    wrapper_value=DataValue(V('wrapper-result'),wrapper,OperationResult(O('wrapper-call'),0),'builtins.int')
    wrapper_call=Operation(O('wrapper-call'),'original nested call',(Behavior.CONTROL,),(wrapper_argument,),(wrapper_value.id,),
        effects_complete=True,callee=jump_region,call_arguments=(wrapper_argument.id,))
    wrapper_use=Use(U('wrapper-return-value'),wrapper_value.id)
    wrapper_return=Operation(O('wrapper-return'),'return original nested result',(Behavior.CONTROL,),(wrapper_use,),effects_complete=True,
        terminator=Terminator(TerminatorKind.RETURN,exit='normal',values=(wrapper_use.id,)))
    wrapper_body=Region(wrapper,'nested caller',B('wrapper-entry'),(
        Block(B('wrapper-entry'),(wrapper_flag.id,),(wrapper_call.id,wrapper_return.id)),),
        (ExitPort('normal',ExitKind.NORMAL,(int_port,)),),parent=root)
    # True enters an infinite CFG cycle; its only NORMAL exit is statically
    # unreachable. Proving that normal value absent is not proving termination.
    never=R('never-normal');never_flag=DataValue(V('never-flag'),never,BlockArgument(B('never-entry'),0),'builtins.bool')
    never_literal=DataValue(V('never-seven'),never,LiteralOrigin(7),'builtins.int')
    never_condition=Use(U('never-condition'),never_flag.id)
    never_branch=Operation(O('never-branch'),'entry choice',(Behavior.CONTROL,),(never_condition,),effects_complete=True,
        terminator=Terminator(TerminatorKind.BRANCH,(Successor(B('never-cycle'),()),Successor(B('never-exit'),())),condition=never_condition.id))
    never_cycle=Operation(O('never-cycle-jump'),'original cycle',(Behavior.CONTROL,),effects_complete=True,
        terminator=Terminator(TerminatorKind.JUMP,(Successor(B('never-cycle'),()),)))
    never_use=Use(U('never-return-value'),never_literal.id)
    never_return=Operation(O('never-return'),'only normal exit',(Behavior.CONTROL,),(never_use,),effects_complete=True,
        terminator=Terminator(TerminatorKind.RETURN,exit='normal',values=(never_use.id,)))
    never_body=Region(never,'normal completion may not exist',B('never-entry'),(
        Block(B('never-entry'),(never_flag.id,),(never_branch.id,)),Block(B('never-cycle'),(),(never_cycle.id,)),
        Block(B('never-exit'),(),(never_return.id,))),(ExitPort('normal',ExitKind.NORMAL,(int_port,)),),parent=root)
    new_calls=[];new_values=[]
    for name,target,flag in(('jump-true',jump_region,call_true),('jump-false',jump_region,call_false),
            ('jump-unknown',jump_region,call_unknown),('nested-true',wrapper,call_true),('nested-false',wrapper,call_false),
            ('never-true',never,call_true),('never-unknown',never,call_unknown)):
        argument=Use(U(name+'-argument'),flag.id)
        result=DataValue(V(name+'-result'),root,OperationResult(O(name+'-call'),0),'builtins.int')
        new_calls.append(Operation(O(name+'-call'),'original typed call',(Behavior.CONTROL,),(argument,),(result.id,),
            effects_complete=True,callee=target,call_arguments=(argument.id,)))
        new_values.append(result)
    root_region=replace(graph.regions[0],blocks=(replace(graph.regions[0].blocks[0],operations=(
        *graph.regions[0].blocks[0].operations[:-1],*(op.id for op in new_calls),returned.id)),))
    graph=replace(graph,regions=(root_region,*graph.regions[1:],jump_body,wrapper_body,never_body),
        operations=(*graph.operations,jump_branch,*jump_terms,jump_return,wrapper_call,wrapper_return,
            never_branch,never_cycle,never_return,*new_calls),values=(*graph.values,jump_flag,jump_yes,jump_no,jump_merged,
                wrapper_flag,wrapper_value,never_flag,never_literal,*new_values))
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
    guarded_input=P(namespace,U('call-true-flag'));guarded_value=P(namespace,call_guarded.id)
    guarded_edge=DependencyEdge(guarded_input,guarded_value,K.STATE_VALUE,M.VALUE,
        (DependencyEvidence('DECLARED_CONDITIONAL_FIELD_V1',(locator,),(guarded_input,guarded_value)),),
        (DependencyCondition('test.runtime','ACTIVE_FLAG_CONTRACT',P(namespace,guarded_source.id)),))

    class PossibleTarget:
        def incoming(self,point):return DependencyNeighborhood(tuple(e for e in(completion,guarded_edge)if e.target==point))
        def outgoing(self,point):return DependencyNeighborhood(tuple(e for e in(completion,guarded_edge)if e.source==point))

    view=ProgramDependencyGraph(lambda ns:index,providers=(PossibleTarget(),))
    # This original non-source fragment has no Python opcode metadata; an
    # absent operator contract is represented as uncertainty, not a crash.
    body=SimpleNamespace(graph=graph,index=index)
    session=SimpleNamespace(index=lambda ns:index,load=lambda ns:body,check=lambda:None)
    known=P(namespace,V('known-result'))
    merged_point=P(namespace,merged.id)
    exact_point=P(namespace,V('exact-tuple-bits'))
    analysis=ProgramValueAnalysis(session,view)
    direct_points=tuple(P(namespace,v.id)for v in direct_values)
    report=analysis.analyze((known,possible_result,merged_point,exact_point,*direct_points))
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
    for point,expected in zip(direct_points,(41,7,None,None)):
        fact=report.for_point(point);values={a.value for a in fact.scalar_constant.alternatives}
        assert values==({PythonLiteral.from_python(expected)}if expected is not None else
            {PythonLiteral.from_python(41),PythonLiteral.from_python(7)})
        if expected is not None:
            assert not fact.scalar_constant.unknown_paths
            assert any(e.rule.startswith('STABLE_BUILTIN_BOOL_SELECTS_SUCCESSOR_')
                for a in fact.scalar_constant.alternatives for e in a.evidence)
    assert len(report.branch_proofs)==2
    frames=tuple(DependencyFrame(namespace,op.id,None,None,namespace,entry=phi)for op in direct)
    assert {(p.branch.context,p.selected_index)for p in report.branch_proofs}=={((frames[0],),0),((frames[1],),1)}
    assert all(p.predicate.node==phi_uses[2].id and p.branch.node==branch.id for p in report.branch_proofs)
    assert any(f.kind=='BRANCH_PREDICATE_GUARDS_OPEN'and f.point.context==(frames[3],)for f in report.frontiers)
    assert any(edge.kind is K.CONTROL_CONDITION for edge in report.edges)
    assert {c.index for edge in report.edges if edge.target.context==(frames[0],)for c in edge.conditions
        if c.name=='SUCCESSOR_SELECTED'and c.subject.node==branch.id}=={0,1},'original false-arm edges remain auditable'
    import json
    from scar.analysis.program_dependency_export import export_value_analysis
    exported=export_value_analysis(report);json.dumps(exported,allow_nan=False)
    proof=next(p for p in exported['branch_proofs']if p['selected_index']==0)
    branch_ref=proof['branch']['point'];predicate_ref=proof['predicate']['point']
    assert exported['points'][branch_ref]['node']==branch.id.wire
    assert exported['points'][predicate_ref]['node']==phi_uses[2].id.wire
    proof_evidence=exported['evidence'][proof['evidence']['evidence']]
    assert proof_evidence['rule']=='STABLE_BUILTIN_BOOL_SELECTS_SUCCESSOR_0_V1'
    assert branch_ref in proof_evidence['anchors']and predicate_ref in proof_evidence['anchors']
    rejected=next(e for e in exported['edges']if e['kind']=='BLOCK_ARGUMENT'and any(
        exported['conditions'][c]['subject']==branch_ref and exported['conditions'][c]['index']==1
        and exported['conditions'][c]['name']=='SUCCESSOR_SELECTED'for c in e['conditions']))
    rejected_fact=next(f for f in exported['facts']if f['point']==rejected['source'])
    assert {a['value']['literal']['payload']for a in rejected_fact['fields']['scalar_constant']['alternatives']}=={'7'}
    selected_fact=next(f for f in exported['facts']if f['point']==exported['roots'][4])
    assert {a['value']['literal']['payload']for a in selected_fact['fields']['scalar_constant']['alternatives']}=={'41'}
    stopped=ProgramValueAnalysis(session,view,budget=ValueAnalysisBudget(max_steps=1)).analyze((direct_points[0],))
    assert not stopped.exhausted and not stopped.branch_proofs
    assert any(f.kind=='VALUE_FIXED_POINT_BUDGET'for f in stopped.frontiers)
    widened=ProgramValueAnalysis(session,view,budget=ValueAnalysisBudget(max_alternatives=1)).analyze((P(namespace,loop_condition.id),))
    assert not widened.branch_proofs and any(f.kind=='VALUE_FIELD_WIDENED'for f in widened.frontiers)
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

    # Independent binding-state facts must not inherit payload precision, or
    # lose missing/MAY paths behind a convenient singleton state projection.
    with pytest.raises(TypeError,match='unknown paths'):
        BindingStateAlternative(BindingState.UNKNOWN)
    unbound_fact=report.for_point(P(namespace,binding.id,(frame,)))
    assert unbound_fact.binding_states==(BindingState.UNBOUND,)
    assert unbound_fact.binding_state.precision is FieldPrecision.EXACT
    assert not report.binding_proofs
    bound_payload=ReferenceValue(V('binding-true'),bad,LiteralOrigin(True),targets=())
    bound_use=Use(U('bind-payload'),bound_payload.id,UseRole.REFERENCE)
    bound_definition=replace(unbind,uses=(bound_use,))
    bound_graph=replace(graph,
        operations=tuple(bound_definition if op.id==unbind.id else op for op in graph.operations),
        values=(*graph.values,bound_payload),
        binding_definitions=(BindingDefinition(V('unbound'),BindingState.BOUND,bound_use.id),))

    def binding_scope(original,name):
        assert validate(original)==()
        encoded=dumps(original).encode();saved=tmp_path/(name+'.json');saved.write_bytes(encoded)
        digest=hashlib.sha256(encoded).hexdigest()
        source=SourceArtifactLocator(ProviderArtifact(str(saved),digest,len(encoded),'scar.program-graph'),
            digest,len(encoded),'canonical-json')
        ns=GraphNamespace(source,'scar.program-graph/'+str(SCHEMA_VERSION),root)
        original_index=ProgramIndex(original);body=SimpleNamespace(graph=original,index=original_index)
        scoped=SimpleNamespace(index=lambda _:original_index,load=lambda _:body,check=lambda:None)
        return ns,scoped,ProgramDependencyGraph(lambda _:original_index)

    bound_ns,bound_session,bound_view=binding_scope(bound_graph,'binding-states')
    bound_frame=DependencyFrame(bound_ns,candidate.id,None,None,bound_ns,entry=bad)
    normal_bound=P(bound_ns,V('dormant-normal'));normal_may=P(bound_ns,V('dormant-normal'),(bound_frame,))
    may_binding=DependencyEdge(P(bound_ns,V('unbound'),(bound_frame,)),P(bound_ns,binding.id,(bound_frame,)),
        K.STATE_VALUE,M.BINDING,(DependencyEvidence('POSSIBLE_BINDING_INPUT_V1',(bound_ns.graph,),
            (P(bound_ns,V('unbound'),(bound_frame,)),P(bound_ns,binding.id,(bound_frame,)))),),
        strength=DependencyStrength.MAY)
    class MaybeBinding:
        def incoming(self,point):return DependencyNeighborhood((may_binding,)if point==may_binding.target else())
        def outgoing(self,point):return DependencyNeighborhood((may_binding,)if point==may_binding.source else())
    bound_view.register(MaybeBinding())
    bound_report=ProgramValueAnalysis(bound_session,bound_view).analyze((normal_bound,normal_may))
    assert bound_report.exhausted and bound_report.for_point(normal_bound).feasible is True
    assert bound_report.for_point(normal_may).feasible is None
    may_state=bound_report.for_point(may_binding.target)
    assert may_state.binding_states==(BindingState.BOUND,)and may_state.binding_state.unknown_paths
    assert {proof.read.context for proof in bound_report.binding_proofs}=={()}
    bound_stopped=ProgramValueAnalysis(bound_session,bound_view,budget=ValueAnalysisBudget(max_steps=1)).analyze((P(bound_ns,binding.id),))
    assert not bound_stopped.exhausted and not bound_stopped.binding_proofs
    assert bound_stopped.for_point(P(bound_ns,binding.id)).binding_state.unknown_paths
    # A singleton UNBOUND projection with a MAY/open source must not make
    # the normal port infeasible. The full independent field is authoritative.
    unbound_may=replace(may_binding,source=P(namespace,V('unbound'),(frame,)),
        target=P(namespace,binding.id,(frame,)))
    class MayUnbound:
        def incoming(self,point):return DependencyNeighborhood((unbound_may,)if point==unbound_may.target else())
        def outgoing(self,point):return DependencyNeighborhood((unbound_may,)if point==unbound_may.source else())
    may_unbound_view=ProgramDependencyGraph(lambda _:index,providers=(MayUnbound(),))
    unbound_open=ProgramValueAnalysis(session,may_unbound_view).analyze((P(namespace,V('dormant-normal'),(frame,)),))
    assert unbound_open.for_point(unbound_may.target).binding_states==(BindingState.UNBOUND,)
    assert unbound_open.for_point(unbound_may.target).binding_state.unknown_paths
    assert unbound_open.for_point(P(namespace,V('dormant-normal'),(frame,))).feasible is None
    class IncompleteBinding:
        def incoming(self,point):return DependencyNeighborhood(enumerated=point!=P(bound_ns,binding.id))
        def outgoing(self,point):return DependencyNeighborhood()
    partial_view=ProgramDependencyGraph(lambda _:bound_session.index(bound_ns),providers=(IncompleteBinding(),))
    partial=ProgramValueAnalysis(bound_session,partial_view).analyze((normal_bound,))
    assert not partial.exhausted and partial.worklist_stable and not partial.binding_proofs
    assert partial.for_point(P(bound_ns,binding.id)).binding_state.unknown_paths
    mixed=analysis._join_binding(known,bound_report.for_point(P(bound_ns,binding.id)).binding_state,
        unbound_fact.binding_state)
    assert {a.state for a in mixed.alternatives}=={BindingState.BOUND,BindingState.UNBOUND}
    assert not analysis._binding_definite(mixed,BindingState.BOUND)
    assert not analysis._binding_definite(mixed,BindingState.UNBOUND)
    partial_branch=P(namespace,branch.id,(frames[0],))
    class IncompletePredicate:
        def incoming(self,point):return DependencyNeighborhood(enumerated=point!=partial_branch)
        def outgoing(self,point):return DependencyNeighborhood()
    partial_control_view=ProgramDependencyGraph(lambda _:index,providers=(IncompletePredicate(),))
    partial_control=ProgramValueAnalysis(session,partial_control_view).analyze(direct_points[:2])
    assert partial_control.worklist_stable and not partial_control.exhausted
    assert {(proof.branch.context,proof.selected_index)for proof in partial_control.branch_proofs}=={((frames[1],),1)}
    jump_report=ProgramValueAnalysis(session,ProgramDependencyGraph(lambda _:index)).analyze(tuple(P(namespace,v.id)for v in new_values))
    assert jump_report.worklist_stable
    for value,expected in zip(new_values[:5],(7,99,None,7,99)):
        fact=jump_report.for_point(P(namespace,value.id))
        assert {a.value for a in fact.scalar_constant.alternatives}==({PythonLiteral.from_python(expected)}
            if expected is not None else{PythonLiteral.from_python(7),PythonLiteral.from_python(99)})
    assert any(len(proof.branch.context)==2 and proof.branch.node==jump_branch.id for proof in jump_report.branch_proofs)
    assert any(proof.route.kind is K.BLOCK_ARGUMENT and proof.route.source.node in{u.id for u in jump_sources}
        for proof in jump_report.route_refutations)
    impossible=jump_report.for_point(P(namespace,new_values[5].id))
    assert impossible.feasible is False and impossible.infeasibility
    assert impossible.scalar_constant.precision is FieldPrecision.NOT_APPLICABLE
    assert jump_report.for_point(P(namespace,new_values[6].id)).feasible is not False
    assert any(f.kind=='CONTROL_TERMINATION_OPEN'for f in jump_report.frontiers)
    # A known argument does not authorize an unverified activation/entry.
    # Its branch value is known, but entry-relative CONTROL cannot prune it.
    external_frame=DependencyFrame(namespace,candidate.id,None,None,namespace,entry=jump_region)
    external_formal=P(namespace,jump_flag.id,(external_frame,));external_actual=P(namespace,U('call-true-flag'))
    external_argument=DependencyEdge(external_actual,external_formal,K.ARGUMENT,M.VALUE,
        (DependencyEvidence('DECLARED_EXTERNAL_ARGUMENT_V1',(locator,),(external_actual,external_formal)),))
    class ExternalEntry:
        def incoming(self,point):return DependencyNeighborhood((external_argument,)if point==external_formal else())
        def outgoing(self,point):return DependencyNeighborhood((external_argument,)if point==external_actual else())
    external_view=ProgramDependencyGraph(lambda _:index,providers=(ExternalEntry(),))
    external=ProgramValueAnalysis(session,external_view).analyze((P(namespace,jump_merged.id,(external_frame,)),))
    assert {a.value for a in external.for_point(P(namespace,jump_merged.id,(external_frame,))).scalar_constant.alternatives}=={
        PythonLiteral.from_python(7),PythonLiteral.from_python(99)}
    assert any(f.kind=='CONTROL_ENTRY_SCOPE_OPEN'for f in external.frontiers)
    assert not external.route_refutations
    absent_normal=P(namespace,new_values[5].id)
    class IncompleteNormalFamily:
        def incoming(self,point):return DependencyNeighborhood(enumerated=point!=absent_normal)
        def outgoing(self,point):return DependencyNeighborhood()
    partial_normal=ProgramValueAnalysis(session,ProgramDependencyGraph(lambda _:index,
        providers=(IncompleteNormalFamily(),))).analyze((absent_normal,))
    assert partial_normal.worklist_stable and not partial_normal.exhausted
    assert partial_normal.for_point(absent_normal).feasible is not False
    assert partial_normal.for_point(absent_normal).scalar_constant.unknown_paths
    stopped_jump=ProgramValueAnalysis(session,ProgramDependencyGraph(lambda _:index),
        budget=ValueAnalysisBudget(max_steps=1)).analyze((P(namespace,new_values[0].id),))
    assert not stopped_jump.worklist_stable and not stopped_jump.route_refutations
    stopped_unbound=ProgramValueAnalysis(session,ProgramDependencyGraph(lambda _:index),
        budget=ValueAnalysisBudget(max_steps=7)).analyze((P(namespace,V('dormant-normal')),))
    assert not stopped_unbound.exhausted and not stopped_unbound.worklist_stable
    assert stopped_unbound.for_point(P(namespace,V('dormant-normal'))).feasible is None

    # An imprecise write kills the prior BOUND token independently of the
    # prior payload's known True. No target function or method executes.
    from scar.ir.program import StateAccess,AccessMode
    previous=LocalBindingValue(V('binding-previous'),bad,OperationResult(O('binding-initial'),0),ValueSlotID('missing'))
    previous_use=Use(U('binding-previous-use'),previous.id,UseRole.LOCAL_BINDING)
    update_world=Use(U('binding-update-world'),V('world-in'),UseRole.STATE_CONTENT)
    after_world=StateVersionValue(V('binding-after-world'),bad,OperationResult(unbind.id,1),world)
    initial=Operation(O('binding-initial'),'initial binding',(Behavior.COMPUTE,),(bound_use,),
        (previous.id,),effects_complete=True)
    update=Operation(unbind.id,'imprecise binding update',(Behavior.READ,Behavior.WRITE),
        (previous_use,update_world),(V('unbound'),after_world.id),
        accesses=(StateAccess(world,update_world.id,AccessMode.READ_WRITE,after_world.id),),effects_complete=False)
    unknown_read=replace(read,uses=(binding,replace(before,value=after_world.id)))
    unknown_regions=tuple(replace(region,blocks=tuple(replace(block,operations=(initial.id,update.id,read.id))
        if block.id==B('bad-entry')else block for block in region.blocks))if region.id==bad else region for region in bound_graph.regions)
    unknown_graph=replace(bound_graph,regions=unknown_regions,operations=tuple(update if op.id==unbind.id else
        unknown_read if op.id==read.id else op for op in bound_graph.operations)+(initial,),
        values=(*bound_graph.values,previous,after_world),binding_definitions=(
            BindingDefinition(previous.id,BindingState.BOUND,bound_use.id),
            BindingDefinition(V('unbound'),BindingState.UNKNOWN,previous=previous_use.id)))
    unknown_ns,unknown_session,unknown_view=binding_scope(unknown_graph,'binding-unknown')
    unknown_point=P(unknown_ns,V('dormant-normal'))
    unknown_report=ProgramValueAnalysis(unknown_session,unknown_view).analyze((unknown_point,))
    assert unknown_report.exhausted and unknown_report.for_point(unknown_point).feasible is None
    unknown_token=unknown_report.for_point(P(unknown_ns,V('unbound')))
    assert not unknown_token.binding_states and unknown_token.binding_state.unknown_paths
    assert not unknown_token.binding_payload.scalar_constant.alternatives
    assert not unknown_report.binding_proofs

    # A tiny real source chain exercises the existing TRUTH contract rather
    # than assigning a synthetic Opcode to it. The Custom body would raise
    # if anybody executed the target; only SCAR parses/compiles this source.
    from scar.analysis.program_dependency_session import ProgramDependencySession,ProgramDependencyBudget
    truth_source=tmp_path/'truth_source';truth_source.mkdir();truth_model=tmp_path/'truth_model'
    truth_text='''class Custom:
    def __bool__(self):
        raise RuntimeError("SCAR must never call this method")
def flags():
    flag = True
    if flag:
        yes = 7
    else:
        yes = 99
    flag = False
    if flag:
        no = 7
    else:
        no = 99
    if unknown_value:
        unknown = 7
    else:
        unknown = 99
    if Custom():
        custom = 7
    else:
        custom = 99
    arithmetic = 2 + 3
    return (yes, no, arithmetic)
'''
    (truth_source/'program.py').write_text(truth_text)
    built=subprocess.run([sys.executable,'-B','-m','scar.cli','static',str(truth_source),'--out',str(truth_model),
        '--jobs','1','--phase','bodies'],capture_output=True,text=True)
    assert built.returncode==0,built.stdout+built.stderr
    with ProgramDependencySession(truth_model,budget=ProgramDependencyBudget(max_seconds=60,max_graphs=16))as scoped:
        original,=scoped.select_bodies(file='program.py',entry='<module>.flags');body=scoped.load_body(original)
        ns=GraphNamespace.from_source(original);roots=[];pairs=[];branches=[]
        from scar.ir.record_codec import decode
        for protocol in body.document['structured']['protocols']:
            if protocol['kind']!='TRUTH':continue
            operation=body.index.operations[decode(O,protocol['operation'])]
            normal=next(e for e in operation.terminator.successors if e.kind is ExitKind.NORMAL)
            failure=next(e for e in operation.terminator.successors if e.kind is ExitKind.RAISE)
            normal_value=body.index._block_records[normal.block].arguments[0]
            raised_value=body.index._block_records[failure.block].arguments[0]
            owner=body.index.operations[body.index._block_records[normal.block].operations[-1]]
            assert owner.terminator.kind is TerminatorKind.BRANCH
            roots.extend((P(ns,owner.id),P(ns,normal_value),P(ns,raised_value)))
            pairs.append((protocol['source']['start_line'],P(ns,normal_value),P(ns,raised_value),P(ns,operation.id)))
            branches.append((protocol['source']['start_line'],P(ns,owner.id)))
        assert {line for line,*rest in pairs}=={6,11,15,19}
        add_link,=[l for l in body.metadata.operation_links if l.opcode is not None and l.opcode.name=='ADD']
        add=body.index.operations[add_link.operation]
        add_normal=next(e for e in add.terminator.successors if e.kind is ExitKind.NORMAL)
        add_raise=next(e for e in add.terminator.successors if e.kind is ExitKind.RAISE)
        add_normal_point=P(ns,body.index._block_records[add_normal.block].arguments[0])
        add_raise_point=P(ns,body.index._block_records[add_raise.block].arguments[0])
        roots.extend((add_normal_point,add_raise_point))
        returned,=[operation for operation in body.graph.operations if operation.terminator is not None
            and operation.terminator.kind is TerminatorKind.RETURN]
        returned_point=P(ns,returned.terminator.values[0]);roots.append(returned_point)
        source_analysis=ProgramValueAnalysis(scoped)
        truth_report=source_analysis.analyze(roots)
        by_branch=dict(branches)
        # Custom dispatch has no published call scope. Its open paths remain
        # local to its fields: a stable queue can still prove the independent
        # original predicates in this very same demand scope.
        assert not truth_report.exhausted and truth_report.worklist_stable
        positive=truth_report
        assert {(p.branch,p.selected_index)for p in positive.branch_proofs}=={
            (by_branch[6],0),(by_branch[11],1)}
        assert len(positive.binding_proofs)==5
        truth_export=export_value_analysis(positive);json.dumps(truth_export,allow_nan=False)
        assert truth_export['fixed_point_reached'] and not truth_export['query_scope_complete']
        assert len(truth_export['binding_proofs'])==5
        for public in truth_export['binding_proofs']:
            read_ref=public['read']['point'];binding_ref=public['binding']['point']
            read_row=truth_export['points'][read_ref];binding_row=truth_export['points'][binding_ref]
            assert read_row['namespace']==binding_row['namespace']and read_row['context']==binding_row['context']
            anchors=truth_export['evidence'][public['evidence']['evidence']]['anchors']
            assert read_ref in anchors and binding_ref in anchors
            guard=public['condition']['condition']
            assert truth_export['conditions'][guard]['name']=='READ_NORMAL_REQUIRES_BOUND'
            assert truth_export['conditions'][guard]['subject']==read_ref
            assert any(guard in edge['conditions']and edge['source']==binding_ref
                and edge['kind']=='BINDING_READ'for edge in truth_export['edges'])
        for proof in positive.binding_proofs:
            assert proof.binding.context==proof.read.context==()
            assert proof.condition in next(e.conditions for e in positive.edges if e.kind is K.BINDING_READ
                and e.source==proof.binding)
            assert proof.read in proof.evidence.anchors and proof.binding in proof.evidence.anchors
            field=positive.for_point(proof.binding).binding_state
            assert field.precision in(FieldPrecision.EXACT,FieldPrecision.CONDITIONAL)
            assert not field.unknown_paths and {a.state for a in field.alternatives}=={BindingState.BOUND}
        assert all(any(e.rule=='READ_BINDING_DEFINITELY_BOUND_V1'for a in proof.alternatives for e in a.evidence)
            for proof in positive.branch_proofs)
        assert any(fact['binding_state']['precision']=='EXACT'and fact['binding_states']==['BOUND']
            for fact in truth_export['facts'])
        actual_return=truth_report.for_point(returned_point)
        assert {a.value for a in actual_return.immutable_tuple.alternatives}=={
            PythonLiteral.from_python((7,99,5),exact=True)}
        assert all(c.name!='SUCCESSOR_SELECTED'or c.index==0 for a in actual_return.immutable_tuple.alternatives
            for c in a.conditions if c.domain=='canonical'and source_analysis._condition_evidence(c)is not None
            and c.subject not in(by_branch[6],by_branch[11]))
        assert truth_report.route_refutations
        assert any(row['rule']=='NECESSARY_ENTRY_CHOICE_REFUTED_V1'for row in truth_export['evidence'])
        assert len(truth_export['route_refutations'])==len(truth_report.route_refutations)
        for public in truth_export['route_refutations']:
            route=truth_export['edges'][public['route']['edge']]
            assert route['strength']=='EXACT'and public['source_evidence']
            witness=truth_export['evidence'][public['evidence']['evidence']]
            assert route['source']in witness['anchors']and route['target']in witness['anchors']
        assert any(row['kind']=='CONTROL'for row in truth_export['edges'])
        for line,normal,failure,operation in pairs:
            normal_fact=truth_report.for_point(normal);failure_fact=truth_report.for_point(failure)
            if line in(6,11):
                assert {a.value for a in normal_fact.scalar_constant.alternatives}=={PythonLiteral.from_python(line==6)}
            else:assert not normal_fact.scalar_constant.alternatives and normal_fact.scalar_constant.unknown_paths
            assert not failure_fact.scalar_constant.alternatives and failure_fact.scalar_constant.unknown_paths
            assert any(e.source==operation and e.target==failure and e.kind is K.RESULT for e in truth_report.edges)
        assert {a.value for a in truth_report.for_point(add_normal_point).scalar_constant.alternatives}=={PythonLiteral.from_python(5)}
        assert not truth_report.for_point(add_raise_point).scalar_constant.alternatives
        assert truth_report.for_point(add_raise_point).scalar_constant.unknown_paths
        add_edge=next(e for e in truth_report.edges if e.kind is K.RESULT and e.source.node==add.id and e.target==add_normal_point)
        raise_edge=next(e for e in truth_report.edges if e.kind is K.RESULT and e.source.node==add.id and e.target==add_raise_point)
        assert source_analysis._normal_result_zero(add_normal_point,add_edge)
        assert not source_analysis._normal_result_zero(add_raise_point,raise_edge)
        assert not any(c.name=='COMPLETION_SLOT'for c in add_edge.conditions)
        assert any('/terminator/successors/'in locator.pointer and'/arguments/'in locator.pointer
            for evidence in add_edge.evidence for locator in evidence.sources)
        legacy_zero=replace(add_edge,conditions=(*add_edge.conditions,
            DependencyCondition('canonical','COMPLETION_SLOT',add_edge.source,0)))
        assert source_analysis._normal_result_zero(add_normal_point,legacy_zero)
        legacy_wrong=replace(add_edge,conditions=(*add_edge.conditions,
            DependencyCondition('canonical','COMPLETION_SLOT',add_edge.source,1)))
        assert not source_analysis._normal_result_zero(add_normal_point,legacy_wrong)
        assert all(any(e.rule=='BRANCH_ENTRY_REQUIRES_ORIGINAL_TRUTH_NORMAL_V1'for a in p.alternatives for e in a.evidence)
            and any(c.name=='SUCCESSOR_SELECTED'and c.subject not in(by_branch[6],by_branch[11])
                for a in p.alternatives for c in a.conditions)for p in positive.branch_proofs)
        assert all(source_analysis._necessary_normal_entry(
            DependencyCondition('canonical','SUCCESSOR_SELECTED',operation,source_analysis._truth_contract(operation)[2]),
            by_branch[line],P(ns,body.index.operations[by_branch[line].node].terminator.condition))is not None
            for line,normal,failure,operation in pairs)
        # No host protocol dispatch is needed even for nonfinite/negative-zero
        # bit patterns; all inputs here are test-owned immutable literals.
        for value,expected in((False,False),(True,True),(0,False),(-2,True),(-0.0,False),
                (float('nan'),True),(float('inf'),True),('',False),('x',True),(b'',False),(b'x',True),
                ((),False),((0,),True),(None,False),(complex(-0.0,-0.0),False),
                (complex(0.0,float('nan')),True),(Ellipsis,True)):
            assert source_analysis._literal_truth(PythonLiteral.from_python(value,exact=True))is expected
