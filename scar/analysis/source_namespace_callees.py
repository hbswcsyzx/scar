"""Bridge selected callee reference queries to source namespace definitions.

Shared namespace templates are instantiated at parent query/state anchors.
Original caller stacks and open boundaries remain untouched. Function bodies
are linked only under their reference-path, creation and signature conditions.
"""
import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import time

from scar.analysis.source_call_context_graph import CallContextParents, read_call_context_graph
from scar.analysis.source_namespace_references import NamespaceReferenceResolver
from scar.analysis.source_reference_slice import source_port
from scar.analysis.source_field_interfaces import _InterfaceOnly
from scar.analysis.source_function_connections import Invocation, connect
from scar.analysis.source_value_flow import _artifact
from scar.analysis.normal_output import write_table
from scar.analysis.source_stage import _durable_bytes, _durable_mkdir
from scar.analysis.source_symbol_variants import _table
from scar.analysis.source_template_links import _json
from scar.ir.program import source_namespace_callees as X, source_productions as P, normal_targets as T
from scar.ir.program.source_namespace_references import NamespaceOriginKind
from scar.ir.record_codec import encode, decode


class NamespaceCalleeParents:
    def __init__(self, path):
        started=time.monotonic();self.root=Path(path).absolute()
        header=json.loads((self.root/'result.json').read_bytes())
        self.base=CallContextParents(header['body_expansion'])
        self.report,self.graph=read_call_context_graph(self.root,parents=self.base)
        self.raw=(self.root/'result.json').read_bytes()
        if json.loads(self.raw)!=self.report:raise ValueError('namespace callee parent changed')
        self.artifact=_artifact(self.root/'result.json',self.report['schema'])
        self.snapshot=self.base.base.values.snapshot
        self.validate();self.certification_seconds=time.monotonic()-started

    def validate(self):
        from scar.analysis.source_call_context_graph import _pins
        if self.raw!=(self.root/'result.json').read_bytes() or self.report['pins']!=_pins():
            raise ValueError('namespace callee original context report or rules changed')
        for receipt in self.report['tables'].values():
            raw=(self.root/receipt['path']).read_bytes()
            if len(raw)!=receipt['bytes'] or sha256(raw).hexdigest()!=receipt['sha256']:
                raise ValueError('namespace callee original table changed')
        self.base.validate()


def resolve_namespace_callees(snapshot, queries):
    resolver=NamespaceReferenceResolver(snapshot);lookups=[];anchors=[];ids={}
    functions=[];frontiers=[];symbols=[];mini_cache={}
    for qi,query in enumerate(queries):
        # Multiple old reasons at one state do not create duplicate lookups.
        states=tuple(dict.fromkeys(f.state for f in query.reference.frontiers))
        caller,local=resolver.slicer.local(query.callee)
        ordinal=int(query.call.locator.rsplit('/',1)[1]);call=caller.calls[ordinal]
        if (query.call!=resolver.slicer.fact(caller,'calls',ordinal)
                or query.callee!=source_port(caller,call.callee)):
            raise ValueError('namespace callee query changed its original source call')
        offset=resolver.slicer.store.offsets[caller.unit]
        invocation=Invocation(offset+call.callee,tuple(offset+p for p in call.positional),
            tuple((name,offset+p) for name,p in call.keywords),offset+call.result,offset+call.world,
            offset+call.result_world,None if call.positional_pack is None else offset+call.positional_pack,
            None if call.keyword_pack is None else offset+call.keyword_pack)
        for state in states:
            point=query.reference.states[state].port
            if type(point) is not T.GlobalPort:continue
            if point not in ids:
                ids[point]=len(lookups);lookups.append(X.CalleeNamespaceLookup(point,resolver.resolve(point)))
            lookup=ids[point];anchor=len(anchors);anchors.append(X.CalleeNamespaceAnchor(qi,state,lookup))
            reference=lookups[lookup].reference;found=False
            for oi,origin in enumerate(reference.origins):
                if origin.kind is NamespaceOriginKind.CLASS_DEFINITION:
                    frontiers.append(X.NamespaceCallFrontier(anchor,oi,'CLASS_PRODUCT_REQUIRES_CONSTRUCTOR_PROTOCOL'))
                    continue
                if origin.kind is not NamespaceOriginKind.FUNCTION_DEFINITION:continue
                terminal=reference.states[origin.state]
                if terminal.selectors:raise ValueError('namespace function source still has pending attributes')
                provider,local=resolver.slicer.local(terminal.port)
                fn=next(f for f in provider.functions if f.value==local)
                if terminal.port not in mini_cache:mini_cache[terminal.port]=_InterfaceOnly(resolver.slicer,provider,fn)
                mini=mini_cache[terminal.port]
                connection=connect(mini,mini.offsets[provider.unit]+fn.value,invocation,conditions=(
                    'SELECTED_PARENT_QUERY_STATE_REFERENCE_PATH_AND_NAMESPACE_ORIGIN_PATH',
                    'NAMESPACE_TEMPLATE_FRAME_AND_WORLD_INSTANTIATED_AT_PARENT_ANCHOR',
                    'CURRENT_NAMESPACE_SLOT_SELECTS_RECORDED_FUNCTION_DEFINITION',
                    'FUNCTION_CREATION_CODE_CAPTURE_AND_DEFAULT_VERSIONS_MATCH_DECLARATION',
                    'SOURCE_LOOKUP_CONDITIONS_REMAIN_REQUIRED_NOT_RUNTIME_DISPATCH'))
                if connection is None:
                    frontiers.append(X.NamespaceCallFrontier(anchor,oi,'SOURCE_FUNCTION_SIGNATURE_NOT_ADMITTED'))
                else:found=True;functions.append(X.NamespaceFunctionConnection(anchor,oi,connection))
            if not found:frontiers.append(X.NamespaceCallFrontier(anchor,None,'NAMESPACE_FUNCTION_TARGET_REMAINS_OPEN'))
    # Keep external named-interface requests even without a retained Python
    # provider. They are not converted to a callable/class/native target here.
    for li,lookup in enumerate(lookups):
        for si,state in enumerate(lookup.reference.states):
            if not state.selectors:continue
            unit,local=resolver.slicer.local(state.port)
            _,*_,imports,_=resolver.unit(unit.unit)
            for ordinal,imported in imports.get(local,()):
                symbols.append(X.NamespaceSymbolRequest(li,si,resolver.slicer.fact(unit,'imports',ordinal),
                    imported.module,imported.requested_module,state.selectors))
    snapshot.validate_parents()
    return dict(lookups=tuple(lookups),anchors=tuple(anchors),functions=tuple(functions),
        frontiers=tuple(frontiers),symbols=tuple(symbols))


CLASSES=dict(lookups=X.CalleeNamespaceLookup,anchors=X.CalleeNamespaceAnchor,
    functions=X.NamespaceFunctionConnection,frontiers=X.NamespaceCallFrontier,symbols=X.NamespaceSymbolRequest)


def _counts(graph):
    return dict(lookups=len(graph['lookups']),anchors=len(graph['anchors']),
        namespace_states=sum(len(l.reference.states) for l in graph['lookups']),
        namespace_edges=sum(len(l.reference.edges) for l in graph['lookups']),
        origin_kinds=dict(Counter(o.kind.value for l in graph['lookups'] for o in l.reference.origins)),
        namespace_frontiers=sum(len(l.reference.frontiers) for l in graph['lookups']),
        source_function_connections=len(graph['functions']),source_functions=len({f.connection.source_callable for f in graph['functions']}),
        bound_queries=len({graph['anchors'][f.anchor].query for f in graph['functions']}),
        frontiers=len(graph['frontiers']),frontier_reasons=dict(Counter(f.reason for f in graph['frontiers'])),
        symbol_requests=len(graph['symbols']))


def _pins():
    from scar.analysis import source_namespace_references,source_function_connections
    from scar.ir.program import source_namespace_references as N
    return {name:sha256(Path(path).read_bytes()).hexdigest() for name,path in (
        ('producer',__file__),('types',X.__file__),('namespaces',source_namespace_references.__file__),
        ('namespace_types',N.__file__),('binder',source_function_connections.__file__))}


def _parent(path,parents):
    parents=parents if parents is not None else NamespaceCalleeParents(path)
    if parents.root!=Path(path).absolute():raise ValueError('namespace callee parent path differs')
    parents.validate();return parents


def build_namespace_callees(path,out,*,parents=None):
    started=time.monotonic();pins=_pins();out=Path(out).absolute()
    if out.exists():raise ValueError('fresh namespace callee output required')
    parents=_parent(path,parents);graph=resolve_namespace_callees(parents.snapshot,parents.graph['queries'])
    parents.validate()
    if pins!=_pins():raise ValueError('namespace callee rules changed')
    _durable_mkdir(out)
    tables={name:write_table(out/(name+'.jsonl.gz'),rows) for name,rows in graph.items()}
    report=dict(schema='scar.namespace-callee-sources',schema_version=1,status='CONDITIONAL_NAMESPACE_FUNCTION_INTERFACES',
        calls=str(parents.root),parent=encode(parents.artifact),pins=pins,tables=tables,counts=_counts(graph),
        parent_caller_stacks_retained=True,current_namespace_versions_proven=False,
        runtime_dispatch_proven=False,target_executed=False,first_stage_complete=False,seconds=time.monotonic()-started)
    _durable_bytes(out/'result.json',_json(report),replace=False);return report


def read_namespace_callees(path,*,parents=None):
    path=Path(path).absolute();raw=(path/'result.json').read_bytes();report=json.loads(raw)
    if (report['schema'],report['schema_version'])!=('scar.namespace-callee-sources',1) or report['pins']!=_pins():
        raise ValueError('namespace callee producer differs')
    parents=_parent(report['calls'],parents)
    if report['parent']!=encode(parents.artifact):raise ValueError('namespace callee parent differs')
    graph={name:tuple(decode(cls,row,record_tags=P.PRODUCTION_RECORD_TAGS)
        for row in _table(path,report['tables'][name])) for name,cls in CLASSES.items()}
    if graph!=resolve_namespace_callees(parents.snapshot,parents.graph['queries']) or _counts(graph)!=report['counts']:
        raise ValueError('namespace callee lookup paths, anchors or signatures differ')
    if (report['parent_caller_stacks_retained'] is not True or any(report[k] is not False for k in (
            'current_namespace_versions_proven','runtime_dispatch_proven','target_executed','first_stage_complete'))):
        raise ValueError('namespace callee sources cannot grant current identity or runtime authority')
    parents.validate()
    if raw!=(path/'result.json').read_bytes():raise ValueError('namespace callee graph changed during verification')
    return report,graph


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--calls');parser.add_argument('--out');parser.add_argument('--read');args=parser.parse_args()
    if args.read:report,_=read_namespace_callees(args.read)
    else:
        if not args.calls or not args.out:parser.error('--calls and --out required')
        report=build_namespace_callees(args.calls,args.out)
    print(json.dumps(dict(status=report['status'],counts=report['counts'],seconds=report['seconds'])),flush=True)


if __name__=='__main__':main()
