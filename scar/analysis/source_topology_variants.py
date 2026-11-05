"""C3-T matches original syntax scopes to an official flags-aware raw view.

Only the effective-future policy differs from the retained topology rules.
Normal source/native graphs and their public rows remain separately named.
Detached/inlined scopes are explicit; no row-count or line-number pairing.
"""
import argparse
import __future__
from dataclasses import replace
from hashlib import sha256
from io import BytesIO,TextIOWrapper
import json
from pathlib import Path

from scar.analysis import source_context_variants as C,source_symbol_variants as N
from scar.analysis import compiler_topology as T,compiler_topology_view
from scar.analysis.normal_facts import SourceFactStore
from scar.analysis.source_bytes import read_source_bytes
from scar.analysis.source_contexts import _digest
from scar.analysis.source_stage import _durable_bytes,_durable_mkdir
from scar.analysis.source_template_links import _json
from scar.ir.program import source_topology_variants as V,source_symbol_variants as NV
from scar.ir.program.source_syntax import SourceSyntaxMaterial
from scar.ir.program.source_roles import SourceRolesMaterial
from scar.ir.program.compiler_topology import CompilerTopologyInput,CompilerTopologyMaterial
from scar.ir.record_codec import encode,decode


def pins():
    return {name:sha256(Path(module.__file__).read_bytes()).hexdigest() for name,module in (
        ('context_variant',C),('symbol_variant',N),('symbol_types',NV),
        ('topology',T),('view',compiler_topology_view),('types',V))}


class _ContextBuilder(T._Builder):
    def __init__(self,syntax,roles,contexts,native,limits,flags):
        self.effective_future_flags=flags
        super().__init__(syntax,roles,contexts,native,limits)

    def _future_annotations(self):
        return bool(self.effective_future_flags & __future__.annotations.compiler_flag)


def topology_variant_document(context_document,symbol_document,f0,f1,f2,f3b,payload,worker,*,parents,
                               max_blocks=100000,max_rewrites=200000,max_visit_steps=4000000):
    context=C.read_context_variant(context_document,f0,f1,f2,f3b,payload)
    native=N.read_symbol_variant(symbol_document,context_document,f0,f1,f2,f3b,payload,worker,
        parents=parents,context_document_sha256=sha256(_json(context_document)).hexdigest())
    if native.namespace!=context.namespace or native.context!=context.context:
        raise ValueError('native scope context differs from source context')
    syntax,roles=decode(SourceSyntaxMaterial,f2),decode(SourceRolesMaterial,f3b)
    limits=max_blocks,max_rewrites,max_visit_steps
    if any(type(n) is not int or n<0 for n in limits):
        raise ValueError('exact nonnegative topology limits required')
    builder=_ContextBuilder(syntax,roles,context.material,native.material,limits,
        context.context.compiled_future_flags)
    projections=builder.run()
    inputs=CompilerTopologyInput(*(_digest(d) for d in
        (f0,f1,f2,f3b,encode(context.material),encode(native.material))),f0['path'],syntax.mode,
        context.material.status,native.material.status,len(context.material.scopes),len(native.material.scopes))
    profile=replace(T._profile(native.material),rule_version='CPYTHON_TOPOLOGY_COMPILE_VARIANT_V1',
        implementation_sha256=_digest(dict(pins=pins(),namespace=context.namespace,
            producer=sha256(Path(__file__).read_bytes()).hexdigest())))
    material=CompilerTopologyMaterial(inputs,profile,*limits,'PROJECTED',tuple(builder.blocks),
        projections,tuple(builder.rewrites),(),builder.visit_steps)
    compiler_topology_view.CompilerTopologyView(roles,context.material,native.material,material,
        contexts=builder.view).verify()
    return encode(V.SourceTopologyVariant(context.namespace,_digest(encode(context.material)),
        sha256(_json(symbol_document)).hexdigest(),material))


def read_topology_variant(document,context_document,symbol_document,f0,f1,f2,f3b,payload,worker,*,parents):
    value=decode(V.SourceTopologyVariant,document);m=value.material
    fresh=topology_variant_document(context_document,symbol_document,f0,f1,f2,f3b,payload,worker,
        parents=parents,max_blocks=m.max_blocks,max_rewrites=m.max_rewrites,max_visit_steps=m.max_visit_steps)
    if fresh!=document:
        raise ValueError('topology variant differs from source/native correspondence rules')
    return value


def build_topology_variants(facts,contexts,symbols,out):
    out=Path(out).absolute()
    if out.exists():
        raise ValueError('fresh topology variant output required')
    store=SourceFactStore(facts);cp=Path(contexts).absolute();np=Path(symbols).absolute()
    craw=(cp/'result.json').read_bytes();nraw=(np/'result.json').read_bytes()
    cr,nr=json.loads(craw),json.loads(nraw)
    if ((cr['schema'],cr['schema_version'])!=('scar.source-context-variants',1)
            or cr['implementation_sha256']!=sha256(Path(C.__file__).read_bytes()).hexdigest() or cr['pins']!=C.pins()):
        raise ValueError('C1 variant producer differs')
    if ((nr['schema'],nr['schema_version'])!=('scar.source-symbol-variants',1)
            or nr['implementation_sha256']!=sha256(Path(N.__file__).read_bytes()).hexdigest() or nr['pins']!=N.pins()):
        raise ValueError('native variant producer differs')
    if (nr['context_variants']!=dict(path=str(cp),sha256=sha256(craw).hexdigest())
            or any(r['source_facts_sha256']!=sha256(store.raw).hexdigest() for r in (cr,nr))
            or set(cr['variants'])!=set(nr['variants'])):
        raise ValueError('topology variant parents differ')
    _durable_mkdir(out);variants={}
    adapter_directory=Path(nr['adapter']['path']).parent
    with N.SymbolVariantWorker(adapter_directory) as worker:
        for namespace,cd in cr['variants'].items():
            nd=nr['variants'][namespace];cdata=(cp/cd['path']).read_bytes();ndata=(np/nd['path']).read_bytes()
            for raw,d in ((cdata,cd),(ndata,nd)):
                if len(raw)!=d['bytes'] or sha256(raw).hexdigest()!=d['sha256']:
                    raise ValueError('context/native variant material differs')
            cdoc,ndoc=json.loads(cdata),json.loads(ndata);native=decode(NV.SourceSymbolVariant,ndoc)
            materials,parents,_=N._source_parents(store,native.source_unit)
            text=native.text_inputs[0];interp=text.interpretation
            with TextIOWrapper(BytesIO(read_source_bytes(materials[0])),encoding=interp.encoding,
                    errors=interp.errors,newline=interp.newline) as stream:payload=stream.read()
            result=topology_variant_document(cdoc,ndoc,*materials,payload,worker,parents=parents)
            value=decode(V.SourceTopologyVariant,result);data=_json(result);name=namespace+'.json'
            _durable_bytes(out/name,data,replace=False)
            variants[namespace]=dict(path=name,bytes=len(data),sha256=sha256(data).hexdigest(),
                context_material_sha256=value.context_material_sha256,native_variant_sha256=value.native_variant_sha256,
                material_sha256=_digest(encode(value.material)),blocks=len(value.material.blocks),
                source_scopes=len(value.material.scopes),native_scopes=len(native.material.scopes),
                projections={kind:sum(b.projection==kind for b in value.material.blocks)
                    for kind in sorted({b.projection for b in value.material.blocks})})
    report=dict(schema='scar.source-topology-variants',schema_version=1,status='CONTEXT_SCOPE_TOPOLOGY_PROJECTED',
        source_facts=str(store.path),source_facts_sha256=sha256(store.raw).hexdigest(),
        context_variants=dict(path=str(cp),sha256=sha256(craw).hexdigest()),
        symbol_variants=dict(path=str(np),sha256=sha256(nraw).hexdigest()),variants=variants,
        target_executed=False,f4_variant_built=False,first_stage_complete=False,
        implementation_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),pins=pins())
    _durable_bytes(out/'result.json',_json(report),replace=False)
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('facts','contexts','symbols','out'):parser.add_argument('--'+name,required=True)
    args=parser.parse_args()
    print(json.dumps(build_topology_variants(args.facts,args.contexts,args.symbols,args.out)),flush=True)


if __name__=='__main__':main()
