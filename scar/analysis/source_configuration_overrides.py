"""Lower declared argv into conditional, versioned configuration writes.

The syntax tool reuses the installed generated ANTLR grammar, isolated from
Hydra initialization. Library visitors and user functions are never invoked.
"""
import argparse
import ast
from hashlib import sha256
import json
from pathlib import Path
import re

from scar.analysis.source_configuration_composition_store import read_configuration_composition
from scar.analysis.source_configuration_request_store import read_configuration_requests
from scar.analysis.source_data_materials import _artifact
from scar.analysis.source_override_syntax import OverrideSyntax
from scar.analysis.source_symbol_variants import _table
from scar.analysis.normal_output import write_table
from scar.analysis.source_stage import _durable_bytes
from scar.analysis.source_template_links import _json
from scar.ir.literals import PythonLiteral
from scar.ir.program import configuration_overrides as O,source_launch as L,source_productions as P
from scar.ir.program.configuration_composition import ConfigurationProtocolSource
from scar.ir.program.providers import ProviderArtifact
from scar.ir.program.source_frame_bindings import StaticInputPort
from scar.ir.record_codec import decode,encode


_FUNCTIONS={
    '_internal/utils.py':('get_args_parser',),
    'core/override_parser/overrides_visitor.py':('HydraOverrideVisitor._createPrimitive',
        'HydraOverrideVisitor._unescape_quoted_string','HydraOverrideVisitor.visitOverride','HydraOverrideVisitor.visitKey'),
    'core/override_parser/types.py':('Override._convert_value','Override.value'),
    '_internal/defaults_list.py':('Overrides.__init__',),
    '_internal/config_loader_impl.py':('ConfigLoaderImpl._apply_overrides_to_config',),
}
_APPROVED_AST={
    'get_args_parser':'812bfc3c6ebe8d6657bbaacf955486f8af8baf3f16989cb2230ac49d4965d3f8',
    'HydraOverrideVisitor._createPrimitive':'9d26d1bfecaed1e4e03745f3766da01db8e09d514c6f5f7f2663d37356fff365',
    'HydraOverrideVisitor._unescape_quoted_string':'17edacba6c69ee643d944a11bf446f1faefb34995d071e8cd84b0ce4e9b9f685',
    'HydraOverrideVisitor.visitOverride':'504ed5fea0d4e119234e97c3f7c8a00e7fba969589e29bda7f3dff5336cea4a7',
    'HydraOverrideVisitor.visitKey':'0bbba3e8216036af02314cba7cc775c8dc074ff2a27329e21b7b87b2dce6f0ad',
    'Override._convert_value':'f55a1939df7f5ad3107888c7f6b16b8188aa2afb2252c63b38392eba9a02ae0f',
    'Override.value':'95301ca7c5a96635c1dbc27755fa5e8cf0b809ff30d1b9960fc3f823e099bba5',
    'Overrides.__init__':'5becd87f4546b7cd73706f1908f198391700c0abb014d642101be157ce89d125',
    'ConfigLoaderImpl._apply_overrides_to_config':'61e9fef249442f59fb8271fa4fdc2a8994b6dab101918677bdf3233dbcf060f7',
}


def _protocol(root):
    sources=[];args_function=None
    for relative,names in _FUNCTIONS.items():
        source,raw=_artifact(Path(root)/relative,'scar.configuration-override-protocol-source')
        tree=ast.parse(raw)
        for name in names:
            node=tree
            for part in name.split('.'):
                node=next(n for n in node.body if isinstance(n,(ast.ClassDef,ast.FunctionDef)) and n.name==part)
            digest=sha256(ast.dump(node,include_attributes=False).encode()).hexdigest()
            if digest!=_APPROVED_AST[name]:raise ValueError('unmodeled override interpretation source version: '+name)
            sources.append(ConfigurationProtocolSource(source,name,digest))
            if name=='get_args_parser':args_function=node
    return tuple(sources),args_function


class _Parser(argparse.ArgumentParser):
    def error(self,message):raise ValueError('declared argv is outside the normal configuration request: '+message)
    def exit(self,status=0,message=None):raise ValueError('declared argv selects a non-task CLI exit')


class _Argument(str):
    def __new__(cls,text,index):
        instance=super().__new__(cls,text);instance.index=index;return instance


def _arguments(function,argv):
    """Use stdlib argparse on literal declarations, retaining positional indices."""
    parser=_Parser(add_help=False,description='Static configuration input')
    environment={}
    for node in function.body:
        if isinstance(node,ast.Assign) and len(node.targets)==1 and isinstance(node.targets[0],ast.Name):
            try:environment[node.targets[0].id]=ast.literal_eval(node.value)
            except (ValueError,TypeError):pass
    for node in ast.walk(function):
        if not (isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute)
                and isinstance(node.func.value,ast.Name) and node.func.value.id=='parser'
                and node.func.attr=='add_argument'):continue
        flags=[ast.literal_eval(arg) for arg in node.args];kwargs={}
        for keyword in node.keywords:
            if keyword.arg in ('help','version'):continue
            if keyword.arg not in ('nargs','const','action','choices','default','required','dest'):
                raise ValueError('unmodeled argument declaration field')
            value=environment[keyword.value.id] if isinstance(keyword.value,ast.Name) else ast.literal_eval(keyword.value)
            kwargs[keyword.arg]=value
        if kwargs.get('action')=='version':kwargs['version']='<unevaluated-target-version>'
        parser.add_argument(*flags,**kwargs)
    parsed=parser.parse_args([_Argument(token,i) for i,token in enumerate(argv) if i])
    if any(getattr(parsed,name,False) for name in ('help','hydra_help','multirun','shell_completion','cfg','info','experimental_rerun')):
        raise ValueError('this graph requires a normal single-task CLI branch')
    if not all(isinstance(token,_Argument) for token in parsed.overrides):
        raise ValueError('positional argv provenance was lost')
    return parsed.overrides


def _unquote(text):
    quote=text[0];remaining=text[1:];pattern=re.compile(r'(\\)+'+re.escape(quote));parts=[]
    match=pattern.search(remaining)
    while match is not None:
        start,stop=match.span();parts.extend((remaining[:start],remaining[start+1:stop:2]))
        remaining=remaining[stop:];match=pattern.search(remaining)
    if len(remaining)>1:parts.append(remaining[:-1])
    return ''.join(parts)


class _Expressions:
    def __init__(self,syntax):self.syntax=syntax;self.rows=[];self.obligations=[]

    def primitive(self,ctx):
        lexer=self.syntax.lexer
        tokens=[child.symbol for child in ctx.children]
        while tokens and tokens[0].type==lexer.WS:tokens.pop(0)
        while tokens and tokens[-1].type==lexer.WS:tokens.pop()
        if not tokens:raise ValueError('whitespace-only override primitive')
        if len(tokens)>1:
            return ''.join(t.text[1::2] if t.type==lexer.ESC else t.text for t in tokens),None
        token=tokens[0];text=token.text
        if token.type==lexer.QUOTED_VALUE:return _unquote(text),text[0]
        if token.type==lexer.INT:return int(text),None
        if token.type==lexer.FLOAT:return float(text),None
        if token.type==lexer.NULL:return None,None
        if token.type==lexer.BOOL:return text.lower()=='true',None
        if token.type==lexer.ESC:return text[1::2],None
        return text,None

    def add(self,ctx,index):
        name=type(ctx).__name__;kind=O.OverrideExpressionKind
        if name in ('ValueContext','ElementContext'):return self.add(ctx.getChild(0),index)
        children=();entries=();function=None;names=();literal=None;quote=None
        if name in ('PrimitiveContext','DictKeyContext'):
            value,quote=self.primitive(ctx);literal=PythonLiteral.from_python(value,exact=True);tag=kind.SCALAR
        elif name in ('ListContainerContext','SimpleChoiceSweepContext'):
            children=tuple(self.add(child,index) for child in ctx.children if type(child).__name__=='ElementContext')
            tag=kind.SEQUENCE if name=='ListContainerContext' else kind.SWEEP
        elif name=='DictContainerContext':
            entries=tuple((self.add(pair.getChild(0),index),self.add(pair.getChild(2),index))
                for pair in ctx.children if type(pair).__name__=='DictKeyValuePairContext')
            tag=kind.MAPPING
        elif name=='FunctionContext':
            function=ctx.getChild(0).getText();parts=[];args=[];pending=None
            for child in ctx.children:
                if type(child).__name__=='ArgNameContext':pending=child.getChild(0).getText()
                elif type(child).__name__=='ElementContext':parts.append(self.add(child,index));args.append(pending);pending=None
            children=tuple(parts);names=tuple(args);tag=kind.CALL
        else:raise ValueError('unmodeled override syntax production: '+name)
        ordinal=len(self.rows)
        self.rows.append(O.OverrideExpression(ordinal,index,ctx.start.start,ctx.stop.stop+1,
            tag,literal,quote,children,entries,function,names))
        if tag in (kind.CALL,kind.SWEEP):
            self.obligations.append(O.ConfigurationOverrideObligation(
                'UNEVALUATED_OVERRIDE_FUNCTION' if tag is kind.CALL else 'SWEEP_SELECTION_PENDING',None,ordinal,ctx.getText()))
        return ordinal

    def empty(self,index,position):
        ordinal=len(self.rows)
        self.rows.append(O.OverrideExpression(ordinal,index,position,position,O.OverrideExpressionKind.SCALAR,
            PythonLiteral.from_python('',exact=True),None,(),(),None,()))
        return ordinal


def lower_overrides(tokens,contract,entry_sha,syntax,conditions):
    expressions=_Expressions(syntax);rows=[]
    for token in tokens:
        tree=syntax.parse(str(token));key=tree.key();key_text=key.packageOrGroup().getText()
        package=None if key.package() is None else key.package().getText()
        prefix=str(token)[:key.start.start]
        action={'':O.OverrideAction.CHANGE,'+':O.OverrideAction.ADD,'++':O.OverrideAction.FORCE_ADD,'~':O.OverrideAction.DELETE}[prefix]
        has_equal=any(getattr(child,'symbol',None) is not None and child.symbol.type==syntax.lexer.EQUAL for child in tree.children)
        value=expressions.add(tree.value(),token.index) if tree.value() is not None else (
            expressions.empty(token.index,len(token)) if has_equal else None)
        ordinal=len(rows);field_path=None if package is not None or '/' in key_text else tuple(key_text.split('.'))
        source=StaticInputPort(contract.root,entry_sha,('inputs','argv',token.index))
        selection=('CONFIG_GROUP_LOOKUP_DOES_NOT_INTERCEPT_FIELD_WRITE',
            'FIELD_UPDATE_SCHEMA_AND_EXISTENCE_CONDITIONS_SATISFIED') if field_path is not None else (
            'CONFIG_GROUP_LOOKUP_SELECTS_DEFAULT_CHOICE',)
        rows.append(O.ConfigurationOverride(ordinal,source,str(token),action,key_text,package,
            field_path,value,ordinal,ordinal+1,(*conditions,*selection)))
    return tuple(rows),tuple(expressions.rows),tuple(expressions.obligations)


def _pins():
    from scar.analysis import source_override_syntax
    return {name:sha256(Path(path).read_bytes()).hexdigest() for name,path in
        dict(producer=__file__,types=O.__file__,syntax=source_override_syntax.__file__).items()}


def _receipt(path,schema):
    raw=Path(path).read_bytes()
    return ProviderArtifact(str(Path(path).absolute()),sha256(raw).hexdigest(),len(raw),schema)


def build_configuration_overrides(composition,out,*,hydra_source):
    initial=_pins();composition=Path(composition).absolute();out=Path(out).absolute()
    if out.exists():raise ValueError('fresh configuration override output required')
    composition_report,base=read_configuration_composition(composition)
    request_report,_=read_configuration_requests(composition_report['requests']['path'])
    entry_path=Path(request_report['script_entry']['path'])/'entry.json'
    entry_raw=entry_path.read_bytes();entry_sha=sha256(entry_raw).hexdigest()
    if entry_sha!=request_report['entry_sha256']:raise ValueError('declared argv parent changed')
    entry=decode(L.ScriptEntryContract,json.loads(entry_raw),record_tags=P.PRODUCTION_RECORD_TAGS)
    protocols,function=_protocol(hydra_source);syntax=OverrideSyntax(hydra_source)
    tokens=_arguments(function,entry.inputs.argv)
    conditions=(*base.conditions,'INITIAL_ARGV_OVERRIDE_PROJECTION_STILL_VALID_AT_PARSE',
        'NORMAL_SINGLE_TASK_CLI_BRANCH_SELECTED')
    rows,expressions,pending=lower_overrides(tokens,entry,entry_sha,syntax,conditions)
    obligations=(*pending,O.ConfigurationOverrideObligation('CURRENT_ARGV_AND_APPENDED_TOKENS_PENDING',None,None,
        'Initial argv is mutable; later append/remove/replace effects remain outside this input projection.'),
        O.ConfigurationOverrideObligation('GROUP_LOOKUP_AND_FIELD_UPDATE_GUARDS_PENDING',None,None,
        'Repository group selection, schema, existence and merge semantics guard these candidate writes.'),
        O.ConfigurationOverrideObligation('LAZY_REFERENCE_AND_TASK_CFG_BINDING_PENDING',None,None,
        'Expressions are input values; missing markers and interpolation are not resolved by this pass.'))
    quoting,_=_artifact(Path(hydra_source)/'_internal/grammar/utils.py','scar.override-quoted-escape-contract-source')
    if quoting.sha256!='c808ea9915e1b9bfd3c9414bc113d674832acef101220897ee633e32729a4650':
        raise ValueError('unmodeled quoted-string escape contract')
    tools=(*syntax.profiles,_artifact(Path(argparse.__file__),'scar.analyzer-stdlib-argparse-source')[0],quoting)
    graph=O.ConfigurationOverrides(_receipt(composition/'result.json','scar.configuration-composition'),base.root_version,
        _receipt(entry_path,'scar.script-entry-contract'),protocols,tools,rows,expressions,obligations,len(rows),conditions)
    out.mkdir(parents=True)
    tables={name:write_table(out/(name+'.jsonl.gz'),getattr(graph,name)) for name in ('overrides','expressions','obligations')}
    header={name:encode(getattr(graph,name)) for name in ('composition','composition_version','entry','protocol_sources','parser_tools',
        'root_version','conditions','semantics')}
    report=dict(schema='scar.configuration-overrides',schema_version=1,status='INITIAL_ARGV_CONDITIONAL_OVERRIDE_GRAPH',
        **header,tables=tables,pins=initial,override_count=len(rows),expression_count=len(expressions),
        target_executed=False,current_argv_proven=False,configuration_resolved=False,first_stage_complete=False)
    if _pins()!=initial or sha256((composition/'result.json').read_bytes()).hexdigest()!=graph.composition.sha256:
        raise ValueError('override graph inputs or producer changed')
    _durable_bytes(out/'result.json',_json(report),replace=False)
    return report


def read_configuration_overrides(path):
    path=Path(path).absolute();raw=(path/'result.json').read_bytes();report=json.loads(raw)
    if ((report['schema'],report['schema_version'],report['status'])!=
            ('scar.configuration-overrides',1,'INITIAL_ARGV_CONDITIONAL_OVERRIDE_GRAPH')
            or report['pins']!=_pins()):raise ValueError('override graph producer differs')
    header={name:report[name] for name in ('composition','composition_version','entry','protocol_sources','parser_tools',
        'root_version','conditions','semantics')}
    for name in ('overrides','expressions','obligations'):header[name]=list(_table(path,report['tables'][name]))
    graph=decode(O.ConfigurationOverrides,header,record_tags=P.PRODUCTION_RECORD_TAGS)
    for artifact in (graph.composition,graph.entry,*graph.parser_tools,*(p.source for p in graph.protocol_sources)):
        parent=Path(artifact.uri).read_bytes()
        if len(parent)!=artifact.size_bytes or sha256(parent).hexdigest()!=artifact.sha256:
            raise ValueError('override graph parent or tool differs')
    _,base=read_configuration_composition(Path(graph.composition.uri).parent)
    if graph.composition_version!=base.root_version:raise ValueError('override base version differs')
    if graph.root_version!=len(graph.overrides) or report['override_count']!=len(graph.overrides) or report['expression_count']!=len(graph.expressions):
        raise ValueError('override graph denominators differ')
    entry=decode(L.ScriptEntryContract,json.loads(Path(graph.entry.uri).read_bytes()),record_tags=P.PRODUCTION_RECORD_TAGS)
    argv=entry.inputs.argv
    for i,override in enumerate(graph.overrides):
        if (override.ordinal!=i or (override.input_version,override.output_version)!=(i,i+1)
                or override.source.contract_sha256!=graph.entry.sha256
                or override.source.root!=entry.root
                or override.source.path[:2]!=('inputs','argv')
                or argv[override.source.path[2]]!=override.token
                or override.value is not None and not 0<=override.value<len(graph.expressions)):
            raise ValueError('override lost its input, expression or version chain')
    for i,expression in enumerate(graph.expressions):
        children=(*expression.children,*(c for pair in expression.entries for c in pair))
        if (expression.ordinal!=i or any(not 0<=c<i for c in children)
                or not 0<=expression.character_start<=expression.character_end<=len(argv[expression.argument_index])):
            raise ValueError('override expression references or spans differ')
    if (any(report[k] for k in ('target_executed','current_argv_proven','configuration_resolved','first_stage_complete'))
            or (path/'result.json').read_bytes()!=raw):raise ValueError('override graph has no runtime-value authority')
    return report,graph


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--composition',required=True);parser.add_argument('--out',required=True)
    parser.add_argument('--hydra-source',required=True)
    args=parser.parse_args();report=build_configuration_overrides(args.composition,args.out,hydra_source=args.hydra_source)
    print(json.dumps({k:report[k] for k in ('status','override_count','expression_count')}),flush=True)


if __name__=='__main__':main()
