"""Join retained text and builtin boundaries into explicit compiler inputs.

The CPython compiler is used as a static frontend, never to execute a target.
Code digests describe compiler values. They neither identify runtime objects
nor grant permission to attach an old body compiled in another context.
"""
import argparse
from collections import defaultdict
from hashlib import sha256
from io import BytesIO, TextIOWrapper
import gzip
import json
from pathlib import Path
import sys
from types import CodeType

from scar.analysis import source_execution, source_text_values, source_compilation_contexts
from scar.analysis.call_compilation import supported_future_flag_mask
from scar.analysis.normal_facts import SourceFactStore
from scar.analysis.normal_output import write_table
from scar.analysis.source_bytes import read_source_bytes
from scar.analysis.source_launch import read_script_entry
from scar.analysis.source_syntax import _digest
from scar.analysis.source_stage import _durable_bytes, _durable_mkdir
from scar.analysis.source_template_links import _json
from scar.analysis.static_query import _Fragments
from scar.ir.program import source_compiled_values as X, source_execution as E, source_text as S
from scar.ir.program import normal_links as F, normal_targets as T, normal_graph as G, source_productions as P
from scar.ir.program.python_bindings import SourceCallSite
from scar.ir.program.providers import ProviderArtifact, ProviderFactReference
from scar.ir.program.source_references import SourceArtifactLocator
from scar.ir.record_codec import _decode, _encode, _record_tags


def _conditions(*groups):
    return tuple(dict.fromkeys(value for group in groups for value in group))


class _References:
    """Unit-local reference constraints; namespace channels are private."""
    def __init__(self, unit):
        self.unit = unit
        self.adj = defaultdict(set)
        self.ports = {}
        tags = _record_tags(P.PRODUCTION_RECORD_TAGS)
        for i, port in enumerate(unit.ports):
            self.ports[i] = T.GlobalPort(unit.unit,
                _decode(G.Port, port, tags) if type(port) is dict else port)
        self.indices = {port:index for index,port in self.ports.items()}
        for a,b in unit.aliases:
            self.adj[a].add(b)
        for access in unit.names:
            ns = access.namespace
            channel = ('namespace', ns.kind, ns.owner, ns.name)
            self.adj[access.value if access.write else channel].add(channel if access.write else access.value)
        self.cache = {}

    def reach(self, point):
        if type(point) is T.GlobalPort:
            point = self.indices[point]
        if point not in self.cache:
            self.cache[point] = source_execution._reach(self.adj, (point,))
        return self.cache[point]

    def site(self, call):
        gp = self.ports.__getitem__
        return SourceCallSite(gp(call.callee),tuple(map(gp,call.positional)),
            tuple((n,gp(p)) for n,p in call.keywords),gp(call.result),gp(call.world),gp(call.result_world),
            None if call.positional_pack is None else gp(call.positional_pack),
            None if call.keyword_pack is None else gp(call.keyword_pack))

    def builtin(self, name):
        modules = set().union(*(self.reach(i.value) for i in self.unit.imports
            if i.module=='builtins'))
        seeds = {a.value for a in self.unit.names if not a.write
            and a.namespace.kind is F.NamespaceKind.BUILTINS and a.namespace.name==name}
        seeds.update(a.value for a in self.unit.attributes if a.receiver in modules
            and a.name==name and a.action in (F.AttributeAction.GET,F.AttributeAction.IMPORT_MEMBER))
        return set().union(*(self.reach(p) for p in seeds))


def filename_candidates(unit, boundary, path_values, references=None):
    refs = _References(unit) if references is None else references
    argument = next(p for p in boundary.parameters if p.name=='filename')
    if argument.source is None:
        return ()
    if argument.literal is not None:
        value = argument.literal.to_python()
        if type(value) is str:
            return (X.CompileFilenameCandidate(boundary.site.result,value,argument.source,
                conditions=boundary.conditions),)
    filenames = {}
    standard_str = refs.builtin('str')
    actual = refs.indices[argument.source]
    for call in unit.calls:
        if (call.callee not in standard_str or len(call.positional)!=1 or call.keywords
                or call.positional_pack is not None or call.keyword_pack is not None
                or actual not in refs.reach(call.result)):
            continue
        for value in path_values:
            if call.positional[0] in refs.reach(value.result):
                item = X.CompileFilenameCandidate(boundary.site.result,value.lexical_path,
                    argument.source,value.result,refs.site(call),_conditions(boundary.conditions,
                    value.conditions,('STANDARD_STR_REFERENCE_AND_PATH_STRING_IMPLEMENTATION_SELECTED',)))
                filenames[item] = None
    return tuple(filenames)


def compile_source_candidates(unit, boundaries, contexts, text_candidates, path_values, entry, raw_loader):
    """Compose conditional values. raw_loader returns retained bytes/root only.

    The loader is a material provider, not a target I/O or code-execution hook.
    Production uses the sealed store below; controlled fixtures can supply F0.
    """
    if (entry.source.runtime.implementation != sys.implementation.name
            or entry.source.runtime.version != tuple(sys.version_info)):
        raise ValueError('compiler runtime differs from the declared source runtime')
    refs = _References(unit)
    requests = {c.invocation_result:c for c in contexts}
    filenames = {};candidates = {};obligations = set();mask = supported_future_flag_mask()
    def oblige(port, reason):
        obligations.add(X.SourceCompileObligation(port,reason))
    for ordinal,boundary in enumerate(boundaries):
        if boundary.builtin is not E.SourceBuiltin.COMPILE:
            continue
        request = requests.get(boundary.site.result)
        if request is None:
            oblige(boundary.site.result,'COMPILE_SIGNATURE_OR_REQUEST_NOT_MODELED');continue
        params = {p.name:p for p in boundary.parameters}
        mode_arg = params['mode'].literal
        mode = None if mode_arg is None else mode_arg.to_python()
        if (request.result_kind!='CODE_OBJECT' or mode not in ('exec','eval','single')
                or request.requested_flags is None or request.dont_inherit is None
                or request.inherited_future_flags is None or request.effective_optimize is None):
            oblige(boundary.site.result,'COMPILE_CONTEXT_FIELD_OR_RESULT_KIND_NOT_SUPPORTED');continue
        choices = filename_candidates(unit,boundary,path_values,refs)
        if not choices:
            oblige(boundary.site.result,'COMPILE_FILENAME_VALUE_NOT_RESOLVED');continue
        for choice in choices:
            filenames[choice] = None
        source = params['source'].source
        matches = [(i,c) for i,c in enumerate(text_candidates)
            if source is not None and refs.indices[source] in refs.reach(c.read_result)]
        if not matches:
            oblige(boundary.site.result,'NO_RETAINED_TEXT_CANDIDATE_REACHES_COMPILE_SOURCE')
        for index,text in matches:
            interpretation = text.interpretation
            if (text.text_utf8_sha256 is None or interpretation.encoding is None
                    or interpretation.errors is None or not interpretation.newline_resolved):
                oblige(boundary.site.result,'SOURCE_TEXT_INTERPRETATION_NOT_RESOLVED');continue
            raw,root = raw_loader(text)
            if len(raw)!=text.raw_bytes or sha256(raw).hexdigest()!=text.raw_sha256:
                raise ValueError('compiled text raw source differs')
            with TextIOWrapper(BytesIO(raw),encoding=interpretation.encoding,
                              errors=interpretation.errors,newline=interpretation.newline) as stream:
                payload = stream.read()
            if sha256(payload.encode('utf-8')).hexdigest()!=text.text_utf8_sha256:
                raise ValueError('compiled text interpretation differs')
            inherited = 0 if request.dont_inherit else request.inherited_future_flags
            flags = request.requested_flags | inherited
            for choice in choices:
                try:
                    code = compile(payload,choice.filename,mode,flags=flags,
                                   dont_inherit=True,optimize=request.effective_optimize)
                except (SyntaxError,ValueError,TypeError,OverflowError):
                    oblige(boundary.site.result,'SELECTED_COMPILER_INPUT_HAS_NO_NORMAL_CODE_RESULT');continue
                if type(code) is not CodeType:
                    oblige(boundary.site.result,'COMPILER_RESULT_IS_NOT_A_CODE_OBJECT');continue
                context = X.EffectiveCompileContext(choice.filename,mode,request.requested_flags,
                    request.dont_inherit,inherited,flags,code.co_flags & mask,code.co_flags,
                    request.effective_optimize,entry.source.runtime)
                digest = source_compilation_contexts.code_digest(code)
                control_digest = None
                if root is not None:
                    # This is an independently compiled control, not an F4
                    # correspondence proof. The old body is never activated.
                    try:
                        control = compile(raw,text.source_path,'exec',flags=0,dont_inherit=True,
                                          optimize=request.effective_optimize)
                        control_digest = source_compilation_contexts.code_digest(control)
                    except (SyntaxError,ValueError,TypeError,OverflowError):
                        pass
                pending = _conditions(text.obligations,('CONTEXT_QUALIFIED_F3_F4_VARIANT_NOT_BUILT',))
                key = dict(compile_result=boundary.site.result,text=text.text_utf8_sha256,
                    read_result=text.read_result,source=text.source,context=context,code_digest=digest)
                identity = sha256(_json(_encode(key,_record_tags(P.PRODUCTION_RECORD_TAGS)))).hexdigest()
                candidates[identity] = X.CompiledSourceCandidate(identity,boundary.site.result,
                    text.read_result,ordinal,index,text.source_unit,text.source,text.text_utf8_sha256,
                    context,digest,root,control_digest,
                    None if control_digest is None else digest==control_digest,
                    _conditions(boundary.conditions,text.conditions,choice.conditions,
                        ('COMPILE_TEXT_FILENAME_AND_CONTEXT_ALTERNATIVES_SELECTED',)),pending)
    return X.CompiledSourceOverlay(unit.unit,tuple(filenames),tuple(candidates.values()),
        tuple(sorted(obligations,key=lambda item:(str(item.port),item.reason))))


def _overlay(path, schema, producer, types_module, rows):
    path = Path(path).absolute();raw = (path/'result.json').read_bytes();report = json.loads(raw)
    if (report['schema'],report['schema_version'])!=(schema,1):
        raise ValueError('source overlay schema differs')
    if (report['implementation_sha256']!=sha256(Path(producer.__file__).read_bytes()).hexdigest()
            or report['types_sha256']!=sha256(Path(types_module.__file__).read_bytes()).hexdigest()):
        raise ValueError('source overlay producer differs')
    tags = _record_tags(P.PRODUCTION_RECORD_TAGS);tables = {}
    for name,kind in rows.items():
        receipt = report['tables'][name];payload = (path/receipt['path']).read_bytes()
        if len(payload)!=receipt['bytes'] or sha256(payload).hexdigest()!=receipt['sha256']:
            raise ValueError('stored overlay table differs')
        decoded = gzip.decompress(payload)
        if (len(decoded)!=receipt['decoded_bytes'] or decoded.count(b'\n')!=receipt['records']
                or sha256(decoded).hexdigest()!=receipt['decoded_sha256']):
            raise ValueError('decoded overlay table differs')
        tables[name] = tuple(_decode(kind,json.loads(line),tags) for line in decoded.splitlines())
    return report,tables,dict(path=str(path),sha256=sha256(raw).hexdigest())


def build_compiled_sources(facts, executions, texts, out):
    out = Path(out).absolute()
    if out.exists():
        raise ValueError('fresh compiled source output required')
    store = SourceFactStore(facts)
    execution, erows, eref = _overlay(executions,'scar.source-builtin-execution',source_execution,E,
        {'boundaries':E.SourceBuiltinInvocation,'compilation-contexts':E.SourceCompilationRequest})
    text, trows, tref = _overlay(texts,'scar.source-text-candidates',source_text_values,S,
        {'path_values':S.SourcePathCandidate,'candidates':S.SourceTextCandidate})
    if (execution['source_facts_sha256']!=sha256(store.raw).hexdigest()
            or text['source_facts_sha256']!=sha256(store.raw).hexdigest()
            or execution['unit']!=text['unit']):
        raise ValueError('compiled source overlay parents differ')
    entry = read_script_entry(text['entry_contract'],store)
    entry_raw = (Path(text['entry_contract'])/'entry.json').read_bytes()
    if (sha256(entry_raw).hexdigest()!=text['entry_sha256']
            or sha256(entry_raw).hexdigest()!=execution['entry_contract']['sha256']):
        raise ValueError('compiler caller contexts differ')
    def raw_loader(candidate):
        descriptor = store.model_units[candidate.source_unit]['artifacts']['source_bytes']
        model = Path(store.model_for(candidate.source_unit))
        manifest = (model/'manifest.json').read_bytes()
        rows = json.loads(manifest)['units']
        ordinal, = [i for i,row in enumerate(rows) if row['key']==candidate.source_unit]
        locator = SourceArtifactLocator(ProviderArtifact(str(model/descriptor['path']),
            descriptor['sha256'],descriptor['bytes'],'scar.source-bytes+gzip-json'),
            descriptor['decoded_sha256'],descriptor['decoded_bytes'],'gzip-canonical-json',
            declaration=ProviderFactReference(ProviderArtifact(str(model/'manifest.json'),
                sha256(manifest).hexdigest(),len(manifest),'scar.static-program'),
                '#/units/'+str(ordinal)+'/artifacts/source_bytes'))
        if locator!=candidate.source:
            raise ValueError('compiled payload artifact or declaration differs')
        f0 = _Fragments(model).read(descriptor)
        if _digest(f0)!=candidate.f0_document_sha256 or f0['path']!=candidate.source_path:
            raise ValueError('compiled source material differs')
        root = store.load(candidate.source_unit).root_scope if candidate.source_unit in store.rows else None
        return read_source_bytes(f0),root
    overlay = compile_source_candidates(store.load(execution['unit']),erows['boundaries'],
        erows['compilation-contexts'],trows['candidates'],trows['path_values'],entry,raw_loader)
    _durable_mkdir(out)
    tables = {name:write_table(out/(name+'.jsonl.gz'),getattr(overlay,name))
        for name in ('filenames','candidates','obligations')}
    report = dict(schema='scar.source-compiled-values',schema_version=1,
        status='CONDITIONAL_COMPILER_INPUTS_AND_CODE_VALUES',source_facts=str(store.path),
        source_facts_sha256=sha256(store.raw).hexdigest(),unit=overlay.unit,
        source_execution=eref,source_text=tref,tables=tables,
        target_executed=False,source_body_activated=False,f4_variant_built=False,
        first_stage_complete=False,runtime=sys.version,
        implementation_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),
        types_sha256=sha256(Path(X.__file__).read_bytes()).hexdigest(),
        compiler_digest_sha256=sha256(Path(source_compilation_contexts.__file__).read_bytes()).hexdigest())
    _durable_bytes(out/'result.json',_json(report),replace=False)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('facts','executions','texts','out'):
        parser.add_argument('--'+name,required=True)
    args = parser.parse_args()
    print(json.dumps(build_compiled_sources(args.facts,args.executions,args.texts,args.out)),flush=True)


if __name__=='__main__':
    main()
