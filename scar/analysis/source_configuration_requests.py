"""Infer conditional configuration requests from source calls and entry inputs."""
import argparse
import ast
from collections import defaultdict,deque
from hashlib import sha256
import json
import os
from pathlib import Path

from scar.analysis.source_context_query import ContextTargetGraph
from scar.analysis.source_symbol_variants import _table
from scar.analysis.source_launch import read_script_entry
from scar.analysis.source_bytes import read_source_bytes
from scar.analysis.static_query import _Fragments
from scar.analysis.normal_output import write_table
from scar.analysis.source_stage import _durable_bytes,_durable_mkdir
from scar.analysis.source_template_links import _json
from scar.ir.program import configuration_requests as R,normal_targets as T,normal_graph as G
from scar.ir.program import source_productions as P
from scar.ir.program.source_frame_bindings import StaticInputPort
from scar.ir.program.source_compiled_values import CompiledSourceCandidate
from scar.ir.program.providers import ProviderArtifact,ProviderFactReference
from scar.ir.literals import PythonLiteral
from scar.ir.record_codec import decode,encode


_MAIN_AST='c74b68f02a2029a047dd57ac694222498276410aad4007735186229d27358545'
_ARGS_AST='812bfc3c6ebe8d6657bbaacf955486f8af8baf3f16989cb2230ac49d4965d3f8'
_FLAGS={'--config-name':'config_name','-cn':'config_name','--config-path':'config_path','-cp':'config_path'}


def _gp(unit,index):
    raw=unit.ports[index]
    return T.GlobalPort(unit.unit,decode(G.Port,raw) if type(raw) is dict else raw)


def _source(store,identity):
    row=store.model_units[identity];root=store.model_for(identity)
    raw=read_source_bytes(_Fragments(root).read(row['artifacts']['source_bytes']))
    return raw,ProviderArtifact(row['path'],sha256(raw).hexdigest(),len(raw),'scar.library-protocol-source')


def _function_ast(raw,name):
    functions=[node for node in ast.parse(raw,type_comments=True).body
        if isinstance(node,ast.FunctionDef) and node.name==name]
    if len(functions)!=1:raise ValueError('one versioned library function required')
    return sha256(ast.dump(functions[0],include_attributes=False).encode()).hexdigest()


class _Aliases:
    """Only original directed reference wires; no namespace or heap guesses."""
    def __init__(self,unit):
        self.unit=unit;self.adj=defaultdict(list);self.cache={}
        for index,(source,target) in enumerate(unit.aliases):self.adj[source].append((target,index))

    def paths(self,source):
        if source in self.cache:return self.cache[source]
        paths={source:()};queue=deque((source,))
        while queue:
            point=queue.popleft()
            for target,index in self.adj.get(point,()):
                if target not in paths:paths[target]=(*paths[point],index);queue.append(target)
        self.cache[source]=paths
        return paths

    def literals(self,target):
        return tuple(R.ConfigurationLiteralCandidate(_gp(self.unit,c.value),c.literal,
            'ORIGINAL_REFERENCE_ALIAS_PATH',self.paths(c.value)[target])
            for c in self.unit.constants if target in self.paths(c.value))


def _initial_options(contract,contract_sha):
    result=[];argv=contract.inputs.argv;index=1
    while index<len(argv):
        token=argv[index];flag,separator,value=token.partition('=')
        if token=='--':break
        if flag not in _FLAGS:index+=1;continue
        if separator:position=index;derivation='INITIAL_ARGV_OPTION_EQUALS_SUFFIX'
        elif index+1<len(argv):
            index+=1;position=index;value=argv[index];derivation='INITIAL_ARGV_FOLLOWING_OPTION_VALUE'
        else:break
        source=StaticInputPort(contract.root,contract_sha,('inputs','argv',position))
        result.append(R.ConfigurationOption(_FLAGS[flag],R.ConfigurationLiteralCandidate(source,
            PythonLiteral.from_python(value,exact=True),derivation),position))
        index+=1
    return tuple(result)


def build_configuration_requests(targets,out):
    out=Path(out).absolute()
    if out.exists():raise ValueError('fresh configuration request output required')
    producer=sha256(Path(__file__).read_bytes()).hexdigest()
    types_sha=sha256(Path(R.__file__).read_bytes()).hexdigest()
    targets_raw=(Path(targets)/'result.json').read_bytes()
    graph=ContextTargetGraph(targets);store=graph.fact_store
    if json.loads(targets_raw)!=graph.report:raise ValueError('configuration target snapshot changed')
    contract=read_script_entry(graph.report['script_entry']['path'],store.base)
    entry_raw=(Path(graph.report['script_entry']['path'])/'entry.json').read_bytes()
    apis={};profiles=[]
    for identity,row in store.rows.items():
        if row['module'] not in ('hydra.main','hydra._internal.utils'):continue
        raw,artifact=_source(store,identity)
        name='main' if row['module']=='hydra.main' else 'get_args_parser'
        digest=_function_ast(raw,name);expected=_MAIN_AST if name=='main' else _ARGS_AST
        if digest!=expected:raise ValueError('library configuration protocol version is not modeled')
        profiles.append(dict(name=name,source=encode(artifact),function_ast_sha256=digest))
        if name!='main':continue
        unit=store.load(identity)
        functions=[f for f in unit.functions if f.parameter_names==('config_path','config_name','version_base')]
        if len(functions)!=1:raise ValueError('versioned library function interface differs')
        fn=functions[0];apis[_json(encode(_gp(unit,fn.value)))]=(unit,fn,artifact)
    argv_profile=any(profile['name']=='get_args_parser' for profile in profiles)
    options=_initial_options(contract,sha256(entry_raw).hexdigest()) if argv_profile else ()
    filenames={}
    exec_graph=graph.namespace_graph.exec_graph
    compiled_root,compiled_report=exec_graph.parents['compiled_sources']
    compiled={wire['id']:decode(CompiledSourceCandidate,wire) for wire in
        _table(compiled_root,compiled_report['tables']['candidates'])}
    for connection in exec_graph.connections():
        filename=compiled[connection.compiled_candidate].context.filename
        old=filenames.setdefault(connection.root.owner.unit,filename)
        if old!=filename:raise ValueError('compiled namespace has incompatible filename candidates')
    calls_artifact=ProviderArtifact(str(graph.path/graph.report['calls']['path']),
        graph.report['calls']['sha256'],graph.report['calls']['bytes'],'scar.context-source-call-links')
    requests=[]
    # Reuse the receipt-checked streaming document view. Retain the global
    # ordinal without materializing every decoded call dictionary at once.
    for ordinal,wire in enumerate(graph._documents('calls',None,None,'result')):
        if wire['source_callable'] is None or _json(wire['source_callable']) not in apis:continue
        api,fn,artifact=apis[_json(wire['source_callable'])]
        link=decode(T.CallLink,wire,record_tags=P.PRODUCTION_RECORD_TAGS)
        caller=store.load(link.result.unit);aliases=_Aliases(caller)
        site=next(c for c in caller.calls if _gp(caller,c.result)==link.result)
        params=[]
        for index,name in enumerate(fn.parameter_names,1):
            formal=_gp(api,fn.formals[index]);route=next((r for r in link.parameters if r.formal==formal),None)
            candidates=[]
            if route is not None:
                for actual in route.actuals:
                    if type(actual) is not T.GlobalPort or actual.unit!=caller.unit:continue
                    local=next(i for i,p in enumerate(caller.ports) if _gp(caller,i)==actual)
                    candidates.extend(aliases.literals(local))
            params.append(R.ConfigurationParameter(name,formal,() if route is None else route.actuals,
                tuple(candidates),None if candidates else 'NO_REFERENCE_LITERAL_SOURCE_PROVEN'))
        associations=[]
        factory_paths=aliases.paths(site.result)
        for decoration in caller.calls:
            if decoration.callee not in factory_paths or len(decoration.positional)!=1 or decoration.keywords:
                continue
            for task in caller.functions:
                paths=aliases.paths(task.value)
                if decoration.positional[0] in paths:
                    associations.append(R.ConfigurationTaskAssociation(_gp(caller,task.value),_gp(caller,decoration.result),
                        factory_paths[decoration.callee],paths[decoration.positional[0]]))
        chosen={option.option:option.candidate for option in options}
        values={p.name:tuple(c.literal.to_python() for c in p.candidates) for p in params}
        for name,candidate in chosen.items():values[name]=(candidate.literal.to_python(),)
        filename=filenames.get(caller.unit,store.rows[caller.unit]['path'])
        relative_filename=not os.path.isabs(filename)
        filename=os.path.abspath(os.path.join(contract.inputs.cwd,filename))
        conditions=('SOURCE_API_CALL_AND_DEFAULT_LIBRARY_BINDINGS_SELECTED',
            'SELECTED_TASK_USES_ASSOCIATED_CODE_FILENAME',
            'HYDRA_CALLING_MODULE_ENVIRONMENT_OVERRIDES_ABSENT_AT_LOOKUP',
            'INITIAL_ARGV_OPTION_PROJECTION_STILL_VALID_AT_PARSE',
            'FILE_PROVIDER_AND_SEARCH_PATH_CANDIDATE_SELECTED')
        if relative_filename:conditions+=('WORKING_DIRECTORY_AT_SEARCH_MATCHES_DECLARED_ENTRY',)
        sources=[]
        if associations:
            for path in values.get('config_path',()):
                for name in values.get('config_name',()):
                    if name is not None and type(name) is not str:continue
                    if path is None:protocol='CONFIG_STORE';root=None;resource=None
                    elif type(path) is not str:continue
                    elif path.startswith('pkg://'):protocol='PACKAGE';root=path;resource=None
                    else:
                        protocol='FILE';root=os.path.abspath(os.path.join(os.path.dirname(filename),path))
                        resource=None if name is None else os.path.join(root,name if name.endswith('.yaml') else name+'.yaml')
                    sources.append(R.ConfigurationSourceCandidate(protocol,root,name,resource,filename,conditions))
        obligations=('CURRENT_ARGV_MUTATION_ANALYSIS_PENDING','SEARCH_PATH_PLUGINS_CONFIG_STORE_AND_EXTRA_DIRS_PENDING',
            'DEFAULTS_COMPOSITION_AND_CFG_BINDING_NOT_PERFORMED')
        if not argv_profile:obligations+=('ARGV_OPTION_PROTOCOL_SOURCE_NOT_ADMITTED',)
        if not associations:obligations+=('TASK_DEFINITION_FACTORY_ASSOCIATION_NOT_PROVEN',)
        reference=ProviderFactReference(calls_artifact,'#/records/'+str(ordinal))
        identity=sha256(_json(dict(call=encode(link.result),reference=encode(reference)))).hexdigest()
        requests.append(R.ConfigurationRequest(identity,'HYDRA_MAIN_V1',link.source_callable,artifact,_MAIN_AST,
            link.result,reference,tuple(params),tuple(associations),options,tuple(sources),conditions,obligations))
    store.validate_parents()
    if ((graph.path/'result.json').read_bytes()!=targets_raw
            or (Path(graph.report['script_entry']['path'])/'entry.json').read_bytes()!=entry_raw
            or sha256(Path(__file__).read_bytes()).hexdigest()!=producer
            or sha256(Path(R.__file__).read_bytes()).hexdigest()!=types_sha):
        raise ValueError('configuration request inputs or rules changed')
    _durable_mkdir(out);table=write_table(out/'requests.jsonl.gz',requests)
    report=dict(schema='scar.configuration-requests',schema_version=1,status='CONDITIONAL_LIBRARY_REQUESTS_EXTRACTED',
        targets=str(graph.path),targets_sha256=sha256(targets_raw).hexdigest(),
        script_entry=graph.report['script_entry'],entry_sha256=sha256(entry_raw).hexdigest(),
        source_catalog_sha256=sha256(store.raw).hexdigest(),protocol_profiles=profiles,requests=table,
        request_count=len(requests),source_candidates=sum(len(r.sources) for r in requests),
        request_scope='ADMITTED_VERSIONED_LIBRARY_APIS_ONLY',argv_protocol_admitted=argv_profile,
        implementation_sha256=producer,types_sha256=types_sha,
        target_executed=False,configuration_composed=False,current_argv_proven=False,first_stage_complete=False)
    _durable_bytes(out/'result.json',_json(report),replace=False)
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--targets',required=True);parser.add_argument('--out',required=True)
    args=parser.parse_args();report=build_configuration_requests(args.targets,args.out)
    print(json.dumps({name:report[name] for name in ('status','request_count','source_candidates')}),flush=True)


if __name__=='__main__':main()
