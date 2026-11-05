"""C1 under explicit effective compile context; original syntax IDs survive.

The original source-only C1 store remains immutable. A new profile and
namespace bind each derived context to the compiler inputs. Call witnesses
are kept outside the shared material, so repeated calls do not clone bodies.
"""
import argparse
import ast
import __future__
from dataclasses import replace
from hashlib import sha256
from io import BytesIO, TextIOWrapper
import json
from pathlib import Path
import sys

from scar.analysis import source_contexts as C, source_context_view, source_roles, source_syntax
from scar.analysis import source_compiled_values as compiled, source_text_values, source_compilation_contexts
from scar.analysis.normal_facts import SourceFactStore
from scar.analysis.normal_output import write_table
from scar.analysis.source_bytes import read_source_bytes
from scar.analysis.call_compilation import supported_future_flag_mask
from scar.analysis.source_stage import _durable_bytes, _durable_mkdir
from scar.analysis.source_template_links import _json
from scar.analysis.static_query import _Fragments
from scar.ir.program import source_context_variants as V, source_compiled_values as X, source_text as S
from scar.ir.program.source_syntax import SourceSyntaxMaterial
from scar.ir.program.source_contexts import SourceContextsInput, SourceContextsMaterial
from scar.ir.record_codec import decode, encode


def pins():
    return {name:sha256(Path(module.__file__).read_bytes()).hexdigest() for name,module in (
        ('contexts',C),('view',source_context_view),('roles',source_roles),
        ('syntax',source_syntax),('compiler_values',compiled),
        ('compiler_digest',source_compilation_contexts),('types',V),('context_types',X))}


class _ContextRouter(C._Router):
    def __init__(self, syntax, roles, limits, effective_future_flags):
        self.effective_future_flags = effective_future_flags
        super().__init__(syntax,roles,limits)

    def _future_annotations(self):
        return bool(self.effective_future_flags & __future__.annotations.compiler_flag)


def context_variant_document(source_unit, f0, f1, f2, f3b, context, payload, *,
                             max_scopes=100000, max_regions=200000,
                             max_boundaries=1000000, max_slots=10000000):
    """Derive a new C1 only after exact F2 tree correspondence is established.

    Text-open and source-file decoding can differ. Reusing their AST is
    conditional on equal constructor, field, literal and position trees, not
    on equal path, raw bytes or a superficial module-code comparison.
    """
    if type(context) is not X.EffectiveCompileContext or type(payload) is not str:
        raise TypeError('explicit compiler context and interpreted source text required')
    if (context.runtime.implementation!=sys.implementation.name
            or context.runtime.version!=tuple(sys.version_info)):
        raise ValueError('context variant compiler runtime differs')
    inherited = 0 if context.caller_dont_inherit else context.inherited_future_flags
    if ((context.caller_dont_inherit and context.inherited_future_flags!=0)
            or context.compiler_input_flags != context.requested_flags | inherited):
        raise ValueError('compiler requested and inherited flags are inconsistent')
    if context.compiled_future_flags != context.compiled_code_flags & supported_future_flag_mask():
        raise ValueError('compiled future flags are inconsistent with code flags')
    if context.compiled_code_flags & ~context.compiled_future_flags:
        raise ValueError('C1 root activation for non-module code flags is not implemented')
    limits = max_scopes,max_regions,max_boundaries,max_slots
    C._limits(limits)
    roles = source_roles.read_source_roles(f3b,f0,f1,f2)
    syntax = decode(SourceSyntaxMaterial,f2)
    if roles.status!='CLASSIFIED' or syntax.status!='PARSED':
        raise ValueError('context variant requires parsed and classified source')
    if context.mode!=syntax.mode:
        raise ValueError('compiler mode requires a new F2 variant before C1')
    restored = source_syntax._restore_ast(syntax.root,syntax.nodes)
    parsed = compile(payload,context.filename,context.mode,
        flags=context.compiler_input_flags | syntax.profile.flags,
        dont_inherit=True,optimize=syntax.profile.optimize,
        _feature_version=syntax.profile.feature_version)
    original_tree = ast.dump(restored,include_attributes=True)
    if not isinstance(parsed,ast.AST) or ast.dump(parsed,include_attributes=True)!=original_tree:
        raise ValueError('compiler text/context needs a new F2 occurrence variant')
    code = compile(payload,context.filename,context.mode,flags=context.compiler_input_flags,
                   dont_inherit=True,optimize=context.optimize)
    if (code.co_flags!=context.compiled_code_flags
            or code.co_flags & supported_future_flag_mask()!=context.compiled_future_flags):
        raise ValueError('compiled code flags differ from their retained context')
    digest = source_compilation_contexts.code_digest(code)
    text_sha = sha256(payload.encode('utf-8')).hexdigest()
    inputs = SourceContextsInput(C._digest(f0),C._digest(f1),C._digest(f2),C._digest(f3b),
        f0['path'],syntax.mode,syntax.status,roles.status)
    key = C._digest(dict(source_unit=source_unit,parents=encode(inputs),context=encode(context),
        text_utf8_sha256=text_sha,code_digest=digest))
    profile = replace(C._profile(),rule_version='PYTHON_SOURCE_CONTEXT_COMPILE_VARIANT_V1',
        implementation_sha256=C._digest(dict(base=pins(),variant_producer=sha256(Path(__file__).read_bytes()).hexdigest(),
            namespace=key)))
    router = _ContextRouter(syntax,roles,limits,context.compiled_future_flags)
    root,counts = router.run()
    material = SourceContextsMaterial(inputs,profile,*limits,'CONTEXTUALIZED',root,
        tuple(router.scopes),tuple(router.regions),tuple(router.privates),
        tuple(router.boundaries),counts,router.slots,())
    source_context_view.SourceContextView(syntax,roles,material).verify_totality()
    return encode(V.SourceContextVariant(key,source_unit,context,text_sha,digest,
        sha256(original_tree.encode('utf-8')).hexdigest(),material))


def read_context_variant(document,f0,f1,f2,f3b,payload):
    variant = decode(V.SourceContextVariant,document)
    m = variant.material
    fresh = context_variant_document(variant.source_unit,f0,f1,f2,f3b,variant.context,payload,
        max_scopes=m.max_scopes,max_regions=m.max_regions,
        max_boundaries=m.max_boundaries,max_slots=m.max_slots)
    if document!=fresh:
        raise ValueError('context variant differs from its source/context rules')
    return variant


def build_context_variants(facts, compiled_sources, out):
    out = Path(out).absolute()
    if out.exists():
        raise ValueError('fresh context variant output required')
    store = SourceFactStore(facts)
    report, rows, parent = compiled._overlay(compiled_sources,'scar.source-compiled-values',compiled,X,
        {'candidates':X.CompiledSourceCandidate})
    if report['source_facts_sha256']!=sha256(store.raw).hexdigest():
        raise ValueError('compiler candidates belong to another source store')
    if report['compiler_digest_sha256']!=sha256(Path(source_compilation_contexts.__file__).read_bytes()).hexdigest():
        raise ValueError('compiler code-value digest implementation differs')
    text_report,text_rows,text_parent = compiled._overlay(report['source_text']['path'],
        'scar.source-text-candidates',source_text_values,S,{'candidates':S.SourceTextCandidate})
    if text_parent!=report['source_text'] or text_report['source_facts_sha256']!=sha256(store.raw).hexdigest():
        raise ValueError('compiler source-text parent differs')
    _durable_mkdir(out)
    variants = {};bindings = []
    for candidate in rows['candidates']:
        text = text_rows['candidates'][candidate.text_candidate_ordinal]
        if (text.source_unit!=candidate.source_unit or text.source!=candidate.source
                or text.read_result!=candidate.read_result or text.text_utf8_sha256!=candidate.text_utf8_sha256):
            raise ValueError('compiled source text selection differs')
        unit = store.model_units[candidate.source_unit]
        model = Path(store.model_for(candidate.source_unit));reader = _Fragments(model)
        materials = {name:reader.read(unit['artifacts'][name]) for name in
            ('source_bytes','source_tokens','source_syntax','source_roles')}
        f0,f1,f2,f3b = (materials[n] for n in ('source_bytes','source_tokens','source_syntax','source_roles'))
        if C._digest(f0)!=text.f0_document_sha256:
            raise ValueError('context variant source F0 document differs')
        raw = read_source_bytes(f0)
        if sha256(raw).hexdigest()!=text.raw_sha256 or len(raw)!=text.raw_bytes:
            raise ValueError('context variant source raw bytes differ')
        interp = text.interpretation
        with TextIOWrapper(BytesIO(raw),encoding=interp.encoding,errors=interp.errors,newline=interp.newline) as stream:
            payload = stream.read()
        document = context_variant_document(candidate.source_unit,f0,f1,f2,f3b,candidate.context,payload)
        variant = decode(V.SourceContextVariant,document)
        if variant.code_digest!=candidate.code_digest or variant.text_utf8_sha256!=candidate.text_utf8_sha256:
            raise ValueError('context variant compiler values differ')
        if variant.namespace not in variants:
            name = variant.namespace+'.json'
            data = _json(document);_durable_bytes(out/name,data,replace=False)
            variants[variant.namespace] = dict(path=name,sha256=sha256(data).hexdigest(),bytes=len(data),
                source_unit=variant.source_unit,context_sha256=C._digest(encode(variant.context)),
                material_sha256=C._digest(encode(variant.material)),
                scopes=len(variant.material.scopes),regions=len(variant.material.regions),
                boundaries=len(variant.material.boundaries),slots=variant.material.slots,
                suppressed_annotations=sum(r.suppression_reason=='FUTURE_ANNOTATION_STRINGIZED'
                    for r in variant.material.regions))
        bindings.append(dict(compile_candidate=candidate.id,compile_result=encode(candidate.compile_result),
            variant=variant.namespace,conditions=candidate.conditions,obligations=candidate.obligations))
    links = write_table(out/'compile-context-bindings.jsonl.gz',bindings)
    result = dict(schema='scar.source-context-variants',schema_version=1,status='C1_COMPILE_CONTEXT_VARIANTS',
        source_facts=str(store.path),source_facts_sha256=sha256(store.raw).hexdigest(),compiled_sources=parent,
        variants=variants,bindings=links,source_body_activated=False,native_symbols_captured=False,
        f4_variant_built=False,first_stage_complete=False,target_executed=False,
        implementation_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),pins=pins())
    _durable_bytes(out/'result.json',_json(result),replace=False)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('facts','compiled-sources','out'):
        parser.add_argument('--'+name,required=True)
    args = parser.parse_args()
    print(json.dumps(build_context_variants(args.facts,args.compiled_sources,args.out)),flush=True)


if __name__=='__main__':
    main()
