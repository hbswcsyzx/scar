"""Capture official symbols(flags) for shared C1 compiler-context variants.

Only retained text is sent to the isolated native compiler. This overlay does
not join native scopes to AST occurrences, bind declarations, or build F4.
"""
import argparse
from dataclasses import replace
from hashlib import sha256
from io import BytesIO, TextIOWrapper
import gzip
import json
import os
from pathlib import Path
import subprocess
import sys
import warnings

ROOT = Path(__file__).resolve().parents[2]
if __name__=='__main__':
    sys.path.insert(0,str(ROOT))

from scar.analysis import source_context_variants as contexts, source_symbols as symbols
from scar.analysis import source_compiled_values as compiled, source_text_values
from scar.analysis import source_symbol_context_adapter as adapter_module
from scar.analysis.normal_facts import SourceFactStore
from scar.analysis.normal_output import write_table
from scar.analysis.source_bytes import read_source_bytes
from scar.analysis.source_stage import _durable_bytes, _durable_mkdir
from scar.analysis.source_template_links import _json
from scar.analysis.static_query import _Fragments
from scar.ir.program import source_symbol_variants as V, source_context_variants as C
from scar.ir.program import source_compiled_values as X, source_text as S
from scar.ir.program.source_symbols import SourceSymbolsInput, SourceSymbolsMaterial, SourceSymbolsProfile
from scar.ir.program.source_tokens import SourceTokenWarning
from scar.ir.record_codec import decode, encode


API = '_scar_symtable_context.symtable_flags(str, filename, mode, explicit_flags)'


def pins():
    return {name:sha256(Path(module.__file__).read_bytes()).hexdigest() for name,module in (
        ('types',V),('contexts',contexts),('context_types',C),('symbols',symbols),
        ('compiler_values',compiled),('text_values',source_text_values),('adapter',adapter_module))}


def _native_profile(native):
    from scar.analysis.source_bytes import _profile
    profile = symbols._profile({'profile':encode(_profile())})
    origin = native.__spec__.origin
    binary = profile.native_binary if origin=='built-in' else str(Path(origin).resolve())
    return replace(profile,api=API,native_origin=origin,native_binary=binary,
        native_sha256=sha256(Path(binary).read_bytes()).hexdigest(),
        source_view_policy='EXACT_RETAINED_TEXT_OPEN_UNICODE_PAYLOAD_NO_F1_NORMALIZATION',
        caller_future_policy='EXPLICIT_RECORDED_COMPILER_INPUT_FLAGS_NO_AMBIENT_INHERITANCE',
        source_future_policy='OFFICIAL_SOURCE_FUTURE_OR_EXPLICIT_FLAGS',
        f2_relation='C1_AST_TREE_EQUALITY_IS_SEPARATE_FROM_UNJOINED_NATIVE_SCOPES')


def _native_worker(native_path):
    if native_path is None:
        import _scar_symtable_context as native
    else:
        native = adapter_module._native_module(native_path)
    print(json.dumps(dict(profile=encode(_native_profile(native)),probe=native.probe())),flush=True)
    for line in sys.stdin:
        try:
            request = json.loads(line)
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter('always')
                raw = native.symtable_flags(request['text'],request['filename'],request['mode'],request['effective_flags'])
                scopes = symbols.capture_raw_view(raw,max_scopes=request['max_scopes'],max_symbols=request['max_symbols'])
            warning_rows = tuple(SourceTokenWarning(w.category.__module__,w.category.__qualname__,
                str(w.message),w.filename,w.lineno,w.line,w.source is not None) for w in caught)
            response = dict(scopes=encode(scopes),warnings=encode(warning_rows))
        except Exception as error:
            response = dict(error=dict(type=type(error).__name__,message=str(error)))
        print(json.dumps(response),flush=True)


class SymbolVariantWorker:
    """Full observer profile and warnings beside the frozen adapter's native ABI."""
    def __init__(self,directory=adapter_module.DEFAULT):
        # Reuse all frozen build/runtime/native/normalizer receipt checks.
        with adapter_module.SymbolContextAdapter(directory) as checked:
            self.parent = checked.parent
            receipt = checked.receipt
            catalog = checked.profile
        helper = receipt['helper']
        binary = receipt['runtime']['executable'] if helper is None else helper['executable']
        command = [binary['path'],'-P','-S','-B',str(Path(__file__).resolve()),'--native-worker']
        if helper is None:
            command += ['--native-path',receipt['native']['path']]
        environment = {k:v for k,v in os.environ.items() if not k.startswith('PYTHON')}
        environment['PYTHONHASHSEED'] = '0'
        self.process = subprocess.Popen(command,stdin=subprocess.PIPE,stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,text=True,env=environment)
        line = self.process.stdout.readline()
        if not line:
            raise RuntimeError('symbol observer worker did not start: '+self.process.stderr.read())
        ready = json.loads(line)
        self.profile = decode(SourceSymbolsProfile,ready['profile'])
        self.probe = ready['probe']
        native_binary = binary if helper is not None else receipt['native']
        if (not self.probe['builder'] or not self.probe['free']
                or self.profile.native_sha256 != native_binary['sha256']
                or self.profile.api != API
                or {c.name:c.value for c in self.profile.constants} != catalog['constants']
                or [m.name for m in self.profile.raw_members] != catalog['raw_members']
                or list(self.profile.runtime.version) != catalog['version']
                or helper is not None and self.profile.hash_context_sha256 != catalog['compiler_hash_context']):
            self.close();raise ValueError('symbol observer runtime/API/native schema differs')
        self.command = command

    def capture(self,payload,context,max_scopes,max_symbols):
        from scar.ir.program.source_symbols import SourceScope
        request = dict(text=payload,filename=context.filename,mode=context.mode,
            effective_flags=context.compiler_input_flags,max_scopes=max_scopes,max_symbols=max_symbols)
        self.process.stdin.write(json.dumps(request)+'\n');self.process.stdin.flush()
        response = json.loads(self.process.stdout.readline())
        if 'error' in response:
            raise ValueError('official context symbol capture failed: '+json.dumps(response['error']))
        return (decode(tuple[SourceScope,...],response['scopes']),
                decode(tuple[SourceTokenWarning,...],response['warnings']))

    def close(self):
        self.process.stdin.close();self.process.wait(timeout=10)
        self.process.stdout.close();self.process.stderr.close()

    def __enter__(self):
        return self

    def __exit__(self,*args):
        self.close()


def symbol_variant_document(context_document,f0,f1,f2,f3b,payload,text_inputs,worker,*,parents,
                            context_document_sha256=None,max_scopes=100000,max_symbols=1000000):
    if any(type(n) is not int or n<0 for n in (max_scopes,max_symbols)):
        raise ValueError('exact nonnegative native scope/symbol budgets required')
    context = contexts.read_context_variant(context_document,f0,f1,f2,f3b,payload)
    if (worker.profile.runtime.implementation != context.context.runtime.implementation
            or worker.profile.runtime.version != context.context.runtime.version):
        raise ValueError('symbol worker and C1 language/runtime versions differ')
    text_inputs = tuple(dict.fromkeys(text_inputs))
    if not text_inputs:
        raise ValueError('retained source text provenance required')
    raw = read_source_bytes(f0)
    if (tuple(p.name for p in parents)!=('source_bytes','source_tokens','source_syntax','source_roles')
            or tuple(p.document_sha256 for p in parents)!=tuple(symbols._digest(d) for d in (f0,f1,f2,f3b))):
        raise ValueError('symbol original F0/F1/F2/role parent references differ')
    for text in text_inputs:
        interp = text.interpretation
        if (text.source != parents[0].source or text.f0_document_sha256 != symbols._digest(f0)
                or text.raw_sha256 != sha256(raw).hexdigest() or text.raw_bytes != len(raw)
                or text.text_utf8_sha256 != context.text_utf8_sha256 or text.characters != len(payload)
                or interp.encoding is None or interp.errors is None or not interp.newline_resolved):
            raise ValueError('symbol text input differs from retained F0/C1 input')
        with TextIOWrapper(BytesIO(raw),encoding=interp.encoding,errors=interp.errors,newline=interp.newline) as stream:
            if stream.read() != payload:
                raise ValueError('symbol text interpretation differs from C1 payload')
    scopes,warning_rows = worker.capture(payload,context.context,max_scopes,max_symbols)
    symbols._validate_graph(scopes)
    source_inputs = SourceSymbolsInput(symbols._digest(f0),symbols._digest(f1),symbols._digest(f2),
        f0['path'],f2['input']['view_sha256'],f2['status'])
    material = SourceSymbolsMaterial(source_inputs,worker.profile,context.context.mode,max_scopes,max_symbols,
        'CAPTURED',0,scopes,symbols._interpretation_frontiers(scopes,worker.profile),None,warning_rows)
    ctx = context.context
    request = V.SymbolContextRequest(context.text_utf8_sha256,len(payload),ctx.filename,ctx.mode,
        ctx.requested_flags,ctx.caller_dont_inherit,ctx.inherited_future_flags,ctx.compiler_input_flags)
    return encode(V.SourceSymbolVariant(context.namespace,context.source_unit,
        context_document_sha256 or sha256(_json(context_document)).hexdigest(),
        symbols._digest(encode(context.material)),ctx,tuple(parents),text_inputs,request,
        V.SymbolAdapterReceipt(**worker.parent),material))


def read_symbol_variant(document,context_document,f0,f1,f2,f3b,payload,worker,*,parents,context_document_sha256=None):
    variant = decode(V.SourceSymbolVariant,document)
    fresh = symbol_variant_document(context_document,f0,f1,f2,f3b,payload,variant.text_inputs,worker,
        parents=parents,
        context_document_sha256=context_document_sha256,
        max_scopes=variant.material.max_scopes,max_symbols=variant.material.max_symbols)
    if document != fresh:
        raise ValueError('symbol variant differs from its retained context/native view')
    return variant


def _table(path,receipt):
    raw = (path/receipt['path']).read_bytes()
    if len(raw)!=receipt['bytes'] or sha256(raw).hexdigest()!=receipt['sha256']:
        raise ValueError('stored context binding table differs')
    decoded = gzip.decompress(raw)
    if (len(decoded)!=receipt['decoded_bytes'] or decoded.count(b'\n')!=receipt['records']
            or sha256(decoded).hexdigest()!=receipt['decoded_sha256']):
        raise ValueError('decoded context binding table differs')
    return tuple(json.loads(line) for line in decoded.splitlines())


def _source_parents(store,identity):
    from scar.ir.program.providers import ProviderArtifact, ProviderFactReference
    from scar.ir.program.source_references import SourceArtifactLocator
    model = Path(store.model_for(identity));manifest = (model/'manifest.json').read_bytes()
    ordinal, = [i for i,row in enumerate(json.loads(manifest)['units']) if row['key']==identity]
    unit = store.model_units[identity];reader = _Fragments(model);parents = [];materials = []
    for name in ('source_bytes','source_tokens','source_syntax','source_roles'):
        descriptor = unit['artifacts'][name];document = reader.read(descriptor)
        declaration = ProviderFactReference(ProviderArtifact(str(model/'manifest.json'),sha256(manifest).hexdigest(),
            len(manifest),'scar.static-program'),'#/units/'+str(ordinal)+'/artifacts/'+name)
        locator = SourceArtifactLocator(ProviderArtifact(str(model/descriptor['path']),descriptor['sha256'],
            descriptor['bytes'],'scar.'+name.replace('_','-')+'+gzip-json'),descriptor['decoded_sha256'],
            descriptor['decoded_bytes'],'gzip-canonical-json',declaration=declaration)
        parents.append(V.SymbolSourceParent(name,locator,symbols._digest(document)));materials.append(document)
    return tuple(materials),tuple(parents),(model/'manifest.json',manifest)


def build_symbol_variants(facts,context_variants,out,*,adapter_directory=adapter_module.DEFAULT):
    out = Path(out).absolute()
    if out.exists():
        raise ValueError('fresh symbol variant output required')
    store = SourceFactStore(facts)
    path = Path(context_variants).absolute();report_raw = (path/'result.json').read_bytes();report = json.loads(report_raw)
    if ((report['schema'],report['schema_version'])!=('scar.source-context-variants',1)
            or report['implementation_sha256']!=sha256(Path(contexts.__file__).read_bytes()).hexdigest()
            or report['pins']!=contexts.pins() or report['source_facts_sha256']!=sha256(store.raw).hexdigest()):
        raise ValueError('C1 context parent implementation/source store differs')
    creport,crows,cparent = compiled._overlay(report['compiled_sources']['path'],'scar.source-compiled-values',
        compiled,X,{'candidates':X.CompiledSourceCandidate})
    treport,trows,tparent = compiled._overlay(creport['source_text']['path'],'scar.source-text-candidates',
        source_text_values,S,{'candidates':S.SourceTextCandidate})
    if (cparent!=report['compiled_sources'] or tparent!=creport['source_text']
            or any(r['source_facts_sha256']!=sha256(store.raw).hexdigest() for r in (creport,treport))):
        raise ValueError('compiler/text parent chain differs from C1 source store')
    candidates = {c.id:c for c in crows['candidates']}
    groups = {};bindings = _table(path,report['bindings'])
    for binding in bindings:
        candidate = candidates[binding['compile_candidate']]
        from scar.ir.program import source_productions as P
        if (binding['compile_result']!=encode(candidate.compile_result,record_tags=P.PRODUCTION_RECORD_TAGS)
                or binding['conditions']!=list(candidate.conditions) or binding['obligations']!=list(candidate.obligations)):
            raise ValueError('C1 call binding differs from retained compiler candidate')
        text = trows['candidates'][candidate.text_candidate_ordinal]
        if (text.source_unit!=candidate.source_unit or text.source!=candidate.source
                or text.read_result!=candidate.read_result or text.text_utf8_sha256!=candidate.text_utf8_sha256):
            raise ValueError('symbol compiler/text selection differs')
        namespace = binding['variant'];descriptor = report['variants'][namespace]
        item = groups.get(namespace)
        if item is None:
            data = (path/descriptor['path']).read_bytes()
            if len(data)!=descriptor['bytes'] or sha256(data).hexdigest()!=descriptor['sha256']:
                raise ValueError('C1 variant bytes differ')
            document = json.loads(data);context = decode(C.SourceContextVariant,document)
            if (context.namespace!=namespace or context.source_unit!=descriptor['source_unit']
                    or symbols._digest(encode(context.material))!=descriptor['material_sha256']
                    or symbols._digest(encode(context.context))!=descriptor['context_sha256']):
                raise ValueError('C1 variant descriptor differs')
            materials,parents,manifest = _source_parents(store,context.source_unit)
            raw = read_source_bytes(materials[0]);interp = text.interpretation
            with TextIOWrapper(BytesIO(raw),encoding=interp.encoding,errors=interp.errors,newline=interp.newline) as stream:
                payload = stream.read()
            item = groups[namespace] = dict(context=context,document=document,descriptor=descriptor,
                materials=materials,parents=parents,manifest=manifest,payload=payload,texts=[])
        if (candidate.context!=item['context'].context or candidate.source_unit!=item['context'].source_unit
                or candidate.code_digest!=item['context'].code_digest
                or candidate.text_utf8_sha256!=item['context'].text_utf8_sha256):
            raise ValueError('compiler candidate differs from bound C1 namespace')
        item['texts'].append(V.SymbolTextInput(text.source,text.f0_document_sha256,text.raw_sha256,
            text.raw_bytes,text.interpretation,text.text_utf8_sha256,text.characters,text.conditions,text.obligations))
    if set(groups)!=set(report['variants']):
        raise ValueError('C1 context binding coverage differs')
    _durable_mkdir(out);variants = {}
    with SymbolVariantWorker(adapter_directory) as worker:
        for namespace,item in groups.items():
            document = symbol_variant_document(item['document'],*item['materials'],item['payload'],item['texts'],worker,
                parents=item['parents'],context_document_sha256=item['descriptor']['sha256'])
            value = decode(V.SourceSymbolVariant,document);data = _json(document);name = namespace+'.json'
            _durable_bytes(out/name,data,replace=False)
            variants[namespace] = dict(path=name,bytes=len(data),sha256=sha256(data).hexdigest(),
                source_unit=value.source_unit,context_material_sha256=value.context_material_sha256,
                material_sha256=symbols._digest(encode(value.material)),scopes=len(value.material.scopes),
                symbols=sum(len(s.symbols) for s in value.material.scopes),text_inputs=len(value.text_inputs))
        links = write_table(out/'compile-symbol-bindings.jsonl.gz',bindings)
        result = dict(schema='scar.source-symbol-variants',schema_version=1,status='CONTEXT_NATIVE_SYMBOL_VIEWS_CAPTURED',
            source_facts=str(store.path),source_facts_sha256=sha256(store.raw).hexdigest(),
            context_variants=dict(path=str(path),sha256=sha256(report_raw).hexdigest()),
            compiled_sources=cparent,source_text=tparent,adapter=worker.parent,
            worker_command=worker.command,worker_probe=worker.probe,worker_profile=encode(worker.profile),
            variants=variants,bindings=links,native_symbols_captured=True,ast_join='UNJOINED',
            f4_variant_built=False,source_body_activated=False,target_executed=False,first_stage_complete=False,
            implementation_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),pins=pins())
    if ((store.path/'result.json').read_bytes()!=store.raw or (path/'result.json').read_bytes()!=report_raw
            or any(item['manifest'][0].read_bytes()!=item['manifest'][1] for item in groups.values())):
        raise ValueError('source/C1 input snapshots changed during symbol capture')
    _durable_bytes(out/'result.json',_json(result),replace=False)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--native-worker',action='store_true');parser.add_argument('--native-path')
    parser.add_argument('--adapter-directory',default=str(adapter_module.DEFAULT))
    for name in ('facts','context-variants','out'):
        parser.add_argument('--'+name)
    args = parser.parse_args()
    if args.native_worker:
        _native_worker(args.native_path)
    else:
        print(json.dumps(build_symbol_variants(args.facts,args.context_variants,args.out,
            adapter_directory=args.adapter_directory)),flush=True)


if __name__=='__main__':
    main()
