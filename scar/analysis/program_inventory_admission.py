"""Admit static graph inventories under the dependencies they actually used.

The static inventory explicitly does not run reaching-definition fixed
points. Its receipts, producer, graph/state types and all used rules remain
exact; changing only that unused solver cannot invalidate its empty tracks.
Stored bytes and historical pins are never modified.
"""
import json
from pathlib import Path

from scar.analysis.program_state_coverage import _pins,_inventory_index
from scar.analysis.source_declared_catalog import read_source_catalog
from scar.analysis.source_value_flow import _artifact
from scar.ir.record_codec import encode


def compatible_static_pins(plan):
    expected=_pins();actual=plan['pins']
    if actual==expected:return True
    if plan.get('binding_fixed_points_run')is not False:return False
    a=dict(actual,state=dict(actual.get('state',{})));b=dict(expected,state=dict(expected['state']))
    a['state'].pop('definitions',None);b['state'].pop('definitions',None)
    return a==b


def admit_static_inventory(path,*,catalog=None):
    path=Path(path).resolve();raw=(path/'index.json').read_bytes();index=json.loads(raw)
    if index!=_inventory_index(path):raise ValueError('stored inventory differs from complete original shards')
    report=json.loads((path/'result.json').read_bytes());plan=report['plan']
    if not compatible_static_pins(plan):raise ValueError('used static inventory rules differ')
    ignored=plan['pins']!=_pins()
    if ignored and (any(report['counts'].get(k,0)!=0 for k in ('tracks','versions','read_selections'))
            or report['binding_fixed_points_complete']is not False):
        raise ValueError('inventory contains solver results but its solver changed')
    source=read_source_catalog(catalog if catalog is not None else plan['catalog'])
    if (str(source.path)!=plan['catalog']
            or encode(_artifact(source.path/'result.json',source.report['schema']))!=plan['parent']
            or plan['scope']=='CATALOG' and set(plan['selected_units'])!=set(source.fact_store.rows)):
        raise ValueError('static inventory source unit denominator differs')
    if raw!=(path/'index.json').read_bytes():raise ValueError('static inventory changed during admission')
    return dict(index,admission=dict(profile='STATIC_GRAPH_AND_STATE_WITHOUT_BINDING_FIXED_POINTS',
        unused_definition_solver_pin_ignored=ignored,stored_receipts_rewritten=False))
