"""Locate a versioned input provider's source state boundary, without execution.

This library adapter binds a content candidate to the cfg argument after a
mutating call. The Python return and the caller's entire world stay distinct.
It does not install field facts into a solver or declare task contents proven.
"""
import argparse
import ast
from hashlib import sha256
import json
from pathlib import Path

from scar.analysis.normal_facts import SourceFactStore
from scar.analysis import normal_facts
from scar.analysis.source_configuration_value_store import read_configuration_values
from scar.analysis.source_configuration_overrides import read_configuration_overrides
from scar.analysis.source_configuration_requests import _Aliases,_gp,_source
from scar.analysis.source_symbol_variants import _table
from scar.analysis.normal_output import write_table
from scar.analysis.source_stage import _durable_mkdir,_durable_bytes
from scar.analysis.source_template_links import _json
from scar.ir.program import source_state_projections as S,source_productions as P,normal_links as F
from scar.ir.program.providers import ProviderArtifact,ProviderFactReference
from scar.ir.record_codec import decode


_API='ConfigLoaderImpl._apply_overrides_to_config'
_API_AST='61e9fef249442f59fb8271fa4fdc2a8994b6dab101918677bdf3233dbcf060f7'
_CFG_POSITION=1


def _artifact(path,schema):
    path=Path(path).absolute();raw=path.read_bytes()
    return ProviderArtifact(str(path),sha256(raw).hexdigest(),len(raw),schema)


def _pins():
    from scar.analysis import source_configuration_value_store,source_configuration_requests
    return {key:sha256(Path(path).read_bytes()).hexdigest() for key,path in
        dict(producer=__file__,types=S.__file__,facts=normal_facts.__file__,
            values=source_configuration_value_store.__file__,aliases=source_configuration_requests.__file__).items()}


def _scoped_aliases(unit,owner):
    """Keep original row coordinates, admitting only this code scope's wires."""
    allowed={index for group in unit.scope_groups if group.owner==owner for span in group.tables
        if span.table is F.FactTable.ALIASES for index in range(span.start,span.stop)}
    aliases=_Aliases(unit)
    aliases.adj={point:[(target,index) for target,index in rows if index in allowed]
        for point,rows in aliases.adj.items()}
    return aliases


def _anchors(values_path,facts_path):
    _,values=read_configuration_values(values_path)
    _,overlay=read_configuration_overrides(Path(values.overrides.uri).parent)
    profiles=[p for p in overlay.protocol_sources if p.qualified_function==_API and p.function_ast_sha256==_API_AST]
    if len(profiles)!=1:raise ValueError('one versioned content-update library protocol required')
    profile=profiles[0];store=SourceFactStore(facts_path);candidates=[]
    for identity in store.units_for_source(profile.source.uri):
        raw,source=_source(store,identity)
        if (source.sha256,source.size_bytes)!=(profile.source.sha256,profile.source.size_bytes):
            raise ValueError('source frontend and content protocol versions differ')
        tree=ast.parse(raw);owner=tree
        for name in profile.qualified_function.split('.'):
            owner=next(n for n in owner.body if isinstance(n,(ast.ClassDef,ast.FunctionDef)) and n.name==name)
        if sha256(ast.dump(owner,include_attributes=False).encode()).hexdigest()!=_API_AST:
            raise ValueError('source boundary protocol AST differs')
        if any(isinstance(n,(ast.Return,ast.Yield,ast.YieldFrom)) for n in ast.walk(owner)):
            raise ValueError('this API boundary requires its normal implicit None return')
        signature=tuple(arg.arg for arg in owner.args.posonlyargs+owner.args.args)
        unit=store.load(identity);functions=[f for f in unit.functions if f.parameter_names==signature]
        if len(functions)!=1:raise ValueError('source protocol definition interface is ambiguous')
        function=functions[0];aliases=_Aliases(unit);body_aliases=_scoped_aliases(unit,function.body_scope.owner)
        none=[(c,body_aliases.paths(c.value)[function.returns]) for c in unit.constants
            if c.literal.to_python() is None and function.returns in body_aliases.paths(c.value)]
        if len(none)!=1:raise ValueError('implicit normal None requires its original reference path')
        descriptor=store.rows[identity];fact=ProviderArtifact(str(store.path/descriptor['facts']),
            descriptor['sha256'],descriptor['bytes'],'scar.normal-source-unit-facts')
        for attr_index,attribute in enumerate(unit.attributes):
            if attribute.action is not F.AttributeAction.GET or attribute.name!=owner.name:continue
            paths=aliases.paths(attribute.value)
            for call_index,call in enumerate(unit.calls):
                if call.callee not in paths:continue
                if call.keywords or call.positional_pack is not None or call.keyword_pack is not None or len(call.positional)!=len(signature):
                    raise ValueError('library source boundary has an unmodeled argument layout')
                owners=[group.owner for group in unit.scope_groups for span in group.tables
                    if span.table is F.FactTable.CALLS and span.start<=call_index<span.stop]
                if len(owners)!=1:raise ValueError('source boundary has no unique original scope')
                callers=[fn.body_scope for fn in unit.functions if fn.body_scope is not None and fn.body_scope.owner==owners[0]]
                if len(callers)!=1:raise ValueError('source boundary caller interface is ambiguous')
                scoped_paths=_scoped_aliases(unit,owners[0]).paths(attribute.value)
                if call.callee not in scoped_paths:continue
                conditions=tuple(dict.fromkeys((*values.conditions,
                    'SOURCE_LIBRARY_API_DESCRIPTOR_AND_SIGNATURE_SELECTED',
                    'DECLARED_INPUT_VERSIONS_REACH_THIS_CFG_AND_OVERRIDE_ARGUMENTS',
                    'SOURCE_SCOPE_ACTIVATED_AND_CALL_RETURNED_NORMALLY',
                    'CONTENT_INTERPRETATION_AT_POST_CALL_WORLD_ONLY')))
                candidates.append(S.SourceStateProjection(
                    _artifact(Path(values_path)/'result.json','scar.configuration-values'),values.selected_root,
                    _artifact(store.path/'result.json','scar.normal-source-link-facts'),profile,_gp(unit,function.value),callers[0],
                    ProviderFactReference(fact,'#/calls/'+str(call_index)),
                    ProviderFactReference(fact,'#/attributes/'+str(attr_index)),
                    _gp(unit,attribute.value),_gp(unit,call.callee),scoped_paths[call.callee],
                    _gp(unit,call.positional[_CFG_POSITION]),_gp(unit,call.world),_gp(unit,call.result_world),
                    _gp(unit,call.result),_gp(unit,function.returns),_gp(unit,none[0][0].value),none[0][1],conditions))
    return tuple(candidates)


def build_configuration_state_bindings(values,facts,out):
    initial=_pins();out=Path(out).absolute()
    if out.exists():raise ValueError('fresh source state binding output required')
    values=Path(values).absolute();facts=Path(facts).absolute()
    bindings=_anchors(values,facts)
    if not bindings:raise ValueError('content-update source unit has not entered the frontend')
    _durable_mkdir(out);table=write_table(out/'bindings.jsonl.gz',bindings)
    report=dict(schema='scar.configuration-state-bindings',schema_version=1,
        status='DECLARED_CALL_STATE_PROJECTION_CANDIDATES',values=str(values),facts=str(facts),
        values_sha256=sha256((values/'result.json').read_bytes()).hexdigest(),
        facts_sha256=sha256((facts/'result.json').read_bytes()).hexdigest(),
        bindings=table,binding_count=len(bindings),pins=initial,
        source_scope_activation_proven=False,input_versions_at_call_proven=False,
        current_task_fields_proven=False,target_executed=False,first_stage_complete=False)
    if _pins()!=initial:raise ValueError('state binding producer changed')
    _durable_bytes(out/'result.json',_json(report),replace=False)
    return report


def read_configuration_state_bindings(path):
    path=Path(path).absolute();raw=(path/'result.json').read_bytes();report=json.loads(raw)
    if ((report['schema'],report['schema_version'],report['status'])!=
            ('scar.configuration-state-bindings',1,'DECLARED_CALL_STATE_PROJECTION_CANDIDATES')
            or report['pins']!=_pins()):raise ValueError('source state projection producer differs')
    for name in ('values','facts'):
        if sha256((Path(report[name])/'result.json').read_bytes()).hexdigest()!=report[name+'_sha256']:
            raise ValueError('source state projection parent differs')
    rows=tuple(decode(S.SourceStateProjection,row,record_tags=P.PRODUCTION_RECORD_TAGS)
        for row in _table(path,report['bindings']))
    expected=_anchors(report['values'],report['facts'])
    if rows!=expected or len(rows)!=report['binding_count']:
        raise ValueError('source state projection lost its original ports or alias witnesses')
    if any(report[name] for name in ('source_scope_activation_proven','input_versions_at_call_proven',
            'current_task_fields_proven','target_executed','first_stage_complete')) or (path/'result.json').read_bytes()!=raw:
        raise ValueError('source boundary candidates have no current-content authority')
    return report,rows


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--values',required=True);parser.add_argument('--facts',required=True);parser.add_argument('--out',required=True)
    args=parser.parse_args();report=build_configuration_state_bindings(args.values,args.facts,args.out)
    print(json.dumps({key:report[key] for key in ('status','binding_count')}),flush=True)


if __name__=='__main__':main()
