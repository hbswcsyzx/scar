"""Admit saved binding fixed points into the same source query facade.

Unit records are loaded only when queried. Original ports are projected by
the existing ProgramView; saved binding edges are type/receipt/reference
checked without repeating their fixed points. Independent replay is explicit.
"""
from collections import Counter
import json
from pathlib import Path

from scar.analysis.source_observed_state import SCHEMA,_pins
from scar.analysis.program_state_view import _pins as state_pins
from scar.analysis.source_consumer_parents import _stamp
from scar.analysis.source_declared_catalog import _check
from scar.analysis.source_symbol_variants import _table
from scar.analysis.source_value_flow import _artifact
from scar.ir.record_codec import encode
from scar.ir.program.dependencies import DependencyNeighborhood as Neighborhood


class SourceObservedStateProvider:
    def __init__(self,view,path,*,index=None):
        self.view=view;self.path=Path(path).resolve();self.loaded={};self.headers={};self.guards={}
        self.report=r=json.loads((self.path/'result.json').read_bytes());plan=r['plan']
        if ((r['schema'],r['schema_version'],plan['pins'])!=(SCHEMA,1,_pins())
                or any(r[k]is not False for k in ('source_bodies_copied','loops_unrolled',
                    'actual_frame_or_tensor_contents_proven','opaque_writers_excluded','target_executed','first_stage_complete'))):
            raise ValueError('observed state schema, implementation or authority differs')
        _check(plan['parent'])
        if json.loads((self.path/'plan.json').read_bytes())!=plan:
            raise ValueError('observed state plan differs from publication')
        artifact=_artifact(view.catalog.path/'result.json',view.catalog.report['schema'])
        if encode(artifact)!=plan['catalog']:raise ValueError('observed state uses another original catalog')
        if index is None:
            from scar.analysis.source_observed_interfaces import ObservedFunctionInterfaceStore
            index=ObservedFunctionInterfaceStore(Path(plan['parent']['path']).parent).index
        if (index.codes.targets.source_sha256!=plan['run_scope']
                or index.view.catalog.path!=view.catalog.path):
            raise ValueError('observed state index uses another catalog or actual capture')
        actual={(e.invocation.process_id,e.code) for e in index.codes.trace.entries};links=[];units=set()
        for row in index.codes.records.values():
            captures=tuple(c for c in row.captures if (c.process_id,c.code.key) in actual)
            if captures:
                units.add(row.function.unit)
                links.append(dict(function=encode(row.function),code_link=encode(row.id),
                    function_fact=encode(row.function_fact),captured_codes=encode(captures)))
        key=lambda row:json.dumps(row,sort_keys=True)
        if sorted(links,key=key)!=sorted(plan['functions'],key=key) or sorted(units)!=plan['units']:
            raise ValueError('saved binding selection differs from actual code body alternatives')
        if {row['unit'] for row in r['units']}!=units or len(r['units'])!=len(units):
            raise ValueError('observed binding unit denominator differs')
        totals=Counter()
        for row in r['units']:
            unit=row['unit'];path=self.path/'units'/unit/'result.json'
            if row['state']['path']!=str(path):raise ValueError('observed state shard path differs')
            _check(row['state']);header=json.loads(path.read_bytes())
            if ((header['schema'],header['schema_version'],header['unit'],header['pins'])!=
                    ('scar.source-state-view',1,unit,state_pins())
                    or header['parent']!=plan['catalog'] or header['counts']!=row['counts']):
                raise ValueError('observed state shard domain or implementation differs')
            self.headers[unit]=header;self.guards[path]=_stamp(path)
            totals.update({k:v for k,v in row['counts'].items() if type(v)is int})
        if dict(totals)!=r['counts']:raise ValueError('observed state aggregate differs from unit records')
        for name in ('result.json','plan.json'):self.guards[self.path/name]=_stamp(self.path/name)
        self.guards[Path(plan['parent']['path'])]=_stamp(Path(plan['parent']['path']))
        self.index=index;self.check();view.register(self)

    def check(self):
        if any(_stamp(path)!=stamp for path,stamp in self.guards.items()):
            raise ValueError('admitted observed state publication changed')
        self.index.codes._check_trace()

    def ensure(self,unit):
        self.check()
        if unit in self.loaded:return self.loaded[unit]
        from scar.analysis.source_stored_bindings import StoredBindingVersions
        header=self.headers[unit];folder=self.path/'units'/unit
        summary=next(row for row in self.report['units'] if row['unit']==unit)
        state=StoredBindingVersions(self.view,folder,header,summary)
        self.loaded[unit]=state;self.guards.update(state.guards);self.check();return state

    def _state(self,point):
        source=self.view.namespaces.get(point.namespace)
        if source is None or source.unit not in self.headers:return None
        return self.ensure(source.unit)

    def incoming(self,point):
        state=self._state(point);return Neighborhood() if state is None else state.incoming(point)
    def outgoing(self,point):
        state=self._state(point);return Neighborhood() if state is None else state.outgoing(point)
    def describe(self,point):
        state=self._state(point)
        if state is None:return None
        return state.describe(point)
    def _owner(self,point):
        state=self._state(point)
        if state is None:raise ValueError('point is outside observed binding state units')
        return state
    def original(self,point):return self._owner(point).original(point)
    def expand(self,point):return self._owner(point).expand(point)
    def explain(self,point):return self._owner(point).explain(point)
