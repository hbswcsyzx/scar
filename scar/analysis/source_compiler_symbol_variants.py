"""C3-S pure symbol collection/analysis over verified compilation variants.

Official native words validate the computed projection, never supply answers
to the source symbol solver. Parent source-only readers grant no authority to
these variants. F4 construction and runtime bindings remain separate gates.
"""
import argparse
import __future__
from dataclasses import replace
from hashlib import sha256
from io import BytesIO, TextIOWrapper
import json
from pathlib import Path
import time

from scar.analysis import source_context_variants as C, source_binding_variants as B
from scar.analysis import source_symbol_variants as N, source_topology_variants as T
from scar.analysis import compiler_symbols as S, compiler_symbol_collect as collect
from scar.analysis import compiler_symbol_solve as solve, compiler_symbol_view
from scar.analysis.normal_facts import SourceFactStore
from scar.analysis.source_bytes import read_source_bytes
from scar.analysis.source_contexts import _digest
from scar.analysis.source_stage import _durable_bytes, _durable_mkdir
from scar.analysis.source_template_links import _json
from scar.ir.program import source_compiler_symbol_variants as V
from scar.ir.program import source_context_variants as CV, source_symbol_variants as NV
from scar.ir.program.compiler_symbols import CompilerSymbolsInput, CompilerSymbolsMaterial, SymbolLimits, SymbolStop
from scar.ir.program.source_syntax import SourceSyntaxMaterial
from scar.ir.program.source_roles import SourceRolesMaterial
from scar.ir.record_codec import decode, encode


def pins():
    return {name:sha256(Path(module.__file__).read_bytes()).hexdigest() for name,module in (
        ('contexts',C),('bindings',B),('native',N),('topology',T),
        ('symbols',S),('collect',collect),('solve',solve),('view',compiler_symbol_view),('types',V))}


class _ContextCollector(collect._Collector):
    def __init__(self, syntax, roles, contexts, declarations, native, topology, limits, flags):
        self.effective_future_flags = flags
        super().__init__(syntax,roles,contexts,declarations,native,topology,limits)

    def _future_annotations(self):
        return bool(self.effective_future_flags & __future__.annotations.compiler_flag)


def compiler_symbol_variant_document(context_document,binding_document,symbol_document,topology_document,
        f0,f1,f2,f3b,payload,worker,*,parents,limits=SymbolLimits()):
    """Replay variant parents, then reuse the source-only scalar algorithms.

    C2's reader verifies C1; C3-T's reader verifies both C1 and a fresh native
    capture. Decoding those same accepted documents adds no source-only grant.
    """
    if type(limits) is not SymbolLimits:
        raise TypeError('typed compiler symbol limits required')
    binding = B.read_binding_variant(binding_document,f0,f1,f2,f3b,context_document,payload)
    topology = T.read_topology_variant(topology_document,context_document,symbol_document,
        f0,f1,f2,f3b,payload,worker,parents=parents)
    context = decode(CV.SourceContextVariant,context_document)
    native = decode(NV.SourceSymbolVariant,symbol_document)
    context_sha = _digest(encode(context.material))
    if (any(value.namespace != context.namespace for value in (binding,topology,native))
            or any(value.context_material_sha256 != context_sha for value in (binding,topology,native))
            or native.context != context.context):
        raise ValueError('compiler symbol parents belong to different compilation contexts')
    syntax,roles = decode(SourceSyntaxMaterial,f2),decode(SourceRolesMaterial,f3b)
    declarations,nt,tt = binding.declarations,native.material,topology.material
    try:
        raw = _ContextCollector(syntax,roles,context.material,declarations,nt,tt,limits,
            context.context.compiled_future_flags).collect()
    except collect.TopologyStop as error:
        raise SymbolStop(error.frontier.code,error.frontier.detail,budget=error.budget) from error
    solution = solve.solve_symbols(raw,tt,declarations.names,limits=limits)
    symbols,parameters = S._project(solution,tt,declarations,nt)
    inputs = CompilerSymbolsInput(*(_digest(doc) for doc in
        (f0,f1,f2,f3b,encode(context.material),encode(declarations),encode(nt),encode(tt))),
        f0['path'],syntax.mode,declarations.status,tt.status,len(declarations.contributions),len(tt.blocks),
        sum(len(row.symbols) for row in nt.scopes),sum(len(row.varnames) for row in nt.scopes))
    profile = replace(S._profile(nt),rule_version='CPYTHON_COMPILER_SYMBOLS_COMPILE_VARIANT_V1',
        implementation_sha256=_digest(dict(pins=pins(),namespace=context.namespace,
            producer=sha256(Path(__file__).read_bytes()).hexdigest())))
    material = CompilerSymbolsMaterial(inputs,profile,limits,'PROJECTED',solution.slots,
        raw.contributions,raw.sources,solution.facts,solution.transforms,solution.protocols,
        solution.blocks,symbols,parameters,(),solution.steps)
    compiler_symbol_view.CompilerSymbolView(declarations,tt,nt,material).verify()
    return encode(V.SourceCompilerSymbolVariant(context.namespace,sha256(_json(context_document)).hexdigest(),
        context_sha,sha256(_json(binding_document)).hexdigest(),_digest(encode(binding.bindings)),
        sha256(_json(symbol_document)).hexdigest(),sha256(_json(topology_document)).hexdigest(),material))


def read_compiler_symbol_variant(document,context_document,binding_document,symbol_document,topology_document,
        f0,f1,f2,f3b,payload,worker,*,parents):
    value = decode(V.SourceCompilerSymbolVariant,document)
    fresh = compiler_symbol_variant_document(context_document,binding_document,symbol_document,topology_document,
        f0,f1,f2,f3b,payload,worker,parents=parents,limits=value.material.limits)
    if document != fresh:
        raise ValueError('compiler symbol variant differs from source/context/native provenance')
    return value


def _report(path,schema,producer):
    path = Path(path).absolute();raw = (path/'result.json').read_bytes();report = json.loads(raw)
    if ((report['schema'],report['schema_version']) != (schema,1)
            or report['implementation_sha256'] != sha256(Path(producer.__file__).read_bytes()).hexdigest()
            or report['pins'] != producer.pins()):
        raise ValueError('compiler symbol parent producer differs')
    return path,raw,report,dict(path=str(path),sha256=sha256(raw).hexdigest())


def _variant(path,descriptor):
    raw = (path/descriptor['path']).read_bytes()
    if len(raw) != descriptor['bytes'] or sha256(raw).hexdigest() != descriptor['sha256']:
        raise ValueError('compiler symbol parent variant bytes differ')
    return json.loads(raw)


def build_compiler_symbol_variants(facts,contexts,bindings,symbols,topology,out):
    started = time.monotonic();out = Path(out).absolute()
    if out.exists():
        raise ValueError('fresh compiler symbol variant output required')
    store = SourceFactStore(facts)
    cp,craw,cr,cref = _report(contexts,'scar.source-context-variants',C)
    bp,braw,br,bref = _report(bindings,'scar.source-binding-variants',B)
    np,nraw,nr,nref = _report(symbols,'scar.source-symbol-variants',N)
    tp,traw,tr,tref = _report(topology,'scar.source-topology-variants',T)
    snapshots = ((cp,craw),(bp,braw),(np,nraw),(tp,traw))
    reports = (cr,br,nr,tr)
    if (any(r['source_facts_sha256'] != sha256(store.raw).hexdigest() for r in reports)
            or any(set(r['variants']) != set(cr['variants']) for r in reports)
            or any(r['context_variants'] != cref for r in (br,nr,tr))
            or tr['symbol_variants'] != nref):
        raise ValueError('compiler symbol variant parent stores or namespaces differ')
    _durable_mkdir(out);variants = {};manifests = []
    with N.SymbolVariantWorker(Path(nr['adapter']['path']).parent) as worker:
        if worker.parent != nr['adapter']:
            raise ValueError('compiler symbol native adapter differs')
        for namespace in cr['variants']:
            cdoc,bdoc,ndoc,tdoc = (_variant(path,r['variants'][namespace]) for path,r in
                ((cp,cr),(bp,br),(np,nr),(tp,tr)))
            context = decode(CV.SourceContextVariant,cdoc)
            native = decode(NV.SourceSymbolVariant,ndoc)
            if context.namespace != namespace or native.source_unit != context.source_unit:
                raise ValueError('compiler symbol source namespace differs')
            materials,parents,manifest = N._source_parents(store,context.source_unit)
            manifests.append(manifest);interp = native.text_inputs[0].interpretation
            with TextIOWrapper(BytesIO(read_source_bytes(materials[0])),encoding=interp.encoding,
                    errors=interp.errors,newline=interp.newline) as stream:
                payload = stream.read()
            document = compiler_symbol_variant_document(cdoc,bdoc,ndoc,tdoc,*materials,payload,worker,parents=parents)
            value = decode(V.SourceCompilerSymbolVariant,document)
            # Publish only after the independent public reader repeats the
            # pure solve and strict parent/native capture from retained inputs.
            checked = read_compiler_symbol_variant(document,cdoc,bdoc,ndoc,tdoc,*materials,payload,worker,parents=parents)
            if value != checked:
                raise ValueError('compiler symbol fresh reader differs')
            data = _json(document);name = namespace+'.json';_durable_bytes(out/name,data,replace=False)
            m = value.material
            variants[namespace] = dict(path=name,bytes=len(data),sha256=sha256(data).hexdigest(),
                context_material_sha256=value.context_material_sha256,
                binding_variant_sha256=value.binding_variant_sha256,native_variant_sha256=value.native_variant_sha256,
                topology_variant_sha256=value.topology_variant_sha256,material_sha256=_digest(encode(m)),
                slots=len(m.slots),contributions=len(m.contributions),sources=len(m.sources),facts=len(m.facts),
                transforms=len(m.transforms),protocols=len(m.protocols),blocks=len(m.blocks),
                symbols=len(m.symbols),parameters=len(m.parameters),steps=m.steps,fresh_reader_passed=True)
    if ((store.path/'result.json').read_bytes() != store.raw
            or any((path/'result.json').read_bytes() != raw for path,raw in snapshots)
            or any(path.read_bytes() != raw for path,raw in manifests)):
        raise ValueError('compiler symbol parents changed during projection')
    result = dict(schema='scar.source-compiler-symbol-variants',schema_version=1,
        status='CONTEXT_COMPILER_SYMBOLS_PROJECTED',source_facts=str(store.path),
        source_facts_sha256=sha256(store.raw).hexdigest(),context_variants=cref,binding_variants=bref,
        symbol_variants=nref,topology_variants=tref,variants=variants,seconds=time.monotonic()-started,
        fresh_reader_passed=True,source_body_activated=False,target_executed=False,
        f4_variant_built=False,first_stage_complete=False,
        implementation_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),pins=pins())
    _durable_bytes(out/'result.json',_json(result),replace=False)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('facts','contexts','bindings','symbols','topology','out'):
        parser.add_argument('--'+name,required=True)
    args = parser.parse_args()
    print(json.dumps(build_compiler_symbol_variants(args.facts,args.contexts,args.bindings,
        args.symbols,args.topology,args.out)),flush=True)


if __name__ == '__main__':
    main()
