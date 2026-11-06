"""Build configuration state algebra and static field/reference dependencies."""
import argparse
import ast
from hashlib import sha256
import json
from pathlib import Path

from scar.analysis.source_configuration_overrides import read_configuration_overrides
from scar.analysis.source_configuration_composition_store import read_configuration_composition
from scar.analysis.source_data_material_store import DataMaterialStore
from scar.analysis.source_data_materials import _artifact
from scar.analysis.source_interpolation_syntax import InterpolationSyntax
from scar.analysis.source_configuration_value_query import ConfigurationValueQuery
from scar.ir.program import configuration_values as V
from scar.ir.program.configuration_composition import ConfigurationStepKind,ConfigurationProtocolSource
from scar.ir.program.configuration_overrides import OverrideAction,OverrideExpressionKind
from scar.ir.program.providers import ProviderArtifact


_FUNCTIONS={
    'basecontainer.py':{
        'BaseContainer._map_merge':'1113d71066b535589df25331ddc9d4b574e6a545bf6e5a36c682e9c2b9cb6220',
        'BaseContainer._list_merge':'fb3aff9ad7e173b1ad2801bdf8984d2b69edec1a729920785584d038efd38f23',
        'BaseContainer._merge_with':'2f9323c2a98c369cf3f982bbbafc3e375c025157fc7f8383399ccd9ea6b50ae8'},
    'omegaconf.py':{
        'OmegaConf.update':'9d9fc6a9af46fcd2b7c04321fe89876968e693529d03c9c2161471b7efd75581',
        '_select_one':'6cb4383ca45a6b36bc9fb362dcd40b53e28efb4cf4609c5e0fbbc94b7645428e'},
    'base.py':{
        'Container._resolve_key_and_root':'3af964cfe0b5aa39eae5e74f53b53501ff84acf2638d6ada908dbc10e31645d0',
        'Container._select_impl':'8d070e2c47c95ddedb8048411bfd372fadf7f71809b40ffd2865ddf1738b1f55',
        'Container._resolve_node_interpolation':'4b395643b39af89423942653170f47100adee8db69c71b62ef404ebdd954b87c'},
    '_utils.py':{
        '_is_missing_literal':'eda4f88d6e8b9abc7ed5f117bd76b671b607af2fd55677ab2e8709f8eb90ecfe',
        'split_key':'f5789a69cd24b91c7908ae54c83fd8ae8bfc787f0a5f702cc9ef0418c15f4cea'},
    'grammar_visitor.py':{
        'GrammarVisitor.visitInterpolationNode':'543c6824f5b4444b494fca49e7ee6a8c4046cd80054cd19246b236d31544cbe7',
        'GrammarVisitor.visitText':'e494683fed48b9afcda008453d9c015f414208c586f918959a93c6889198724a',
        'GrammarVisitor._unescape':'a12bcd4c4eb3b5adbb0725be73e30863b847cd32a613f622528b620881147cab'},
    'nodes.py':{'ValueNode._set_value':'a6d4c90dfa204321a4cb0b20e6ad0e11a9174222e20cfb361663935472646d33'},
    'dictconfig.py':{
        'DictConfig._validate_merge':'ac29de5abf60c70f85ec05acb35e94b568572b138b7d1a030969f8ee087aa6c9',
        'DictConfig._validate_non_optional':'e047eb8134631f1b200059e4a993a75e281fcf89a5ecbb8b8d947372f3754b85'},
}


def protocol_sources(root):
    result=[]
    for relative,functions in _FUNCTIONS.items():
        artifact,raw=_artifact(Path(root)/relative,'scar.configuration-value-protocol-source')
        tree=ast.parse(raw)
        if relative=='_utils.py':
            patterns={node.targets[0].id:ast.literal_eval(node.value.args[0]) for node in tree.body
                if isinstance(node,ast.Assign) and len(node.targets)==1 and isinstance(node.targets[0],ast.Name)
                and node.targets[0].id in ('KEY_PATH_HEAD','KEY_PATH_OTHER')}
            if patterns!={'KEY_PATH_HEAD':r'(\.)*[^.[]*','KEY_PATH_OTHER':r'\.([^.[]*)|\[(.*?)\]'}:
                raise ValueError('configuration key path rules differ')
        for qualified,expected in functions.items():
            node=tree
            for name in qualified.split('.'):
                node=next(n for n in node.body if isinstance(n,(ast.ClassDef,ast.FunctionDef)) and n.name==name)
            digest=sha256(ast.dump(node,include_attributes=False).encode()).hexdigest()
            if digest!=expected:raise ValueError('configuration value protocol version is not modeled: '+qualified)
            result.append(ConfigurationProtocolSource(artifact,qualified,digest))
    return tuple(result)


def compile_configuration_expressions(base,overrides,override_sha):
    """Translate existing operations, retaining their table coordinates and guards."""
    expressions=[];roots=[];composition_roots={};E=V.ConfigurationExpressionKind

    def emit(kind,inputs=(),source=None,path=(),exclusions=(),*,stage,index,conditions):
        ordinal=len(expressions)
        expressions.append(V.ConfigurationExpression(ordinal,kind,inputs,source,path,exclusions,stage,index,conditions))
        return ordinal

    for step in base.steps:
        kwargs=dict(stage='COMPOSITION',index=step.ordinal,conditions=step.conditions)
        if step.kind is ConfigurationStepKind.EMPTY:root=emit(E.EMPTY,**kwargs)
        elif step.kind is ConfigurationStepKind.OPEN_PROVIDER:
            opened=emit(E.OPEN_PROVIDER,**kwargs)
            root=emit(E.MERGE,(composition_roots[step.previous],opened),**kwargs)
        else:
            payload=emit(E.INPUT,source=V.ConfigurationInput('MATERIAL_REFERENCE',step.material,step.root_reference),
                exclusions=step.exclude_root_keys,**kwargs)
            if step.package:payload=emit(E.EMBED,(payload,),path=step.package,**kwargs)
            root=emit(E.MERGE,(composition_roots[step.previous],payload),**kwargs)
        composition_roots[step.ordinal]=root;roots.append(V.ConfigurationRoot('COMPOSITION',step.ordinal,root))
    root=composition_roots[overrides.composition_version]
    roots.append(V.ConfigurationRoot('OVERRIDE',0,root))
    for row in overrides.overrides:
        kwargs=dict(stage='OVERRIDE',index=row.ordinal,conditions=row.conditions)
        value=None if row.value is None else emit(E.INPUT,
            source=V.ConfigurationInput('OVERRIDE_EXPRESSION',override_sha,row.value),**kwargs)
        if row.field_path_candidate is None:
            opened=emit(E.OPEN_PROVIDER,**kwargs)
            root=emit(E.MERGE,(root,opened),**kwargs)
        elif row.action is OverrideAction.DELETE:
            root=emit(E.DELETE,(root,) if value is None else (root,value),path=row.field_path_candidate,**kwargs)
        else:
            tag=overrides.expressions[row.value].kind
            kind=E.UPDATE if tag in (OverrideExpressionKind.MAPPING,OverrideExpressionKind.SEQUENCE) else E.ASSIGN
            root=emit(kind,(root,value),path=row.field_path_candidate,**kwargs)
        roots.append(V.ConfigurationRoot('OVERRIDE',row.output_version,root))
    return tuple(expressions),tuple(roots),root


def build_configuration_values(overrides,out,*,omegaconf_source,paths=None,max_projections=20000):
    from scar.analysis.source_configuration_value_store import write_configuration_values,pins
    initial=pins()
    overrides=Path(overrides).absolute();out=Path(out).absolute()
    if out.exists():raise ValueError('fresh configuration value graph required')
    raw=(overrides/'result.json').read_bytes();override_sha=sha256(raw).hexdigest()
    _,overlay=read_configuration_overrides(overrides)
    _,base=read_configuration_composition(Path(overlay.composition.uri).parent)
    materials={m.id:DataMaterialStore(Path(m.store.uri).parent).read() for m in base.materials}
    profiles=protocol_sources(omegaconf_source);syntax=InterpolationSyntax(omegaconf_source)
    expressions,roots,selected=compile_configuration_expressions(base,overlay,override_sha)
    conditions=tuple(dict.fromkeys((*overlay.conditions,*(c for r in overlay.overrides for c in r.conditions),
        'PLAIN_UNTYPED_CONFIG_CONTAINER_PROTOCOL_SELECTED',
        'NORMAL_SUCCESS_AT_EACH_RECORDED_ROOT_VERSION',
        'OPEN_DESTINATIONS_DO_NOT_EAGERLY_RESOLVE_LAZY_CANDIDATES',
        'OPEN_UPDATE_ANCESTORS_USE_DIRECT_MAPPING_LOCATIONS',
        'PENDING_EAGER_EFFECTS_DO_NOT_INVALIDATE_OTHER_PROJECTIONS',
        'ADD_DELETE_EXISTENCE_AND_VALUE_MATCH_GUARDS_SATISFIED')))
    query=ConfigurationValueQuery(expressions,materials,overlay,override_sha,syntax,conditions,max_projections=max_projections)
    for path in query.known_paths(selected) if paths is None else paths:query.project(selected,path)
    query.obligation('UPSTREAM_CONFIGURATION_CONDITIONS_UNDISCHARGED',detail=
        'Provider/schema/search selection, current argv, parsed function values, callbacks and task-world binding remain conditional.')
    parent=ProviderArtifact(str(overrides/'result.json'),override_sha,len(raw),'scar.configuration-overrides')
    graph=V.ConfigurationValues(parent,profiles,syntax.profiles,expressions,roots,tuple(query.projections),
        tuple(query.interpolations),tuple(query.read_demands),tuple(query.obligations),selected,conditions)
    if (overrides/'result.json').read_bytes()!=raw or pins()!=initial:
        raise ValueError('configuration override parent or analysis implementation changed')
    return write_configuration_values(graph,out)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--overrides',required=True);parser.add_argument('--out',required=True)
    parser.add_argument('--omegaconf-source',required=True)
    parser.add_argument('--path-json',action='append',help='One precise string-segment path as a JSON array; default: known paths')
    args=parser.parse_args();paths=None if args.path_json is None else [tuple(json.loads(p)) for p in args.path_json]
    if paths is not None and any(any(type(s) is not str for s in path) for path in paths):
        raise ValueError('configuration selector segments must be strings')
    report=build_configuration_values(args.overrides,args.out,omegaconf_source=args.omegaconf_source,paths=paths)
    print(json.dumps({k:report[k] for k in ('status','expression_count','root_count','projection_count',
        'interpolation_count','read_demand_count','obligation_count')}),flush=True)


if __name__=='__main__':main()
