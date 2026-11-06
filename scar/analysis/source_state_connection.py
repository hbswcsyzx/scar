"""Connect declared state boundaries to original context call interfaces.

    Admission is static may-analysis evidence. The selected input state, runtime
    dispatch, and content preservation after the boundary remain separate claims.
"""
import argparse
from hashlib import sha256
import json
from pathlib import Path

from scar.analysis.source_configuration_state_binding import read_configuration_state_bindings
from scar.analysis.source_context_query import ContextTargetGraph
from scar.analysis.source_configuration_requests import _gp
from scar.analysis.source_relation_selection import select_relation_rows
from scar.analysis.normal_output import write_table
from scar.analysis.source_stage import _durable_mkdir,_durable_bytes
from scar.analysis.source_template_links import _json
from scar.analysis.source_symbol_variants import _table
from scar.ir.program import source_state_connections as S,normal_targets as T,source_productions as P
from scar.ir.program.normal_entry import ScopeActivationEvidence
from scar.ir.program.providers import ProviderArtifact,ProviderFactReference
from scar.ir.record_codec import encode,decode


def _artifact(path,schema):
    path=Path(path).absolute();raw=path.read_bytes()
    return ProviderArtifact(str(path),sha256(raw).hexdigest(),len(raw),schema)


def _table_artifact(graph,name):
    receipt=graph.report[name]
    return ProviderArtifact(str(graph.path/receipt['path']),receipt['sha256'],receipt['bytes'],'scar.context.'+name)


def _pins():
    from scar.analysis import source_configuration_state_binding,source_relation_selection
    return {name:sha256(Path(path).read_bytes()).hexdigest() for name,path in
        dict(producer=__file__,types=S.__file__,boundaries=source_configuration_state_binding.__file__,
            selector=source_relation_selection.__file__).items()}


def _derive(boundaries,targets):
    boundary_report,bindings=read_configuration_state_bindings(boundaries)
    target_report=json.loads((Path(targets)/'result.json').read_bytes())
    if target_report.get('analysis_transport_profile')=='ADMITTED_LEXICAL_REFERENCE_COPY_CLOSURE':
        from scar.analysis.source_lexical_context import LexicalContextGraph
        graph=LexicalContextGraph(targets)
    else:
        graph=ContextTargetGraph(targets)
    store=graph.fact_store
    boundary_artifact=_artifact(Path(boundaries)/boundary_report['bindings']['path'],'scar.source-state-projections')
    wanted={_json(encode(b.data_result)) for b in bindings}
    sites=select_relation_rows(graph.path,graph.report['calls'],lambda w:_json(w['result']) in wanted)
    scopes={};required_aliases=set();functions={};obligations=[]
    for ordinal,binding in enumerate(bindings):
        if binding.receiver.unit not in store.rows:
            obligations.append(S.SourceStateConnectionObligation(ordinal,'BOUNDARY_UNIT_NOT_IN_CONTEXT','Source provider has not entered this context catalog.'))
            continue
        unit=store.load(binding.receiver.unit)
        function=next(f for f in unit.functions if _gp(unit,f.value)==binding.source_function)
        functions[ordinal]=(unit,function)
        scopes[binding.caller.owner]=None;scopes[function.body_scope.owner]=None
        required_aliases.update((unit.unit,i) for i in (*binding.callee_alias_rows,*binding.none_alias_rows))
    activations=select_relation_rows(graph.path,graph.report['entry_activations'],
        lambda w:any(w['target']==encode(scope) for scope in scopes))
    activation_artifact=_table_artifact(graph,'entry_activations')
    for ordinal,wire in activations:
        evidence=decode(ScopeActivationEvidence,wire,record_tags=P.PRODUCTION_RECORD_TAGS)
        if scopes[evidence.target] is None:scopes[evidence.target]=ProviderFactReference(activation_artifact,'#/records/'+str(ordinal))
    alias_rows=select_relation_rows(graph.path,graph.report['reference_alias_facts'],
        lambda w:(w['unit'],w['alias']) in required_aliases)
    alias_artifact=_table_artifact(graph,'reference_alias_facts')
    aliases={(wire['unit'],wire['alias']):ProviderFactReference(alias_artifact,'#/records/'+str(ordinal))
        for ordinal,wire in alias_rows}
    call_artifact=_table_artifact(graph,'calls');connections=[]
    for index,binding in enumerate(bindings):
        if index not in functions:continue
        unit,function=functions[index];matches=[]
        for ordinal,wire in sites:
            if wire['result']!=encode(binding.data_result) or wire['source_callable']!=encode(binding.source_function):continue
            link=decode(T.CallLink,wire,record_tags=P.PRODUCTION_RECORD_TAGS)
            if link.callee!=binding.callee or link.body!=T.Body(unit.unit,function.template,function.body):
                raise ValueError('connected call no longer matches its declared source site/body')
            content_routes=[r for r in link.parameters if r.kind is T.RouteKind.ARGUMENT and binding.receiver in r.actuals]
            state_routes=[r for r in link.parameters if r.kind is T.RouteKind.STATE and binding.world_before in r.actuals]
            content=content_routes[0] if len(content_routes)==1 else None
            state=state_routes[0] if len(state_routes)==1 else None
            data_return=(binding.normal_return,binding.data_result)
            state_return=(_gp(unit,function.return_world),binding.world_after)
            if (content is None or content.kind is not T.RouteKind.ARGUMENT or content.actuals!=(binding.receiver,)
                    or state is None or state.kind is not T.RouteKind.STATE or state.actuals!=(binding.world_before,)
                    or data_return not in link.returns or state_return not in link.returns):
                raise ValueError('source state join crossed an argument, data return or world route')
            matches.append((ordinal,link,content,state,data_return,state_return))
        if not matches:
            obligations.append(S.SourceStateConnectionObligation(index,'BOUNDARY_TARGET_NOT_CONNECTED_AT_FRONTIER',
                'No matching SourceCallLink in this admitted event prefix; the declaration remains available.'))
        caller=scopes[binding.caller.owner];body=scopes[function.body_scope.owner]
        if caller is None:obligations.append(S.SourceStateConnectionObligation(index,'CALLER_SCOPE_NOT_ADMITTED_AT_FRONTIER',''))
        if body is None:obligations.append(S.SourceStateConnectionObligation(index,'API_BODY_SCOPE_NOT_ADMITTED_AT_FRONTIER',''))
        refs=[]
        for row in (*binding.callee_alias_rows,*binding.none_alias_rows):
            ref=aliases.get((unit.unit,row))
            if ref is None:
                obligations.append(S.SourceStateConnectionObligation(index,'REFERENCE_ALIAS_NOT_ADMITTED_AT_FRONTIER',str(row)))
            else:refs.append(ref)
        for ordinal,link,content,state,data_return,state_return in matches:
            conditions=tuple(dict.fromkeys((*binding.conditions,*link.conditions,
                'INPUT_CONTENT_AT_CALL_AND_LATER_STATE_VERSIONS_REMAIN_UNPROVEN')))
            connections.append(S.SourceStateConnection(ProviderFactReference(boundary_artifact,'#/records/'+str(index)),
                ProviderFactReference(call_artifact,'#/records/'+str(ordinal)),link,content,state,data_return,state_return,
                caller,body,tuple(refs),conditions))
        obligations.append(S.SourceStateConnectionObligation(index,'INPUT_VERSIONS_AT_CALL_NOT_PROVEN',
            'Static interface matching does not prove argv/config input versions at this world.'))
    store.validate_parents()
    return graph,tuple(connections),tuple(obligations),len(bindings)


def build_source_state_connections(boundaries,targets,out):
    initial=_pins();out=Path(out).absolute();boundaries=Path(boundaries).absolute();targets=Path(targets).absolute()
    if out.exists():raise ValueError('fresh source state connection output required')
    before={name:_artifact(path/'result.json','scar.'+name) for name,path in (('boundaries',boundaries),('targets',targets))}
    graph,connections,obligations,count=_derive(boundaries,targets)
    _durable_mkdir(out)
    tables=dict(connections=write_table(out/'connections.jsonl.gz',connections),
        obligations=write_table(out/'obligations.jsonl.gz',obligations))
    report=dict(schema='scar.source-state-connections',schema_version=1,status='CONDITIONAL_SOURCE_STATE_INTERFACE_JOIN',
        boundaries=str(boundaries),targets=str(targets),parents={k:encode(v) for k,v in before.items()},pins=initial,
        tables=tables,boundary_count=count,connection_count=len(connections),obligation_count=len(obligations),
        target_fixed_point=graph.report['status']=='CONTEXT_TARGET_FIXED_POINT',
        target_executed=False,runtime_dispatch_proven=False,input_versions_at_call_proven=False,
        current_task_fields_proven=False,first_stage_complete=False)
    for name,path in (('boundaries',boundaries),('targets',targets)):
        if _artifact(path/'result.json','scar.'+name)!=before[name]:raise ValueError('state join parent changed')
    if _pins()!=initial:raise ValueError('state join producer changed')
    _durable_bytes(out/'result.json',_json(report),replace=False)
    return report


def read_source_state_connections(path):
    path=Path(path).absolute();raw=(path/'result.json').read_bytes();report=json.loads(raw)
    if ((report['schema'],report['schema_version'],report['status'])!=
            ('scar.source-state-connections',1,'CONDITIONAL_SOURCE_STATE_INTERFACE_JOIN') or report['pins']!=_pins()):
        raise ValueError('source state connection producer differs')
    for name in ('boundaries','targets'):
        if encode(_artifact(Path(report[name])/'result.json','scar.'+name))!=report['parents'][name]:
            raise ValueError('source state connection parent differs')
    connections=tuple(decode(S.SourceStateConnection,w,record_tags=P.PRODUCTION_RECORD_TAGS)
        for w in _table(path,report['tables']['connections']))
    obligations=tuple(decode(S.SourceStateConnectionObligation,w) for w in _table(path,report['tables']['obligations']))
    graph,expected,pending,count=_derive(report['boundaries'],report['targets'])
    if (connections!=expected or obligations!=pending or count!=report['boundary_count']
            or len(connections)!=report['connection_count'] or len(obligations)!=report['obligation_count']
            or report['target_fixed_point']!=(graph.report['status']=='CONTEXT_TARGET_FIXED_POINT')):
        raise ValueError('source state connection evidence or denominators differ')
    if any(report[k] for k in ('target_executed','runtime_dispatch_proven','input_versions_at_call_proven',
            'current_task_fields_proven','first_stage_complete')) or (path/'result.json').read_bytes()!=raw:
        raise ValueError('source state join cannot grant runtime-content authority')
    return report,connections,obligations


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--boundaries',required=True);parser.add_argument('--targets',required=True);parser.add_argument('--out',required=True)
    args=parser.parse_args();r=build_source_state_connections(args.boundaries,args.targets,args.out)
    print(json.dumps({k:r[k] for k in ('status','boundary_count','connection_count','obligation_count')}),flush=True)


if __name__=='__main__':main()
