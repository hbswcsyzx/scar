"""Parse versioned YAML representation graphs without importing application code."""
from array import array
import ast
from collections import defaultdict
from hashlib import sha256
from pathlib import Path
import re
import sys

import yaml

from scar.analysis.static_sources import _absolute,_has_symlink_component,_read_raw_source
from scar.ir.literals import PythonLiteral
from scar.ir.program import data_materials as D
from scar.ir.program.providers import ProviderArtifact


# A library-contract version, not a workload rule. Inspecting a different
# loader implementation requires another explicit interpretation profile.
_OMEGA_LOADER_AST='f876d265614aeacd02a3a93945536d0c3745560f3136cf4904ea4d1061921a9b'
_SCALAR_TAGS=tuple('tag:yaml.org,2002:'+name for name in ('null','bool','int','float','str'))


def _artifact(path,schema):
    path=Path(path).absolute()
    if _has_symlink_component(path) is not None:
        raise ValueError('data/parser input must retain a non-symlink path: '+str(path))
    raw=_read_raw_source(path,path.stat().st_size)
    return ProviderArtifact(str(path),sha256(raw).hexdigest(),len(raw),schema),raw


def _profile(loader_source):
    folder=Path(yaml.__file__).resolve().parent
    tools=tuple(_artifact(path,'scar.yaml-parser-source')[0] for path in sorted(folder.glob('*.py')))
    executable=Path(sys.executable).resolve()
    tools+=(_artifact(executable,'scar.analyzer-python-executable')[0],)
    source=None;function_sha=None;pattern=None;flags=0;first='';removed=()
    if loader_source is not None:
        source,raw=_artifact(_absolute(loader_source),'scar.yaml-loader-contract-source')
        functions=[node for node in ast.parse(raw).body
            if isinstance(node,ast.FunctionDef) and node.name=='get_yaml_loader']
        if len(functions)!=1:raise ValueError('one original YAML loader function required')
        function=functions[0]
        function_sha=sha256(ast.dump(function,include_attributes=False).encode()).hexdigest()
        if function_sha!=_OMEGA_LOADER_AST:
            raise ValueError('YAML loader has no verified scalar-resolution profile')
        resolver=next(node for node in ast.walk(function) if isinstance(node,ast.Call)
            and isinstance(node.func,ast.Attribute) and node.func.attr=='add_implicit_resolver')
        assert ast.literal_eval(resolver.args[0])=='tag:yaml.org,2002:float'
        pattern=ast.literal_eval(resolver.args[1].args[0]);flags=int(re.X)
        first=ast.literal_eval(resolver.args[2].args[0])
        removed=('tag:yaml.org,2002:timestamp',)
    rule='PYYAML_SAFE_SCALARS' if source is None else 'OMEGACONF_VERSIONED_SCALAR_RESOLUTION'
    profile=D.DataParserProfile(rule,tools,source,function_sha,pattern,flags,first,removed,_SCALAR_TAGS)
    return profile


def _text_view(raw):
    """Match UTF-8 text IO's universal-newline view and retain raw byte bounds."""
    text=raw.decode('utf-8');view=[];offsets=array('Q',[0]);index=0;offset=0
    while index<len(text):
        char=text[index];offset+=len(char.encode('utf-8'));index+=1
        if char=='\r':
            if index<len(text) and text[index]=='\n':index+=1;offset+=1
            char='\n'
        view.append(char);offsets.append(offset)
    return ''.join(view),offsets


def parse_yaml_material(path,*,loader_source=None,max_bytes=8*1024*1024,max_nodes=100000):
    """Return ``(DataMaterial, raw_bytes)``; no container is constructed.

    Scalar literals describe the representation only. Configuration missing
    markers, interpolation, packages and merges are not evaluated here.
    """
    path=_absolute(path)
    if _has_symlink_component(path) is not None:raise ValueError('data input traverses a symbolic link')
    raw=_read_raw_source(path,max_bytes);text,offsets=_text_view(raw)
    source=ProviderArtifact(str(path),sha256(raw).hexdigest(),len(raw),'scar.source-data-bytes')
    profile=_profile(loader_source)
    nodes=[];node_ids={};anchors={};references=[];children=defaultdict(dict)

    def span(begin,end):
        return D.DataSpan(offsets[begin.index],offsets[end.index],begin.line,begin.column,end.line,end.column)

    def node_id(node):
        key=id(node)
        if key not in node_ids:
            if len(nodes)>=max_nodes:raise ValueError('data node budget reached')
            node_ids[key]=len(nodes);nodes.append(node)
        return node_ids[key]

    class GraphLoader(yaml.SafeLoader):
        # add_implicit_resolver copies this table before modifying it. The
        # explicit clone also keeps filtering local to this interpretation.
        yaml_implicit_resolvers={key:list(rows) for key,rows in yaml.SafeLoader.yaml_implicit_resolvers.items()}

        def compose_node(self,parent,index):
            event=self.peek_event();alias=isinstance(event,yaml.AliasEvent)
            node=super().compose_node(parent,index)
            target=node_id(node)
            if not alias:anchors[id(node)]=event.anchor
            ref=len(references)
            if ref>=4*max_nodes:raise ValueError('data reference budget reached')
            references.append(D.DataReference(ref,target,
                span(event.start_mark,event.end_mark) if alias else span(node.start_mark,node.end_mark),
                alias,event.anchor))
            if parent is not None:
                slot=('item',index) if isinstance(parent,yaml.SequenceNode) else (
                    'key' if index is None else 'value',len(parent.value))
                children[id(parent)][slot]=ref
            return node

    if profile.float_pattern is not None:
        GraphLoader.add_implicit_resolver('tag:yaml.org,2002:float',
            re.compile(profile.float_pattern,profile.float_flags),list(profile.float_initial_characters))
    if profile.removed_implicit_tags:
        GraphLoader.yaml_implicit_resolvers={key:[(tag,pattern) for tag,pattern in rows
            if tag not in profile.removed_implicit_tags] for key,rows in GraphLoader.yaml_implicit_resolvers.items()}
    loader=GraphLoader(text)
    obligations=[];records=[]
    try:
        root_node=loader.get_single_node()
        root=None if root_node is None else len(references)-1
        for index,node in enumerate(nodes):
            slots=children.get(id(node),{});literal=None;scalar=None;style=None;flow=None;items=();entries=()
            if isinstance(node,yaml.ScalarNode):
                kind=D.DataNodeKind.SCALAR;scalar=node.value;style=node.style
                if node.tag in profile.scalar_tags:
                    literal=PythonLiteral.from_python(loader.construct_object(node),exact=True)
                else:
                    obligations.append(D.DataObligation('UNINTERPRETED_SCALAR_TAG',index,None,node.tag))
            elif isinstance(node,yaml.SequenceNode):
                kind=D.DataNodeKind.SEQUENCE;flow=node.flow_style
                items=tuple(slots['item',i] for i in range(len(node.value)))
            elif isinstance(node,yaml.MappingNode):
                kind=D.DataNodeKind.MAPPING;flow=node.flow_style
                entries=tuple(D.DataMappingEntry(slots['key',i],slots['value',i]) for i in range(len(node.value)))
                seen=set()
                for key,_ in node.value:
                    if key.tag=='tag:yaml.org,2002:merge':
                        obligations.append(D.DataObligation('MAPPING_MERGE_NOT_CONSTRUCTED',index,None,'Merge syntax retained as entries.'))
                    if profile.loader_source is not None and isinstance(key,yaml.ScalarNode) and key.tag=='tag:yaml.org,2002:str':
                        if key.value in seen:
                            obligations.append(D.DataObligation('LOADER_REJECTS_DUPLICATE_STRING_KEY',index,None,key.value))
                        seen.add(key.value)
            else:raise ValueError('unsupported YAML node constructor')
            expected_tag={D.DataNodeKind.SEQUENCE:'tag:yaml.org,2002:seq',
                D.DataNodeKind.MAPPING:'tag:yaml.org,2002:map'}.get(kind)
            if expected_tag is not None and node.tag!=expected_tag:
                obligations.append(D.DataObligation('UNINTERPRETED_CONTAINER_TAG',index,None,node.tag))
            records.append(D.DataNode(index,kind,node.tag,span(node.start_mark,node.end_mark),anchors.get(id(node)),
                scalar,style,flow,literal,items,entries))
        material=D.DataMaterial(source,profile,sha256(text.encode('utf-8')).hexdigest(),root,
            tuple(records),tuple(references),tuple(obligations))
    finally:loader.dispose()
    if _read_raw_source(path,max_bytes)!=raw:raise ValueError('data source changed during parsing')
    return material,raw


def main():
    import argparse,json
    from scar.analysis.source_data_material_store import write_data_material
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--file',required=True);parser.add_argument('--out',required=True)
    parser.add_argument('--loader-source')
    args=parser.parse_args()
    material,raw=parse_yaml_material(args.file,loader_source=args.loader_source)
    result=write_data_material(material,raw,args.out)
    print(json.dumps(dict(status=result['status'],nodes=len(material.nodes),
        references=len(material.references),obligations=len(material.obligations))),flush=True)


if __name__=='__main__':main()
