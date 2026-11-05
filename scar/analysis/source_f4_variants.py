"""Build shared executable source graphs in verified compilation namespaces.

Reuse the existing F4 recipes and normal-edge/fact emitters. Imported units
and source-only stores are immutable; each compiled context owns one local
template graph, never one graph per invocation or loop iteration.
"""
import argparse
from collections import Counter,deque
from hashlib import sha256
from io import BytesIO,TextIOWrapper
import json
from pathlib import Path
import time

from scar.analysis import source_compiler_symbol_variants as S,source_compile_interfaces
from scar.analysis import source_expression_rules,source_statement_rules,source_root_rules,normal_graph,normal_links
from scar.analysis.frontend_bindings import FrontendBindingView
from scar.analysis.source_context_view import SourceContextView
from scar.analysis.source_productions import ProductionSourceIndex,production_plan_document
from scar.analysis.source_template_links import build_template_graph
from scar.analysis.source_expression_materials import _WORLD,_implementation as recipe_implementation
from scar.analysis.normal_facts import SourceFactStore
from scar.analysis.normal_output import write_table
from scar.analysis.source_bytes import read_source_bytes
from scar.analysis.source_stage import _durable_bytes,_durable_mkdir
from scar.analysis.source_template_links import _json
from scar.ir.program import source_context_variants as CV,source_binding_variants as BV
from scar.ir.program import source_symbol_variants as NV,source_topology_variants as TV
from scar.ir.program import source_compiler_symbol_variants as SV
from scar.ir.program import source_productions as P,normal_links as F
from scar.ir.program.source_template_links import SourceMaterialDomain as D
from scar.ir.program.protocol_signatures import ExceptionABI
from scar.ir.program.source_syntax import SourceSyntaxMaterial
from scar.ir.program.source_roles import SourceRolesMaterial
from scar.ir.record_codec import encode,decode


def pins():
    return dict(recipe_dependencies=recipe_implementation(),local_dependencies={name:sha256(Path(module.__file__).read_bytes()).hexdigest() for name,module in (
        ('compiler_symbols',S),('compiler_interfaces',source_compile_interfaces),
        ('expressions',source_expression_rules),('statements',source_statement_rules),
        ('roots',source_root_rules),('normal_graph',normal_graph),('normal_links',normal_links))})


def construct_graph(context,binding,native,topology,symbols,f0,f2,roles):
    frontend=FrontendBindingView(roles,context.material,binding.declarations,binding.bindings,
        native.material,topology.material,symbols.material)
    frontend.verify()
    syntax=decode(SourceSyntaxMaterial,f2)
    view=SourceContextView(syntax,roles,context.material)
    source=source_compile_interfaces.install_compile_context(ProductionSourceIndex(f0,view,frontend),context)
    kwargs=dict(world=_WORLD,exception_abi=ExceptionABI.EXCEPTION_WORLD)
    rules={D.EXPRESSIONS:source_expression_rules.SourceExpressionRules(source,**kwargs),
           D.STATEMENTS:source_statement_rules.SourceStatementRules(source,**kwargs),
           D.ROOTS:source_root_rules.SourceRootRules(source,**kwargs)}
    families={row.name:row.bases for row in syntax.profile.ast_schema}
    plans={};records={domain:[] for domain in D};dispositions=[];pending=deque();seen=set()
    def add(domain,plan):
        key=plan.source.occurrence,plan.purpose
        if key in plans:
            if plans[key]!=plan:raise ValueError('conflicting context source plans')
            return
        plans[key]=plan
        records[domain].append(production_plan_document(plan))
        for step in plan.steps:
            ins=step.instruction
            if type(ins) is P.EvaluateChild and ins.purpose is P.ProductionPurpose.CONDITION:
                occurrence=source.roles.locate(ins.field)[1].reference
                if occurrence not in seen:seen.add(occurrence);pending.append(occurrence)
    for occurrence,node in enumerate(syntax.nodes):
        domain=(D.ROOTS if occurrence==syntax.root else D.STATEMENTS if 'stmt' in families[node.constructor]
                else D.EXPRESSIONS if 'expr' in families[node.constructor] else None)
        if domain is None:
            owners=[rule.descriptor_owner(occurrence) for rule in
                (rules[D.EXPRESSIONS],rules[D.STATEMENTS])]
            owner=next((owner for owner in owners if owner is not None),None)
            dispositions.append(dict(occurrence=occurrence,constructor=node.constructor,domain=None,
                disposition='PARENT_SOURCE_DESCRIPTOR' if owner is not None else 'GRAMMAR_METADATA',
                owner=None if owner is None else encode(owner),suppression_reason=None))
            continue
        rule=rules[domain];owner=rule.descriptor_owner(occurrence)
        state=view.entry_context(occurrence);region=context.material.regions[state.region]
        disposition='PARENT_SOURCE_DESCRIPTOR' if owner is not None else (
            'SOURCE_NOT_SCHEDULED' if region.eligibility=='SUPPRESSED' else 'LOCAL_SOURCE_RULE')
        dispositions.append(dict(occurrence=occurrence,constructor=node.constructor,domain=domain.value,
            disposition=disposition,owner=None if owner is None else encode(owner),
            suppression_reason=region.suppression_reason))
        if disposition!='LOCAL_SOURCE_RULE':continue
        purpose={D.ROOTS:P.ProductionPurpose.ROOT,D.STATEMENTS:P.ProductionPurpose.STATEMENT,
                 D.EXPRESSIONS:P.ProductionPurpose.VALUE}[domain]
        if domain is D.EXPRESSIONS and node.constructor in ('Name','Attribute','Subscript','List','Tuple'):
            purpose={'Load':P.ProductionPurpose.VALUE,'Store':P.ProductionPurpose.STORE,
                     'Del':P.ProductionPurpose.DELETE}[source.roles.context(occurrence)]
        add(domain,rule.build(occurrence,purpose))
    while pending:
        add(D.EXPRESSIONS,rules[D.EXPRESSIONS].build(pending.popleft(),P.ProductionPurpose.CONDITION))
    graph=build_template_graph(context.namespace,f2,
        ((domain,i,document) for domain,rows in records.items() for i,document in enumerate(rows,1)))
    interfaces=dict(nodes={n.key:n for n in graph.templates},links={(e.caller,e.step):e for e in graph.links})
    unit=dict(key=context.namespace,path=f0['path'])
    facts=normal_links._Facts(unit,f2,encode(binding.bindings),encode(binding.declarations),encode(roles),encode(context.material))
    edges=[]
    for template in graph.templates:
        plan=plans[template.key.occurrence,template.key.purpose]
        edges.extend(normal_graph._Emitter(plan,template.key,interfaces).run())
        aliases=normal_links._Aliases(plan,template.key,interfaces,facts);aliases.run();aliases.describe()
    aliases=tuple(sorted(facts.aliases))
    values={name:tuple(getattr(facts,name)) for name in ('ports','names','functions','classes','attributes','imports',
        'constants','calls','containers','items','updates','iterations','operations','activations')}
    primitive=F.UnitFacts(context.namespace,facts.module,aliases=aliases,root_scope=facts.root_scope,
        scope_groups=facts.groups(aliases),**values)
    if primitive.root_scope is None:raise ValueError('compiled graph has no root interface')
    return graph,records,dispositions,edges,primitive


def build_f4_variants(facts,compiler_symbols,out):
    started=time.monotonic();out=Path(out).absolute()
    if out.exists():raise ValueError('fresh F4 variant output required')
    store=SourceFactStore(facts)
    sp,sraw,sr,sref=S._report(compiler_symbols,'scar.source-compiler-symbol-variants',S)
    inputs=[S._report(sr[name]['path'],schema,producer) for name,schema,producer in (
        ('context_variants','scar.source-context-variants',S.C),
        ('binding_variants','scar.source-binding-variants',S.B),
        ('symbol_variants','scar.source-symbol-variants',S.N),
        ('topology_variants','scar.source-topology-variants',S.T))]
    for (path,raw,report,reference),name in zip(inputs,('context_variants','binding_variants','symbol_variants','topology_variants')):
        if reference!=sr[name] or report['source_facts_sha256']!=sha256(store.raw).hexdigest():
            raise ValueError('F4 variant parent chain differs')
    if sr['source_facts_sha256']!=sha256(store.raw).hexdigest():raise ValueError('F4 source facts differ')
    initial_pins=pins();producer_sha=sha256(Path(__file__).read_bytes()).hexdigest()
    snapshots=[(sp/'result.json',sraw),*((path/'result.json',raw) for path,raw,_,_ in inputs)]
    manifests=[]
    _durable_mkdir(out);variants={}
    with S.N.SymbolVariantWorker(Path(inputs[2][2]['adapter']['path']).parent) as worker:
        for namespace,sd in sr['variants'].items():
            cdoc,bdoc,ndoc,tdoc=(S._variant(path,report['variants'][namespace]) for path,_,report,_ in inputs)
            sdoc=S._variant(sp,sd);context=decode(CV.SourceContextVariant,cdoc)
            native=decode(NV.SourceSymbolVariant,ndoc)
            materials,parents,manifest=S.N._source_parents(store,context.source_unit)
            manifests.append(manifest)
            interp=native.text_inputs[0].interpretation
            with TextIOWrapper(BytesIO(read_source_bytes(materials[0])),encoding=interp.encoding,
                    errors=interp.errors,newline=interp.newline) as stream:payload=stream.read()
            symbol=S.read_compiler_symbol_variant(sdoc,cdoc,bdoc,ndoc,tdoc,*materials,payload,worker,parents=parents)
            binding,topology=decode(BV.SourceBindingVariant,bdoc),decode(TV.SourceTopologyVariant,tdoc)
            graph,records,dispositions,edges,primitive=construct_graph(context,binding,native,topology,symbol,
                materials[0],materials[2],decode(SourceRolesMaterial,materials[3]))
            folder=out/namespace;_durable_mkdir(folder)
            tables={domain.value:write_table(folder/(domain.value+'.jsonl.gz'),rows) for domain,rows in records.items()}
            tables['dispositions']=write_table(folder/'dispositions.jsonl.gz',dispositions)
            tables['normal_edges']=write_table(folder/'normal-edges.jsonl.gz',edges)
            for name,value in (('templates',graph),('facts',primitive)):
                tables[name]=write_table(folder/(name+'.jsonl.gz'),(value,))
            variants[namespace]=dict(original_source_unit=context.source_unit,path=namespace,tables=tables,
                templates=len(graph.templates),template_links=len(graph.links),operations=sum(len(row['steps']) for rows in records.values() for row in rows),
                normal_edges=len(edges),ports=len(primitive.ports),functions=len(primitive.functions),calls=len(primitive.calls),
                loops=sum(r['constructor'] in ('For','AsyncFor','While') and r['disposition']=='LOCAL_SOURCE_RULE' for r in dispositions),
                root=encode(primitive.root_scope),dispositions=dict(Counter(r['disposition'] for r in dispositions)))
    if ((store.path/'result.json').read_bytes()!=store.raw
            or any(path.read_bytes()!=raw for path,raw in (*snapshots,*manifests))
            or pins()!=initial_pins or sha256(Path(__file__).read_bytes()).hexdigest()!=producer_sha):
        raise ValueError('F4 variant inputs or rule dependencies changed during construction')
    result=dict(schema='scar.source-f4-variants',schema_version=1,status='CONTEXT_SOURCE_GRAPHS_BUILT',
        source_facts=str(store.path),source_facts_sha256=sha256(store.raw).hexdigest(),compiler_symbols=sref,
        variants=variants,seconds=time.monotonic()-started,f4_variant_built=True,source_body_activated=False,
        target_executed=False,first_stage_complete=False,implementation_sha256=producer_sha,pins=initial_pins)
    _durable_bytes(out/'result.json',_json(result),replace=False)
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('facts','compiler-symbols','out'):parser.add_argument('--'+name,required=True)
    args=parser.parse_args()
    print(json.dumps(build_f4_variants(args.facts,args.compiler_symbols,args.out)),flush=True)


if __name__=='__main__':main()
