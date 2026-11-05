"""C2a then C2b using one verified effective compiler-context policy.

No source-prefix rescanning, caller-global mutation, old-store replacement or
native-symbol grant occurs here. Original source ports and scopes stay in
their context namespace; capture/lookup relations remain typed templates.
"""
import argparse
import __future__
from dataclasses import replace
from hashlib import sha256
from io import BytesIO, TextIOWrapper
import json
from pathlib import Path

from scar.analysis import source_context_variants as C, source_declarations as D, source_bindings as B
from scar.analysis import source_declaration_view, source_binding_view, source_text_values, source_compiled_values
from scar.analysis.normal_facts import SourceFactStore
from scar.analysis.static_query import _Fragments
from scar.analysis.source_bytes import read_source_bytes
from scar.analysis.source_stage import _durable_bytes, _durable_mkdir
from scar.analysis.source_template_links import _json
from scar.analysis.source_contexts import _digest
from scar.ir.program import source_binding_variants as V, source_context_variants as CV, source_text as S
from scar.ir.program.source_syntax import SourceSyntaxMaterial
from scar.ir.program.source_roles import SourceRolesMaterial
from scar.ir.program.source_declarations import SourceDeclarationsInput, SourceDeclarationsMaterial
from scar.ir.program.source_bindings import SourceBindingsInput, SourceBindingsMaterial
from scar.ir.record_codec import decode, encode


def pins():
    return {name:sha256(Path(module.__file__).read_bytes()).hexdigest() for name,module in (
        ('context_variant',C),('context_variant_types',CV),('declarations',D),('bindings',B),
        ('declaration_view',source_declaration_view),('binding_view',source_binding_view),('types',V))}


class _EffectiveFuture:
    def _future_annotations(self):
        return bool(self.effective_future_flags & __future__.annotations.compiler_flag)


class _ContextLedger(_EffectiveFuture,D._Ledger):
    def __init__(self,syntax,roles,contexts,limits,flags):
        self.effective_future_flags = flags
        super().__init__(syntax,roles,contexts,limits)


class _ContextResolver(_EffectiveFuture,B._Resolver):
    def __init__(self,syntax,roles,contexts,declarations,limits,flags):
        self.effective_future_flags = flags
        super().__init__(syntax,roles,contexts,declarations,limits)


def binding_variant_document(f0,f1,f2,f3b,context_variant,payload,*,
        declaration_limits=(1000000,1000000,100000),
        binding_limits=(1000000,1000000,1000000,4000000,2000000,2000000,10000000,100000)):
    context = C.read_context_variant(context_variant,f0,f1,f2,f3b,payload)
    syntax,roles = decode(SourceSyntaxMaterial,f2),decode(SourceRolesMaterial,f3b)
    contexts = context.material;c1 = encode(contexts);digest = _digest
    flags = context.context.compiled_future_flags
    if (len(declaration_limits)!=3 or len(binding_limits)!=8
            or any(type(n) is not int or n<0 for n in (*declaration_limits,*binding_limits))):
        raise ValueError('invalid variant declaration/binding limits')
    implementation = digest(dict(pins=pins(),namespace=context.namespace,
        producer=sha256(Path(__file__).read_bytes()).hexdigest()))
    ledger = _ContextLedger(syntax,roles,contexts,declaration_limits,flags)
    scopes = ledger.run()
    declared = SourceDeclarationsMaterial(
        SourceDeclarationsInput(*(digest(doc) for doc in (f0,f1,f2,f3b,c1)),
            f0['path'],syntax.mode,contexts.status,len(roles.ports)),
        replace(D._profile(),rule_version='PYTHON_SOURCE_DECLARATION_COMPILE_VARIANT_V1',
            implementation_sha256=implementation),*declaration_limits,'DECLARED',
        tuple(ledger.names),tuple(ledger.ports),tuple(ledger.contributions),scopes,tuple(ledger.conflicts),())
    source_declaration_view.SourceDeclarationView(roles,contexts,declared,contexts=ledger.view).verify()
    resolver = _ContextResolver(syntax,roles,contexts,declared,binding_limits,flags)
    scope_bindings = resolver.run()
    resolved = SourceBindingsMaterial(
        SourceBindingsInput(*(digest(doc) for doc in (f0,f1,f2,f3b,c1,encode(declared))),
            f0['path'],syntax.mode,declared.status,len(roles.ports),len(contexts.scopes)),
        replace(B._profile(),rule_version='PYTHON_SOURCE_BINDING_COMPILE_VARIANT_V1',
            implementation_sha256=implementation),*binding_limits,
        'RESOLVED_WITH_CONFLICTS' if resolver.conflicts else 'RESOLVED',
        tuple(resolver.bindings),tuple(resolver.interfaces),tuple(resolver.plans),tuple(resolver.ports),
        tuple(resolver.resolutions),scope_bindings,tuple(resolver.captures),tuple(resolver.relays),
        tuple(resolver.root_globals),tuple(resolver.implicit),tuple(resolver.conflicts),(),resolver.search_steps)
    source_binding_view.SourceBindingView(roles,contexts,declared,resolved,contexts=resolver.view).verify()
    return encode(V.SourceBindingVariant(context.namespace,digest(c1),declared,resolved))


def read_binding_variant(document,f0,f1,f2,f3b,context_variant,payload):
    variant = decode(V.SourceBindingVariant,document)
    d,b = variant.declarations,variant.bindings
    fresh = binding_variant_document(f0,f1,f2,f3b,context_variant,payload,
        declaration_limits=(d.max_names,d.max_contributions,d.max_conflicts),
        binding_limits=(b.max_bindings,b.max_interfaces,b.max_plans,b.max_plan_steps,
            b.max_captures,b.max_relays,b.max_search_steps,b.max_conflicts))
    if document!=fresh:
        raise ValueError('binding variant differs from its effective context and source rules')
    return variant


def build_binding_variants(facts,contexts,out):
    out = Path(out).absolute()
    if out.exists():
        raise ValueError('fresh binding variant output required')
    root = Path(contexts).absolute();raw_report = (root/'result.json').read_bytes()
    report = json.loads(raw_report)
    if ((report['schema'],report['schema_version'])!=('scar.source-context-variants',1)
            or report['implementation_sha256']!=sha256(Path(C.__file__).read_bytes()).hexdigest()
            or report['pins']!=C.pins()):
        raise ValueError('context variant producer differs')
    store = SourceFactStore(facts)
    if report['source_facts_sha256']!=sha256(store.raw).hexdigest():
        raise ValueError('context variant source facts differ')
    code_root = Path(report['compiled_sources']['path']);code_raw = (code_root/'result.json').read_bytes()
    if sha256(code_raw).hexdigest()!=report['compiled_sources']['sha256']:
        raise ValueError('compiled context parent differs')
    code_report = json.loads(code_raw)
    _,texts,text_parent = source_compiled_values._overlay(code_report['source_text']['path'],
        'scar.source-text-candidates',source_text_values,S,{'candidates':S.SourceTextCandidate})
    if text_parent!=code_report['source_text']:
        raise ValueError('binding variant text parent differs')
    _durable_mkdir(out);variants = {}
    for namespace,descriptor in report['variants'].items():
        raw = (root/descriptor['path']).read_bytes()
        if len(raw)!=descriptor['bytes'] or sha256(raw).hexdigest()!=descriptor['sha256']:
            raise ValueError('context variant material differs')
        document = json.loads(raw);context = decode(CV.SourceContextVariant,document)
        if context.namespace!=namespace:
            raise ValueError('context namespace differs')
        text = next(t for t in texts['candidates'] if t.source_unit==context.source_unit
            and t.text_utf8_sha256==context.text_utf8_sha256)
        unit = store.model_units[context.source_unit];reader = _Fragments(store.model_for(context.source_unit))
        f0,f1,f2,f3b = (reader.read(unit['artifacts'][name]) for name in
            ('source_bytes','source_tokens','source_syntax','source_roles'))
        with TextIOWrapper(BytesIO(read_source_bytes(f0)),encoding=text.interpretation.encoding,
                errors=text.interpretation.errors,newline=text.interpretation.newline) as stream:
            payload = stream.read()
        result = binding_variant_document(f0,f1,f2,f3b,document,payload)
        typed = decode(V.SourceBindingVariant,result)
        data = _json(result);name = namespace+'.json';_durable_bytes(out/name,data,replace=False)
        variants[namespace] = dict(path=name,bytes=len(data),sha256=sha256(data).hexdigest(),
            declarations_sha256=_digest(encode(typed.declarations)),
            bindings_sha256=_digest(encode(typed.bindings)),
            ports=len(typed.bindings.ports),scopes=len(typed.bindings.scopes),
            bindings=len(typed.bindings.bindings),plans=len(typed.bindings.plans),
            captures=len(typed.bindings.captures),relays=len(typed.bindings.relays),
            declaration_conflicts=len(typed.declarations.conflicts),binding_conflicts=len(typed.bindings.conflicts),
            detached_annotations=sum(p.analysis_visibility=='DETACHED_FUTURE_ANNOTATION'
                for p in typed.bindings.ports))
    result = dict(schema='scar.source-binding-variants',schema_version=1,
        status='C2_COMPILE_CONTEXT_VARIANTS',source_facts=str(store.path),
        source_facts_sha256=sha256(store.raw).hexdigest(),
        context_variants=dict(path=str(root),sha256=sha256(raw_report).hexdigest()),variants=variants,
        target_executed=False,native_symbols_captured=False,f4_variant_built=False,first_stage_complete=False,
        implementation_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),pins=pins())
    _durable_bytes(out/'result.json',_json(result),replace=False)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('facts','contexts','out'):
        parser.add_argument('--'+name,required=True)
    args = parser.parse_args()
    print(json.dumps(build_binding_variants(args.facts,args.contexts,args.out)),flush=True)


if __name__=='__main__':
    main()
