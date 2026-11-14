"""Join all recorded source-body entries through shared protocol interfaces.

All correspondence variants enter the same join. A captured caller location
selects existing source operations; unresolved choices remain conditional.
Occurrences stay in evidence tables rather than unrolling the source graph.
"""
from collections import Counter, defaultdict
from hashlib import sha256
import argparse
import json
from pathlib import Path
import time
from typing import get_args

from scar.analysis.source_body_interfaces import BodyInterfaceResolver, _pins as body_pins
from scar.analysis.source_observed_codes import ObservedSourceCodeProvider
from scar.analysis.source_observed_calls import ObservedSourceCallsiteIndex, _span
from scar.analysis.source_namespace_interfaces import NamespacePlanView
from scar.analysis.program_view import ProgramView, _digest
from scar.analysis.source_consumer_parents import _stamp
from scar.analysis.source_stage import _durable_bytes, _durable_mkdir
from scar.analysis.source_template_links import _json
from scar.analysis.source_symbol_variants import _table
from scar.analysis.source_value_flow import _artifact
from scar.analysis.normal_output import write_table
from scar.ir.program import source_body_activations as R, source_body_interfaces as B
from scar.ir.program import source_observed_codes as C, source_productions as P, normal_graph as G
from scar.ir.program.ids import ProviderID
from scar.ir.program.model import ValueKind, ValueType
from scar.ir.program.call_edges import CallEdgeBudget
from scar.ir.record_codec import encode, decode
from scar.trace.code_snapshot import site as code_site


SCHEMA = 'scar.source-body-activations'
TABLES = dict(interfaces=B.SourceBodyInterface, activations=R.SourceBodyActivation,
    observations=R.SourceBodyActivationObservation, parents=R.SourceBodyActivationParent,
    frontiers=R.SourceBodyActivationFrontier)
_LINK_TABLES = {C.ObservedSourceCodeLink:'records', C.ObservedSourceScopeLink:'scope_records',
    C.ObservedSourceRequestCodeLink:'request_records', C.ObservedSourceCompilerCodeLink:'compiler_records'}


def _links(codes):
    if set(_LINK_TABLES) != set(get_args(C.ObservedSourceBodyLink)):
        raise ValueError('activation correspondence adapters do not cover the closed source-body link domain')
    result = tuple(row for kind, table in _LINK_TABLES.items()
        for row in getattr(codes,table).values() if type(row) is kind)
    if (len(result) != sum(len(getattr(codes,name)) for name in _LINK_TABLES.values())
            or len({row.id for row in result}) != len(result)):
        raise ValueError('source-body correspondence domain contains unclassified or duplicate rows')
    # Correspondence alternatives are a set. Their source catalog enumeration
    # must not change activation identity when another admitted index is reused.
    return tuple(sorted(result,key=lambda row:row.id.value))


def _completions(context, step):
    return tuple(B.SourceBodyCompletion(completion.kind,completion.target,completion.types,
        tuple(context.gp(context.emitter.port(step.id,G.PortKind.RESULT,i,completion))
            for i in range(len(completion.types))),
        context.gp(context.emitter.port(step.id,G.PortKind.EXIT,completion=completion)))
        for completion in step.completions)


class _SourceAnchors:
    """Location abstraction over original typed operations, for every opcode.

    Exact existing CALL mappings take precedence. Otherwise the innermost
    enclosing F2 location supplies conditional operation alternatives in the
    original code scope. This neither infers a callable by name nor asserts
    that a source span uniquely identifies an operation.
    """
    def __init__(self,index,resolver):
        self.index=index; self.resolver=resolver; self.observed=defaultdict(list)
        self.cache={}; self.locations={}
        for row in (*index.bindings,*index.protocol_bindings):
            self.observed[row.caller.process_id,row.attempt.site].append(row)

    def _anchor(self,site,unit,context,step):
        return R.SourceActivationAnchor(site,context.site(step),context.owner(step.region),
            tuple(context.value(value) for value in step.arguments),
            tuple(context.emitter.value(value)[1] for value in step.arguments),_completions(context,step))

    @staticmethod
    def _contains(outer,inner):
        return (outer[0],outer[2]) <= (inner[0],inner[2]) and (inner[1],inner[3]) <= (outer[1],outer[3])

    def select(self,process,site):
        key=process,site
        if key in self.cache:return self.cache[key]
        callers=self.index._callers.get((process,site.code),())
        for caller in callers:
            if code_site(caller.code,site.offset) != encode(site):
                raise ValueError('activation caller site differs from its original full compiler code')
        result=[]
        for row in self.observed.get(key,()):
            port=row.operation if hasattr(row,'operation') else row.result
            context=self.resolver.plan(row.unit,port.port.template)
            step=context.steps[port.port.owner]
            if context.owner(step.region) != row.owner:
                raise ValueError('activation anchor differs from the original observed source scope')
            result.append(self._anchor(site,row.unit,context,step))
        if not result and site.position is not None:
            for caller in callers:
                unit=caller.unit; source=self.index.view.unit(unit)
                if unit not in self.locations:
                    syntax=self.index._source_syntax(unit); locations=[]
                    for template in source.material.interfaces['nodes']:
                        try:span=_span(syntax,template.occurrence)
                        except (KeyError,TypeError):continue  # Module roots have no PEP657 coordinates.
                        if span is not None and all(type(v) is int for v in span):locations.append((span,template))
                    self.locations[unit]=tuple(locations)
                candidates=[(span,template) for span,template in self.locations[unit]
                    if self._contains(span,site.position)]
                if not candidates:continue
                # Select code ownership before taking the innermost source
                # location. A compiler instruction may carry the location of
                # syntax evaluated in another scope (e.g. a generator's first
                # iterable); pruning by syntax alone hides its body protocol.
                located=[]
                for _,template in candidates:
                    context=self.resolver.plan(unit,template)
                    for step in context.plan.steps:
                        if context.owner(step.region).owner != caller.scope.owner:continue
                        try:span=_span(self.index._source_syntax(unit),step.source.occurrence)
                        except (KeyError,TypeError):continue
                        if (span is None or any(type(value) is not int for value in span)
                                or not self._contains(span,site.position)):continue
                        types=tuple(context.emitter.value(value)[1] for value in step.arguments)
                        if any(type(t) is ValueType and t.kind is ValueKind.STATE for t in types):
                            located.append((span,self._anchor(site,unit,context,step)))
                result.extend(anchor for span,anchor in located if not any(
                    other!=span and self._contains(span,other) for other,_ in located))
        answer=tuple(sorted(dict.fromkeys(result),key=_digest)); self.cache[key]=answer
        return answer


def derive_body_activations(index):
    """Account for every retained frame entry; no direct-CALL-only filter."""
    if type(index) is not ObservedSourceCallsiteIndex:
        raise TypeError('body activation join requires its original checked call/source index')
    index.check(); links=_links(index.codes); by_code=defaultdict(list); by_site=defaultdict(list)
    registered=set()
    for link in links:
        for capture in link.captures:
            identity=capture.process_id,capture.code.key,link.id
            if identity in registered:continue
            registered.add(identity)
            by_code[capture.process_id,capture.code.key].append((link,capture))
            by_site[capture.process_id,capture.code.key].append(link)
    endings=defaultdict(list)
    for exit_ in index.codes.trace.exits:endings[exit_.invocation].append(exit_)
    resolver=BodyInterfaceResolver(index.view); anchors=_SourceAnchors(index,resolver)
    interfaces={}; activations={}; observations=[]; frontiers=[]; by_invocation=defaultdict(list)
    for entry in index.codes.trace.entries:
        matches=by_code.get((entry.invocation.process_id,entry.code),())
        if not matches:
            frontiers.append(R.SourceBodyActivationFrontier(entry,'EXECUTED_CODE_HAS_NO_SOURCE_BODY_CORRESPONDENCE'))
        for link,capture in matches:
            interface=resolver.resolve(link.body)
            if interface.scope != link.scope:raise ValueError('activation source scope differs from its original body interface')
            if entry.suspended != bool(capture.code.flags & (0x20|0x80|0x200)):
                raise ValueError('activation suspension capability differs from its captured code')
            interface_id=interface.id; interfaces[interface_id]=interface
            path_index=None; caller_links=(); selected=()
            for ordinal,site in enumerate(entry.path):
                parents=by_site.get((entry.invocation.process_id,site.code),())
                if parents:
                    path_index=ordinal; caller_links=tuple(dict.fromkeys(row.id for row in parents))
                    selected=anchors.select(entry.invocation.process_id,site)
                    break
            identity=ProviderID(_digest((SCHEMA,link.id,interface_id,capture.code,entry.path,
                entry.suspended,caller_links,path_index,selected)))
            activation=R.SourceBodyActivation(identity,link.id,interface_id,capture.code,entry.path,
                entry.suspended,caller_links,path_index,selected)
            if activations.setdefault(identity,activation) != activation:raise ValueError('activation identity collision')
            exits=endings.get(entry.invocation,())
            exit_=exits[0] if len(exits)==1 and exits[0].code==entry.code else None
            observations.append(R.SourceBodyActivationObservation(identity,entry,exit_))
            by_invocation[entry.invocation].append(identity)
            if not entry.path_complete:
                frontiers.append(R.SourceBodyActivationFrontier(entry,'RECORDED_CALLER_PATH_INCOMPLETE'))
            if path_index is not None and not selected:
                frontiers.append(R.SourceBodyActivationFrontier(entry,'SOURCE_CALLER_KNOWN_OPERATION_ANCHOR_UNRESOLVED'))
    parents=[]
    for observation in observations:
        entry=observation.entry; caller=entry.caller_invocation or entry.ancestor_invocation
        for parent in by_invocation.get(caller,()):
            parents.append(R.SourceBodyActivationParent(parent,observation.activation,entry.anchor,
                entry.caller_invocation is not None))
    units=defaultdict(lambda:{name:[] for name in TABLES})
    for interface in interfaces.values():units[interface.body.unit]['interfaces'].append(interface)
    by_id={row.id:row for row in interfaces.values()}
    unit_of=lambda identity:by_id[activations[identity].interface].body.unit
    for row in activations.values():units[unit_of(row.id)]['activations'].append(row)
    for row in observations:units[unit_of(row.activation)]['observations'].append(row)
    for row in dict.fromkeys(parents):units[unit_of(row.child)]['parents'].append(row)
    for row in dict.fromkeys(frontiers):
        for identity in by_invocation.get(row.entry.invocation,()):units[unit_of(identity)]['frontiers'].append(row)
    index.check()
    return {unit:{name:tuple(rows[name]) for name in TABLES} for unit,rows in sorted(units.items())},tuple(
        row for row in frontiers if row.entry.invocation not in by_invocation)


def _pins():
    from scar.ir.program import source_observed_codes
    from scar.analysis import source_observed_codes as code_reader,source_observed_calls as call_reader
    return {**body_pins(), **{'correspondence_'+name:digest
        for name,digest in code_reader.request_code_pins().items()},
        'activation_producer':sha256(Path(__file__).read_bytes()).hexdigest(),
        'activation_types':sha256(Path(R.__file__).read_bytes()).hexdigest(),
        'correspondence_types':sha256(Path(source_observed_codes.__file__).read_bytes()).hexdigest(),
        'correspondence_reader':sha256(Path(code_reader.__file__).read_bytes()).hexdigest(),
        'call_reader':sha256(Path(call_reader.__file__).read_bytes()).hexdigest()}


def _basis(index):
    return dict(catalog=encode(_artifact(index.view.catalog.path/'result.json',index.view.catalog.report['schema'])),
        trace=index.codes.trace.directory,project_root=index.codes.project_root,code_units=sorted(index.codes.selected_units),
        run_scope=index.codes.targets.source_sha256,target_reader_budget=index.codes.target_reader_budget,
        frame_budget=encode(index.codes.trace.frame_budget))


def _coverage(index,rows,unmatched):
    observations=[row for values in rows.values() for row in values['observations']]
    actual={row.anchor for row in index.codes.trace.entries}; covered={row.entry.anchor for row in observations}
    return dict(recorded_entries=len(actual),covered_entries=len(covered),missing_entries=len(actual-covered),
        shared_activations=sum(len(values['activations']) for values in rows.values()),
        shared_interfaces=sum(len(values['interfaces']) for values in rows.values()),
        unmatched_entries=len(unmatched),occurrences=len(observations),
        source_anchor_frontiers=sum(len(values['frontiers']) for values in rows.values()),
        entry_coverage_complete=covered==actual,
        body_protocols=dict(Counter(type(row.instruction).__name__ for values in rows.values() for row in values['interfaces'])))


def build_body_activations(index,out):
    started=time.monotonic(); out=Path(out).absolute()
    if out.resolve()!=out or out.exists():raise ValueError('activation graph requires fresh canonical output')
    pins=_pins(); basis=_basis(index); rows,unmatched=derive_body_activations(index); _durable_mkdir(out); shards={}
    for unit,values in rows.items():
        folder=out/'units'/unit; _durable_mkdir(folder)
        shards[unit]=dict(path='units/'+unit,tables={name:write_table(folder/(name+'.jsonl.gz'),values[name]) for name in TABLES},
            counts={name:len(values[name]) for name in TABLES})
    missing=write_table(out/'unmatched.jsonl.gz',unmatched)
    report=dict(schema=SCHEMA,schema_version=1,basis=basis,pins=pins,shards=shards,unmatched=missing,
        coverage=_coverage(index,rows,unmatched),target_executed=False,source_bodies_copied=False,
        argument_aliases_proven=False,namespace_instances_bound=False,first_stage_complete=False,
        seconds=time.monotonic()-started)
    if pins!=_pins() or basis!=_basis(index):raise ValueError('activation input or implementation changed during join')
    _durable_bytes(out/'result.json',_json(report),replace=False)
    return report


class SourceBodyActivationStore:
    def __init__(self,path,*,index=None):
        self.path=Path(path).resolve(); self.raw=(self.path/'result.json').read_bytes(); self.report=r=json.loads(self.raw)
        if (r['schema'],r['schema_version'],r['pins'])!=(SCHEMA,1,_pins()):
            raise ValueError('activation schema or implementation differs')
        if any(r[name] is not False for name in ('target_executed','source_bodies_copied',
                'argument_aliases_proven','namespace_instances_bound','first_stage_complete')):
            raise ValueError('activation metadata claims unproved identities or transformations')
        b=r['basis']
        if index is None:
            view=ProgramView(Path(b['catalog']['uri']).parent)
            codes=ObservedSourceCodeProvider(view,b['trace'],b['project_root'],units=b['code_units'],
                frame_budget=decode(CallEdgeBudget,b['frame_budget']),**b['target_reader_budget'])
            index=ObservedSourceCallsiteIndex(codes)
        self.index=index; self.view=index.view; self.rows={}; self.guards={}
        if _basis(index)!=b:raise ValueError('activation source or trace identity differs')
        expected,unmatched=derive_body_activations(index)
        if tuple(expected)!=tuple(r['shards']):raise ValueError('activation unit denominator differs')
        for unit,values in expected.items():
            shard=r['shards'][unit]; folder=self.path/shard['path']; loaded={}
            if shard['path']!='units/'+unit or set(shard['tables'])!=set(TABLES):raise ValueError('activation shard schema differs')
            for name,kind in TABLES.items():
                receipt=shard['tables'][name]; path=folder/receipt['path']; stamp=_stamp(path)
                if receipt['path']!=name+'.jsonl.gz':raise ValueError('activation table location differs')
                loaded[name]=tuple(decode(kind,row,record_tags=P.PRODUCTION_RECORD_TAGS) for row in _table(folder,receipt))
                if _stamp(path)!=stamp:raise ValueError('activation table changed during read')
                self.guards[path]=stamp
            if loaded!=values or shard['counts']!={name:len(values[name]) for name in TABLES}:
                raise ValueError('activation table differs from original frame, source scope or typed body ports')
            self.rows[unit]=loaded
        missing=tuple(decode(R.SourceBodyActivationFrontier,row) for row in _table(self.path,r['unmatched']))
        if missing!=unmatched or r['coverage']!=_coverage(index,expected,unmatched):raise ValueError('activation entry coverage differs')
        self.guards[self.path/'result.json']=_stamp(self.path/'result.json')
        self.guards[self.path/r['unmatched']['path']]=_stamp(self.path/r['unmatched']['path'])
        self.guards.update((Path(module.__file__),_stamp(Path(module.__file__))) for module in (
            __import__(__name__,fromlist=['__file__']),R,B,C,P))
        self.check()

    def check(self):
        if self.raw!=(self.path/'result.json').read_bytes() or any(_stamp(path)!=stamp for path,stamp in self.guards.items()):
            raise ValueError('admitted activation material changed')


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--catalog'); parser.add_argument('--trace'); parser.add_argument('--project-root')
    parser.add_argument('--out'); parser.add_argument('--read'); parser.add_argument('--graph-check',action='store_true')
    parser.add_argument('--graph-check-out',help='read back graph using the same admitted source/trace index')
    args=parser.parse_args(argv)
    if args.graph_check:
        if not args.read or not args.out:parser.error('--graph-check requires --read and --out')
        from scar.analysis.source_body_activation_view import verify_body_activations
        report=verify_body_activations(args.read,args.out)
        print(json.dumps(report,indent=2));return 0
    if args.read:
        store=SourceBodyActivationStore(args.read); report=store.report
    else:
        if not all((args.catalog,args.trace,args.project_root,args.out)):parser.error('--catalog --trace --project-root --out required')
        view=ProgramView(args.catalog); codes=ObservedSourceCodeProvider(view,args.trace,args.project_root)
        index=ObservedSourceCallsiteIndex(codes)
        report=build_body_activations(index,args.out)
        if args.graph_check_out:
            from scar.analysis.source_body_activation_view import verify_body_activations
            verify_body_activations(args.out,args.graph_check_out,index=index)
    print(json.dumps(report['coverage'],indent=2))
    return 0


if __name__=='__main__':raise SystemExit(main())
