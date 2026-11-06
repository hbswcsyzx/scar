"""Build ordered file-configuration subgraphs without executing the program.

Known file payloads remain shared representation graphs. Missing providers,
choice rewrites and the implicit library root remain explicit dependencies;
this pass does not manufacture a final cfg from an incomplete defaults tree.
"""
import argparse
import ast
from hashlib import sha256
import json
import posixpath
from pathlib import Path
import re

from scar.analysis.source_configuration_request_store import read_configuration_requests
from scar.analysis.source_data_materials import parse_yaml_material,_artifact,_text_view
from scar.analysis.source_data_material_store import write_data_material
from scar.analysis.static_sources import _absolute
from scar.analysis.source_template_links import _json
from scar.ir.program import configuration_composition as C
from scar.ir.program.data_materials import DataNodeKind
from scar.ir.program.providers import ProviderArtifact


# Source-only library interpretation. Hashes cover complete functions, including
# nested bodies; no target import or invocation is used to obtain this profile.
_PROFILE_FUNCTIONS={
    'plugins/config_source.py':('ConfigSource._get_header_dict',),
    '_internal/core_plugins/file_config_source.py':('FileConfigSource.load_config',),
    'core/default_element.py':('InputDefault._get_final_package','InputDefault.set_package_header',
        'ConfigDefault.get_config_path','ConfigDefault._relative_group_path',
        'GroupDefault.get_group_path','GroupDefault._relative_group_path'),
    '_internal/defaults_list.py':('_validate_self','_update_overrides','_create_defaults_tree_impl','_tree_to_list','_create_root'),
    '_internal/config_loader_impl.py':('ConfigLoaderImpl._compose_config_from_defaults_list','ConfigLoaderImpl._load_single_config'),
}
_APPROVED_AST={
    'ConfigSource._get_header_dict':'3d363021095d664b5453daf52f66c7ad88b25d5edaf5482354e51354915de228',
    'FileConfigSource.load_config':'a39f3c9a83047bb7f2cd800350e6522d6bebc4a071042a99b6dd0da495d76756',
    'InputDefault._get_final_package':'e7fe33c7dd01924ba026d4df38582bd06ae34889ba1c820b0452fa6d9b7f2ccc',
    'InputDefault.set_package_header':'aac74444e2f617626c5c8004643ebd056186fb270ecb0276d45dd9bf948b68b6',
    'ConfigDefault.get_config_path':'b320f0617e842fb30529bfe4aea180d7359637a09cb7b50b0dcd7477e8270db2',
    'ConfigDefault._relative_group_path':'5baab09ef4f152f06d310d83d0fce267af9da8cb925777e56468246f94ad2964',
    'GroupDefault.get_group_path':'35a3503b715ef17061583d3c7262a73dc2bbd6ca621b882ec2da60f7f0aa1703',
    'GroupDefault._relative_group_path':'b1370e4aebf54a2fa0ac92e5c62ce5b52c17c35521cbd1eb450ef25485e01b62',
    '_validate_self':'da7b74b43d615a004968da1ab0dd3ee02397d160389e9aef479fb05e124d9672',
    '_update_overrides':'d9952b52f60328caa572e011e1881dee952545db893b7b4df56a06eb39f05a01',
    '_create_defaults_tree_impl':'3872b68e9fcee0061af1fdf7bff1f0b1a260f1d8c5d869ccb34ceebf28b87f05',
    '_tree_to_list':'9ac74e3183a5e4238a621b2ebc2d19d5388d60960fb1f9d6869936eb3b33973f',
    'ConfigLoaderImpl._compose_config_from_defaults_list':'803c9fddebc9abcca9dea8cd9f5f7489b875ddc414a87b3e49eacfa0d502a8d7',
    'ConfigLoaderImpl._load_single_config':'1a8912623f7fcd17e2fe92c53000c97990620da43263bfcf98083dc51db922db',
    '_create_root':'4f9ab91d8ef6fa01ad09b22a9827cef0c25cf5a788f5a859954a68bac4d3a8fc',
}


def protocol_sources(root):
    """Retain exact source versions for the interpretation's reviewed rules."""
    result=[]
    for relative,names in _PROFILE_FUNCTIONS.items():
        artifact,raw=_artifact(Path(root)/relative,'scar.configuration-composition-protocol-source')
        tree=ast.parse(raw)
        for qualified in names:
            owner=tree
            for name in qualified.split('.'):
                owner=next(n for n in owner.body if isinstance(n,(ast.ClassDef,ast.FunctionDef)) and n.name==name)
            digest=sha256(ast.dump(owner,include_attributes=False).encode()).hexdigest()
            if digest!=_APPROVED_AST[qualified]:raise ValueError('unmodeled configuration protocol source version: '+qualified)
            result.append(C.ConfigurationProtocolSource(artifact,qualified,digest))
    return tuple(result)


def _header(raw):
    # FileConfigSource reads 512 *characters* through UTF8 universal-newline IO.
    text,_=_text_view(raw);header={}
    for line in text[:512].splitlines():
        line=line.strip()
        if not line:continue
        if not re.match(r'^\s*#\s*@',line):break
        parts=[p for p in line.lstrip('#').strip().split(' ') if p]
        if len(parts)!=2:raise ValueError('library package header requires two components')
        key,value=parts
        if key.startswith('@'):header[key[1:]]=value
    return header.get('package')


def _package(parent,relative_group,override,header,default_group=None):
    if override is not None:
        package='' if override=='_here_' else override
        if '_group_' in package:
            group=relative_group if default_group is None else default_group
            package='_global_.'+package.replace('_group_',group.replace('/','.'))
    elif header is not None:
        package=header if header=='_global_' or header.startswith('_global_.') else '_global_.'+header
    else:package=relative_group.replace('/','.')
    if '_name_' in package or '_group_' in package or '${' in package:
        raise ValueError('version-dependent or interpolated package requires a separate rule')
    joined='.'.join(p for p in (parent,package) if p)
    last=joined.rfind('_global_')
    return joined[last+len('_global_')+1:] if last>=0 else joined


class _Builder:
    def __init__(self,request,candidate,index,out,loader_source,profiles,max_files):
        self.request=request;self.candidate=candidate;self.index=index;self.out=out
        self.loader_source=loader_source;self.profiles=profiles;self.max_files=max_files
        self.materials={};self.data={};self.dependencies=[];self.steps=[];self.obligations=[]
        self.active=set();self.packages={}
        self.conditions=(*request.conditions,*candidate.conditions,
            'VERSIONED_HYDRA_DEFAULTS_PROTOCOL_AND_FILE_CANDIDATES_SELECTED',
            'NO_MATCHED_CONFIG_STORE_SCHEMA_FOR_FILE_PAYLOADS',
            'UNRESOLVED_CHOICE_REWRITES_DO_NOT_REPLACE_LOCAL_FILE_SELECTIONS')
        self.step(C.ConfigurationStepKind.EMPTY)
        self.step(C.ConfigurationStepKind.OPEN_PROVIDER)
        self.obligation('IMPLICIT_LIBRARY_ROOT_PROVIDER_PENDING',None,None,
            'Hydra inserts hydra/config before the primary config; ConfigStore and package providers are not loaded here.')

    def obligation(self,code,dependency,material,detail):
        self.obligations.append(C.ConfigurationCompositionObligation(code,dependency,material,detail))

    def step(self,kind,*,instance=None,dependency=None,material=None,package=''):
        row=C.ConfigurationStep(len(self.steps),kind,len(self.steps)-1 if self.steps else None,
            instance,dependency,None if material is None else material.id,
            None if material is None else material.root_reference,
            tuple(package.split('.')) if package else (),
            ('defaults',) if kind is C.ConfigurationStepKind.MERGE_MATERIAL else (),self.conditions)
        self.steps.append(row)

    def capture(self,resource):
        path=Path(resource).absolute();key=str(path)
        if key in self.materials:return self.materials[key],self.data[key]
        if len(self.materials)>=self.max_files:raise ValueError('configuration file budget reached')
        data,raw=parse_yaml_material(path,loader_source=self.loader_source)
        identity=sha256(_json(dict(uri=data.source.uri,sha256=data.source.sha256))).hexdigest()
        folder=self.out/'materials'/identity
        write_data_material(data,raw,folder)
        report_raw=(folder/'result.json').read_bytes()
        row=C.ConfigurationMaterial(identity,ProviderArtifact(str(folder/'result.json'),
            sha256(report_raw).hexdigest(),len(report_raw),'scar.source-data-material'),
            data.source,data.root,_header(raw))
        self.materials[key]=row;self.data[key]=data
        self.obligation('APPLICATION_MATCHED_SCHEMA_LOOKUP_PENDING',None,identity,
            'A same-name ConfigStore schema can supply fields before this file payload is embedded: '+key)
        for obligation in data.obligations:
            self.obligation('DATA_'+obligation.code,None,identity,obligation.detail)
        return row,data

    @staticmethod
    def node(data,ref):return data.nodes[data.references[ref].target]

    def scalar(self,data,ref):
        node=self.node(data,ref)
        if node.kind is not DataNodeKind.SCALAR or node.representation_literal is None:
            raise ValueError('defaults requires an admitted scalar representation')
        return node.representation_literal.to_python()

    def defaults(self,data):
        if data.root is None:return ()
        root=self.node(data,data.root)
        if root.kind is not DataNodeKind.MAPPING:raise ValueError('configuration root requires a mapping')
        entries=[entry for entry in root.entries if self.scalar(data,entry.key)=='defaults']
        if len(entries)>1:raise ValueError('duplicate defaults key')
        if not entries:return ()
        node=self.node(data,entries[0].value)
        if node.kind is not DataNodeKind.SEQUENCE:raise ValueError('defaults requires a sequence')
        return node.items

    def visit(self,config_path,parent_package='',relative_group='',package_override=None,parent_dependency=None,lookup_group=None):
        normalized=posixpath.normpath(config_path).lstrip('/')
        if normalized.endswith('.yml'):raise ValueError('legacy .yml extension requires a version-base rule')
        resource=Path(self.candidate.root)/(normalized if normalized.endswith('.yaml') else normalized+'.yaml')
        # Do not traverse guessed search roots, symlinks or runtime providers.
        resource=_absolute(resource)
        if not resource.is_relative_to(Path(self.candidate.root).absolute()):
            raise ValueError('configuration path leaves the selected file search root')
        if not resource.is_file():return None
        material,data=self.capture(resource)
        group_base=posixpath.dirname(normalized) if lookup_group is None else lookup_group
        package=_package(parent_package,relative_group,package_override,material.package_header,group_base)
        instance=sha256(_json(dict(request=self.request.id,candidate=self.index,path=normalized,
            parent_dependency=parent_dependency,package=package))).hexdigest()
        self.packages[instance]=package
        active_key=material.id
        if active_key in self.active:
            self.obligation('RECURSIVE_DEFAULTS_DEPENDENCY',parent_dependency,material.id,normalized)
            self.step(C.ConfigurationStepKind.OPEN_PROVIDER,instance=instance,dependency=parent_dependency)
            return instance
        self.active.add(active_key)
        refs=list(self.defaults(data));self_refs=[ref for ref in refs
            if self.node(data,ref).kind is DataNodeKind.SCALAR and self.scalar(data,ref)=='_self_']
        if len(self_refs)>1:raise ValueError('duplicate _self_')
        if not self_refs:refs.append(None)
        base=posixpath.dirname(normalized) if lookup_group is None else lookup_group
        seen_override=False
        for ref in refs:
            if ref is None or (self.node(data,ref).kind is DataNodeKind.SCALAR and self.scalar(data,ref)=='_self_'):
                dep=C.ConfigurationDependency(len(self.dependencies),instance,material.id,ref,
                    C.ConfigurationDependencyKind.SELF,normalized,None,None,None,package,None,False,ref is None,self.conditions)
                self.dependencies.append(dep)
                self.step(C.ConfigurationStepKind.MERGE_MATERIAL,instance=instance,
                    dependency=dep.ordinal,material=material,package=package)
                continue
            node=self.node(data,ref);group=None;choice=None;override=None;optional=False
            kind=C.ConfigurationDependencyKind.CONFIG
            if node.kind is DataNodeKind.SCALAR:
                path=self.scalar(data,ref)
                if type(path) is not str:raise ValueError('defaults config path must be a string')
                path,separator,override=path.partition('@');override=override if separator else None
                group_path=posixpath.dirname(path.lstrip('/'))
            elif node.kind is DataNodeKind.MAPPING and len(node.entries)==1:
                entry=node.entries[0];group=self.scalar(data,entry.key);choice=self.scalar(data,entry.value)
                if type(group) is not str or (choice is not None and type(choice) is not str):
                    raise ValueError('defaults group choices require strings or null')
                kind=C.ConfigurationDependencyKind.GROUP
                if group.startswith('override '):group=group[len('override '):];kind=C.ConfigurationDependencyKind.OVERRIDE
                elif group.startswith('optional '):
                    # Selection is retained; absence is unresolved, not silently discarded.
                    group=group[len('optional '):];optional=True
                group,separator,override=group.partition('@');override=override if separator else None
                group_path=group.lstrip('/');path=posixpath.join(group,choice or '')
                if choice is None:kind=C.ConfigurationDependencyKind.NULL_CHOICE
            else:raise ValueError('defaults entry requires a config string or one group-choice pair')
            if seen_override and kind is not C.ConfigurationDependencyKind.OVERRIDE:
                raise ValueError('library defaults overrides must follow non-override entries')
            seen_override|=kind is C.ConfigurationDependencyKind.OVERRIDE
            absolute=path.startswith('/')
            child_path=posixpath.normpath(path.lstrip('/') if absolute else posixpath.join(base,path))
            ordinal=len(self.dependencies)
            dep=C.ConfigurationDependency(ordinal,instance,material.id,ref,kind,child_path,group,choice,
                override,None,None,optional,False,self.conditions)
            self.dependencies.append(dep)
            if '${' in path or choice=='???':
                self.obligation('DEFAULT_CHOICE_REQUIRES_VALUE_RESOLUTION',ordinal,material.id,path)
                self.step(C.ConfigurationStepKind.OPEN_PROVIDER,instance=instance,dependency=ordinal)
            elif kind is C.ConfigurationDependencyKind.OVERRIDE:
                self.obligation('GROUP_OVERRIDE_TARGET_SELECTION_PENDING',ordinal,material.id,
                    'Choice selection applies to the existing group, not a merge at this declaration position: '+child_path)
            elif kind is not C.ConfigurationDependencyKind.NULL_CHOICE:
                group_base=None if kind is C.ConfigurationDependencyKind.CONFIG else (
                    group.lstrip('/') if group.startswith('/') else posixpath.normpath(posixpath.join(base,group)))
                child=self.visit(child_path,package,group_path,override,ordinal,group_base)
                if child is None:
                    self.obligation('DEFAULT_PROVIDER_SELECTION_PENDING',ordinal,material.id,child_path)
                    self.step(C.ConfigurationStepKind.OPEN_PROVIDER,instance=instance,dependency=ordinal)
                else:
                    from dataclasses import replace
                    self.dependencies[ordinal]=replace(dep,child_instance=child,package=self.packages[child])
        self.active.remove(active_key)
        return instance

    def build(self):
        relative=Path(self.candidate.resource).relative_to(Path(self.candidate.root)).as_posix()
        if self.visit(relative) is None:raise ValueError('primary configuration file is unavailable')
        self.obligation('CLI_OVERRIDES_AND_LAZY_REFERENCES_PENDING',None,None,
            'This ordered graph precedes command-line overrides and lazy interpolation lookup.')
        return C.ConfigurationComposition(self.request.id,self.index,self.candidate.root,self.candidate.resource,
            self.profiles,tuple(self.materials.values()),tuple(self.dependencies),tuple(self.steps),
            tuple(self.obligations),len(self.steps)-1,self.conditions)


def build_configuration_composition(requests,out,*,hydra_source,loader_source,request_id=None,source_candidate=0,max_files=256):
    from scar.analysis.source_configuration_composition_store import write_configuration_composition
    _,rows=read_configuration_requests(requests)
    selected=[r for r in rows if request_id is None or r.id==request_id]
    if len(selected)!=1:raise ValueError('select exactly one configuration request')
    request=selected[0];candidate=request.sources[source_candidate]
    if candidate.protocol!='FILE' or candidate.root is None or candidate.resource is None:
        raise ValueError('this composition pass requires a conditional file source candidate')
    out=Path(out).absolute()
    if out.exists():raise ValueError('fresh composition output required')
    profiles=protocol_sources(hydra_source)
    out.mkdir(parents=True)
    builder=_Builder(request,candidate,source_candidate,out,loader_source,profiles,max_files)
    graph=builder.build()
    return write_configuration_composition(graph,requests,out)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--requests',required=True);parser.add_argument('--out',required=True)
    parser.add_argument('--hydra-source',required=True);parser.add_argument('--loader-source',required=True)
    parser.add_argument('--request-id');parser.add_argument('--source-candidate',type=int,default=0)
    args=parser.parse_args();report=build_configuration_composition(args.requests,args.out,
        hydra_source=args.hydra_source,loader_source=args.loader_source,
        request_id=args.request_id,source_candidate=args.source_candidate)
    print(json.dumps({key:report[key] for key in ('status','material_count','dependency_count','step_count','obligation_count')}),flush=True)


if __name__=='__main__':main()
