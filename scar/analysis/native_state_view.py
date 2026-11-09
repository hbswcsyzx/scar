"""Publish native local state shards without copying canonical native bodies."""
import argparse
from collections import Counter
from hashlib import sha256
from itertools import zip_longest
import json
from pathlib import Path
import time

from scar.analysis.native_state import NativeStateSession,NativeStateProvider
from scar.analysis.native_state_materials import NativeStateMaterials
from scar.analysis.normal_output import write_table
from scar.analysis.source_symbol_variants import _table
from scar.analysis.source_stage import _durable_bytes,_durable_mkdir
from scar.analysis.source_template_links import _json
from scar.analysis.source_value_flow import _artifact
from scar.analysis.program_state_view import _edges
from scar.ir.program import native_state as N,source_state as S
from scar.ir.record_codec import encode,decode


def _pins():
    from scar.analysis import native_state,native_state_materials,program_view
    from scar.ir.program import model,codec
    return {name:sha256(Path(module.__file__).read_bytes()).hexdigest() for name,module in (
        ('publisher',__import__(__name__,fromlist=['__file__'])),('state',native_state),('types',N),
        ('materials',native_state_materials),('facade',program_view),('core_types',model),('core_codec',codec))}


def _rows(provider):
    return dict(addresses=(N.NativeStateAddress,provider.addresses.values()),
        projections=(N.NativeStateProjection,provider.projections.values()),
        accesses=(N.NativeStateAccess,provider.accesses),alias_groups=(N.NativeAliasGroup,provider.groups),
        edges=(S.StoredBindingEdge,_edges(provider)))


def _counts(provider):
    return dict(addresses=len(provider.addresses),projections=len(provider.projections),
        accesses=len(provider.accesses),alias_groups=len(provider.groups),
        relations=sum(len(rows) for rows in provider.out_edges.values()),
        categories=dict(Counter(a.category.value for a in provider.addresses.values())),
        declared_possible_writes=sum(a.declared_may_write is True for a in provider.addresses.values()),
        typed_list_families=sum(any(p.value=='LIST_ELEMENT' for p in a.type_path) for a in provider.addresses.values()))


def publish_native_state(materials,out):
    started=time.monotonic();pins=_pins();out=Path(out).absolute()
    if out.exists():raise ValueError('fresh native-state output required')
    session=NativeStateSession(materials);_durable_mkdir(out);shards={}
    for selector,namespace in session.selectors.items():
        provider=session.providers[namespace];key=sha256(selector.encode()).hexdigest()[:24]
        folder=out/'units'/key;_durable_mkdir(folder)
        tables={name:write_table(folder/(name+'.jsonl.gz'),rows) for name,(_,rows) in _rows(provider).items()}
        shards[selector]=dict(path='units/'+key,namespace=encode(namespace),
            declaration=encode(provider.unit.declaration_fact),counts=_counts(provider),tables=tables)
    materials.check()
    if pins!=_pins():raise ValueError('native local-state producer changed during publication')
    report=dict(schema='scar.native-state-view',schema_version=1,parent=encode(_artifact(materials.path/'result.json',materials.report['schema'])),
        source=str(materials.path),pins=pins,shards=shards,
        counts=dict(units=len(shards),**{key:sum(row['counts'][key] for row in shards.values()) for key in
            ('addresses','projections','accesses','alias_groups','relations','declared_possible_writes','typed_list_families')}),
        alias_candidates_factored=True,canonical_body_bytes_copied=0,
        effect_membership_closed=False,physical_alias_proven=False,logical_versions_proven=False,
        source_call_normalization_proven=False,target_executed=False,first_stage_complete=False,
        seconds=time.monotonic()-started)
    _durable_bytes(out/'result.json',_json(report),replace=False)
    return report,session


def read_native_state(path):
    path=Path(path).absolute();raw=(path/'result.json').read_bytes();report=json.loads(raw);pins=_pins()
    facades={'publisher','facade'}
    if ((report['schema'],report['schema_version'])!=('scar.native-state-view',1)
            or {k:v for k,v in report['pins'].items() if k not in facades}!={k:v for k,v in pins.items() if k not in facades}):
        raise ValueError('native-state source rules or schema differ')
    for name in facades:
        value=report['pins'].get(name)
        if type(value) is not str or len(value)!=64 or any(c not in '0123456789abcdef' for c in value):
            raise ValueError('native-state facade provenance is not a SHA256')
    if (report['alias_candidates_factored'] is not True or report['canonical_body_bytes_copied']!=0
            or any(report[key] is not False for key in ('effect_membership_closed','physical_alias_proven',
                'logical_versions_proven','source_call_normalization_proven','target_executed','first_stage_complete'))):
        raise ValueError('native-state authority exceeds declared local state')
    if encode(_artifact(Path(report['source'])/'result.json',report['parent']['schema']))!=report['parent']:
        raise ValueError('native-state source report receipt differs')
    session=NativeStateSession(NativeStateMaterials(report['source']));sentinel=object()
    if set(session.selectors)!=set(report['shards']):raise ValueError('native-state unit domain differs')
    for selector,namespace in session.selectors.items():
        provider=session.providers[namespace];shard=report['shards'][selector]
        if (shard['path']!='units/'+sha256(selector.encode()).hexdigest()[:24]
                or encode(namespace)!=shard['namespace'] or encode(provider.unit.declaration_fact)!=shard['declaration']
                or _counts(provider)!=shard['counts'] or set(_rows(provider))!=set(shard['tables'])):
            raise ValueError('native-state shard declaration or coverage differs')
        for name,(cls,expected) in _rows(provider).items():
            actual=(decode(cls,row) for row in _table(path/shard['path'],shard['tables'][name]))
            if any(a!=b for a,b in zip_longest(actual,expected,fillvalue=sentinel)):
                raise ValueError('native-state local rederivation differs: '+selector+'/'+name)
    counts=dict(units=len(session.providers),**{key:sum(_counts(p)[key] for p in session.providers.values()) for key in
        ('addresses','projections','accesses','alias_groups','relations','declared_possible_writes','typed_list_families')})
    if counts!=report['counts']:raise ValueError('native-state total coverage differs')
    session.materials.check()
    if pins!=_pins() or (path/'result.json').read_bytes()!=raw:raise ValueError('native-state rules changed during read')
    return report,session


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source');parser.add_argument('--out');parser.add_argument('--read')
    args=parser.parse_args()
    if args.read:
        if args.source or args.out:parser.error('--read stands alone')
        report,_=read_native_state(args.read)
    else:
        if not args.source or not args.out:parser.error('--source and --out are required')
        report,_=publish_native_state(NativeStateMaterials(args.source),args.out)
    print(json.dumps(dict(counts=report['counts'],first_stage_complete=False)))


if __name__=='__main__':main()
