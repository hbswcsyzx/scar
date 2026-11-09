"""Compact per-unit publication of source binding interfaces and may tracks."""
import argparse
from collections import Counter
from hashlib import sha256
from itertools import zip_longest
import json
from pathlib import Path
import time

from scar.analysis.normal_output import write_table
from scar.analysis.program_view import ProgramView
from scar.analysis.source_effects import catalog
from scar.analysis.source_stage import _durable_bytes, _durable_mkdir
from scar.analysis.source_symbol_variants import _table
from scar.analysis.source_template_links import _json
from scar.analysis.source_value_flow import _artifact
from scar.ir.program import source_state as S, source_productions as P
from scar.ir.program import view as V
from scar.ir.record_codec import encode, decode


def _pins():
    from scar.analysis import source_state, source_effects, source_name_definitions
    from scar.analysis import source_name_access_anchors, source_value_flow, program_view
    from scar.analysis import source_implicit_namespaces
    from scar.ir.program import source_effects as effects_types
    return {name:sha256(Path(module.__file__).read_bytes()).hexdigest() for name,module in (
        ('producer', __import__(__name__, fromlist=['__file__'])), ('state', source_state),
        ('state_types', S), ('effect_catalog', source_effects), ('effect_types', effects_types),
        ('definitions', source_name_definitions), ('anchors', source_name_access_anchors),
        ('implicit_addresses', source_implicit_namespaces),
        ('body_projection', source_value_flow), ('unified_adapter', program_view))}


def _edges(state):
    for rows in state.out_edges.values():
        for edge in rows:
            if edge.source.namespace != state.namespace or edge.target.namespace != state.namespace:
                raise ValueError('binding edge left its owning source unit')
            conditions = tuple(V.StoredDependencyCondition(c.domain,c.name,
                None if c.subject is None else c.subject.node,c.index,tuple(p.node for p in c.operands)) for c in edge.conditions)
            yield S.StoredBindingEdge(edge.source.node,edge.target.node,edge.kind,edge.meaning,
                edge.strength,edge.evidence[0].rule,conditions)


def _tracks(state):
    for graph,limits in zip(state.tracks,state.track_limits,strict=True):
        yield S.StoredBindingTrack(graph.source_function,graph.namespace,**limits,
            definitions=graph.definitions,states=graph.states,transitions=graph.transitions,
            reads=graph.reads,frontiers=graph.frontiers,traversal_complete=graph.traversal_complete,
            dataflow_complete=graph.dataflow_complete)


def _rows(state):
    return dict(rules=(type(catalog()[0]),catalog()),
        requests=(S.SourceEffectRequest,state.requests.values()),
        locations=(S.BindingLocationTemplate,state.locations.values()),
        accesses=(S.BindingAccessTemplate,state.accesses),
        versions=(S.BindingVersionTemplate,state.versions.values()),
        selections=(S.BindingReadSelection,state.selections),
        tracks=(S.StoredBindingTrack,_tracks(state)),edges=(S.StoredBindingEdge,_edges(state)))


def _counts(state):
    return dict(operations=len(state.requests),binding_accesses=len(state.accesses),locations=len(state.locations),
        versions=len(state.versions),read_selections=len(state.selections),tracks=len(state.tracks),
        relations=sum(len(rows) for rows in state.out_edges.values()),
        missing_address_rules=dict(Counter(r.rule.instruction for r in state.requests.values() if r.missing_rules)))


def publish_state_view(state, out):
    started=time.monotonic();pins=_pins();out=Path(out).absolute()
    if out.exists():raise ValueError('fresh state-view output required')
    state.check();_durable_mkdir(out)
    tables={name:write_table(out/(name+'.jsonl.gz'),rows) for name,(_,rows) in _rows(state).items()}
    report=dict(schema='scar.source-binding-state-view',schema_version=1,
        catalog=str(state.view.catalog.path),parent=encode(_artifact(state.view.catalog.path/'result.json',state.view.catalog.report['schema'])),
        unit=state.material.unit,namespace=encode(state.namespace),source_material=encode(state.material.result_artifact),
        binding_materials=encode(state.materials),pins=pins,tables=tables,
        counts=_counts(state),
        original_body_bytes_copied=0,loops_unrolled=False,target_executed=False,
        tensor_content_versions_proven=False,effect_membership_closed=False,first_stage_complete=False,
        seconds=time.monotonic()-started)
    state.check()
    if pins!=_pins():raise ValueError('state-view rules changed during publication')
    _durable_bytes(out/'result.json',_json(report),replace=False)
    return report


def read_state_view(path):
    """Rederive all rows against the original material; no trusted caches."""
    path=Path(path).absolute();raw=(path/'result.json').read_bytes();report=json.loads(raw)
    pins=_pins()
    # As with ProgramView, facade/CLI evolution need not invalidate unchanged
    # data. All state/type/solver contracts stay exact and every row is still
    # independently rederived below. Keep the producer SHA as provenance.
    admitted=report['pins']
    if (report['schema'],report['schema_version'])!=('scar.source-binding-state-view',1) or (
            {k:v for k,v in admitted.items() if k!='producer'}!={k:v for k,v in pins.items() if k!='producer'}):
        raise ValueError('state view schema or producer contract differs')
    if (type(admitted.get('producer')) is not str or len(admitted['producer'])!=64
            or any(c not in '0123456789abcdef' for c in admitted['producer'])):
        raise ValueError('state view producer provenance is not a SHA256')
    if (report['original_body_bytes_copied']!=0 or any(report[name] is not False for name in
            ('loops_unrolled','target_executed','tensor_content_versions_proven','effect_membership_closed','first_stage_complete'))):
        raise ValueError('state view claims results outside its static binding scope')
    parent=_artifact(Path(report['catalog'])/'result.json',report['parent']['schema'])
    if encode(parent)!=report['parent']:raise ValueError('state view catalog receipt differs')
    view=ProgramView(report['catalog']);state=view.state(report['unit'])
    if (encode(state.namespace)!=report['namespace'] or encode(state.material.result_artifact)!=report['source_material']
            or encode(state.materials)!=report['binding_materials']):
        raise ValueError('state view source address material differs')
    sentinel=object()
    # First decode the compact tracks, then ask the certified source solver to
    # reconstruct them. Declared IDs alone cannot establish a graph version.
    for row in _table(path,report['tables']['tracks']):
        track=decode(S.StoredBindingTrack,row,record_tags=P.PRODUCTION_RECORD_TAGS)
        state.track(track.source_function,track.namespace,max_states=track.max_states,
            max_stack=track.max_stack,max_updates=track.max_updates)
    rows=_rows(state)
    if set(rows)!=set(report['tables']):raise ValueError('state view table domain differs')
    for name,(cls,expected) in rows.items():
        actual=(decode(cls,row,record_tags=P.PRODUCTION_RECORD_TAGS) for row in _table(path,report['tables'][name]))
        if any(a!=b for a,b in zip_longest(actual,expected,fillvalue=sentinel)):
            raise ValueError('state view source rederivation differs: '+name)
    if _counts(state)!=report['counts']:raise ValueError('state view coverage counts differ')
    state.check()
    if pins!=_pins() or (path/'result.json').read_bytes()!=raw:
        raise ValueError('state view contract changed during read')
    return report,view,state


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--catalog');parser.add_argument('--unit');parser.add_argument('--out')
    parser.add_argument('--read')
    parser.add_argument('--slot',action='append',type=int,default=[],help='original C2 local-binding slot; owner function is resolved mechanically')
    parser.add_argument('--interfaces-only',action='store_true',help='publish addresses without solving local binding tracks')
    args=parser.parse_args()
    if args.read:
        if any((args.catalog,args.unit,args.out,args.slot,args.interfaces_only)):parser.error('--read stands alone')
        report,_,_=read_state_view(args.read)
    else:
        if not all((args.catalog,args.unit,args.out)):parser.error('--catalog --unit --out are required')
        from scar.analysis.source_reference_slice import source_port
        from scar.ir.program import normal_links as F
        state=ProgramView(args.catalog).state(args.unit)
        if args.interfaces_only and args.slot:parser.error('--interfaces-only cannot select slots')
        if not args.slot and not args.interfaces_only:
            from scar.analysis.source_local_state import track_local_reads
            track_local_reads(state)
        for index in dict.fromkeys(args.slot):
            if not 0<=index<len(state.bindings.bindings):parser.error('slot is outside original C2 binding domain')
            slot=state.bindings.bindings[index]
            functions=[f for f in state.source.facts.functions if f.environment.scope==slot.owner]
            if slot.domain!='LOCAL_BINDING' or len(functions)!=1:parser.error('slot needs one owning source function')
            state.track(source_port(state.source.facts,functions[0].value),F.Namespace(F.NamespaceKind.LEXICAL,index,state._name(slot.name)))
        report=publish_state_view(state,args.out)
    print(json.dumps(dict(unit=report['unit'],counts=report['counts'],first_stage_complete=False)))


if __name__=='__main__':main()
