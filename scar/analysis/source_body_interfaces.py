"""Project every source body protocol onto its original shared graph ports.

Entry, completion, suspension and resume interfaces are read from sealed
recipes. No function-name matching, runtime binding, body copy or unrolling.
"""
from collections import Counter, defaultdict
from dataclasses import replace
from concurrent.futures import ProcessPoolExecutor
from hashlib import sha256
import argparse
import json
import multiprocessing
from pathlib import Path
import time
from types import MappingProxyType
from typing import get_args

from scar.analysis.source_connection_contracts import body_entry_rules, validate_connection_plan
from scar.analysis.source_productions import _digest as _plan_digest
from scar.analysis.source_namespace_interfaces import NamespacePlanView
from scar.analysis.program_view import ProgramView, _digest
from scar.analysis.source_consumer_parents import _stamp
from scar.analysis.source_symbol_variants import _table
from scar.analysis.source_stage import _durable_bytes, _durable_mkdir
from scar.analysis.source_template_links import _json
from scar.analysis.normal_output import write_table
from scar.analysis.source_value_flow import _artifact
from scar.ir.program import source_productions as P, normal_graph as G
from scar.ir.program import source_body_interfaces as R
from scar.ir.program.normal_targets import Body
from scar.ir.program.ids import ProviderID
from scar.ir.record_codec import encode, decode


SCHEMA = 'scar.source-body-interfaces'
_WORKER = None


def _entry_rules():
    rules = dict(body_entry_rules())
    if set(rules) != set(get_args(R.BodyEntryInstruction)):
        raise ValueError('body interface union differs from the complete entry instruction domain')
    return rules


def extract_body_interfaces(unit, plan, *, plan_sha256=None):
    """One pass per plan, including nested type factories and lazy requests.

    World ports are taken from types. A resume delivers a fresh world before
    its saved-reference suffix; it does not bind the function formals again.
    """
    rules = _entry_rules()
    validate_connection_plan(plan)
    digest = _plan_digest(encode(plan, record_tags=P.PRODUCTION_RECORD_TAGS))
    if plan_sha256 is not None and digest != plan_sha256:
        raise ValueError('body interface plan differs from its original template receipt')
    view = NamespacePlanView(unit, plan)
    entries = [step for step in plan.steps if type(step.instruction) in rules]
    suspensions = [step for step in plan.steps if type(step.instruction) is P.SuspendExecution]
    ancestor_cache = {}
    def ancestors(region):
        if region not in ancestor_cache:
            chain = []; current = region
            while current is not None and current not in ancestor_cache:
                chain.append(current); current = view.regions[current].parent
            inherited = frozenset() if current is None else ancestor_cache[current]
            for current in reversed(chain):
                inherited = inherited | {current}; ancestor_cache[current] = inherited
        return ancestor_cache[region]
    result = []
    for step in entries:
        region = view.regions[step.region]; owner = view.owner(region.id)
        body = Body(unit, view.key, region.id)
        parameters = tuple(view.value(P.ProductionParameter(region.id, i))
            for i in range(len(region.parameters)))
        ingresses = [R.SourceBodyIngress(body, parameters, region.parameters)]
        handoffs = []
        for suspended in suspensions:
            if (owner.owner != view.owner(suspended.region).owner
                    or region.id not in ancestors(suspended.region)):
                continue
            instruction = suspended.instruction
            arguments = tuple(view.value(value) for value in suspended.arguments)
            types = tuple(view.emitter.value(value)[1] for value in suspended.arguments)
            suspension=view.site(suspended)
            handoffs.append(R.SourceBodySuspension(suspension, instruction.suspension, arguments, types))
            for route in instruction.routes:
                resume = view.regions[route.region]
                parameters = tuple(view.value(P.ProductionParameter(resume.id, i))
                    for i in range(len(resume.parameters)))
                payload = len(resume.parameters) - len(instruction.saved)
                if payload < 0:
                    raise ValueError('resume parameters cannot hold their original saved references')
                saved = tuple((parameters[i], view.value(value))
                    for i, value in enumerate(instruction.saved, payload))
                ingresses.append(R.SourceBodyIngress(Body(unit,view.key,resume.id), parameters, resume.parameters,
                    suspension, route.kind, saved))
        completions = tuple(R.SourceBodyCompletion(completion.kind, completion.target, completion.types,
            tuple(view.gp(view.emitter.port(region.id, G.PortKind.RESULT, i, completion))
                for i in range(len(completion.types))),
            view.gp(view.emitter.port(region.id, G.PortKind.EXIT, completion=completion)))
            for completion in region.completions)
        payload = (SCHEMA, body, owner, digest, step.id, step.instruction,
            tuple(ingresses), completions, tuple(handoffs))
        result.append(R.SourceBodyInterface(ProviderID(_digest(payload)), body, owner, digest,
            step.id, step.instruction, tuple(ingresses), completions, tuple(handoffs)))
    return tuple(result)


def unit_body_interfaces(view, unit):
    """Decode each template once; no normal-graph expansion is required."""
    source = view.unit(unit); material = source.material
    keys = tuple(material.interfaces['nodes'])
    resolver=BodyInterfaceResolver(view)
    resolver.seed(unit,material.plans(keys))
    bodies=tuple(resolver.heads)
    result=tuple(resolver.resolve(body) for body in bodies)
    if len({interface.id for interface in result}) != len(result):
        raise ValueError('duplicate source body interface identity')
    source.check()
    return result


class BodyInterfaceResolver:
    """Share one original plan decode across all requested bodies in it."""
    def __init__(self, view):
        self.view = view; self.plans = {}; self.heads = {}; self.interfaces = {}

    def seed(self,unit,plans):
        material=self.view.unit(unit).material
        for key,plan in plans.items():
            if (unit,key) in self.plans:continue
            rows=extract_body_interfaces(unit,plan,
                plan_sha256=material.interfaces['nodes'][key].origin.plan_sha256)
            self.heads.update((row.body,row) for row in rows)
            self.plans[unit,key]=NamespacePlanView(unit,plan)

    def plan(self, unit, key):
        identity = unit,key
        source = self.view.unit(unit)
        if identity not in self.plans:
            material = source.material
            plan = material.plans((key,))[key]
            self.seed(unit,{key:plan})
        source.check()
        return self.plans[identity]

    def resolve(self, body):
        self.plan(body.unit,body.template)
        if body in self.interfaces:return self.interfaces[body]
        if body not in self.heads:
            raise ValueError('source body has no original entry protocol')
        head=self.heads[body]; material=self.view.unit(body.unit).material
        pending=[(body.template,body.region)]; visited=set(); suspensions={}; ingresses=[head.ingresses[0]]
        # Traverse shared template references, never dynamic iterations. A
        # nested declaration with another code owner remains its own body.
        while pending:
            key,root=pending.pop()
            if (key,root) in visited:continue
            visited.add((key,root)); context=self.plan(body.unit,key)
            if context.owner(root).owner != head.scope.owner:continue
            children=defaultdict(list)
            for region in context.plan.regions:
                if region.parent is not None:children[region.parent].append(region.id)
            regions=[root]; selected=set()
            while regions:
                region=regions.pop()
                if context.owner(region).owner != head.scope.owner:continue
                selected.add(region); regions.extend(children[region])
            for step in context.plan.steps:
                if step.region not in selected:continue
                link=material.interfaces['links'].get((key,step.id))
                if link is not None:
                    callee=material.interfaces['nodes'][link.callee]
                    pending.append((link.callee,callee.root))
                if type(step.instruction) is not P.SuspendExecution:continue
                site=context.site(step)
                if site in suspensions:continue
                arguments=tuple(context.value(value) for value in step.arguments)
                types=tuple(context.emitter.value(value)[1] for value in step.arguments)
                suspensions[site]=R.SourceBodySuspension(site,step.instruction.suspension,arguments,types)
                for route in step.instruction.routes:
                    region=context.regions[route.region]
                    parameters=tuple(context.value(P.ProductionParameter(region.id,i)) for i in range(len(region.parameters)))
                    payload=len(parameters)-len(step.instruction.saved)
                    saved=tuple((parameters[i],context.value(value)) for i,value in enumerate(step.instruction.saved,payload))
                    ingresses.append(R.SourceBodyIngress(Body(body.unit,key,region.id),parameters,region.parameters,
                        site,route.kind,saved))
        payload=(SCHEMA,head.body,head.scope,head.plan_sha256,head.entry,head.instruction,
            tuple(ingresses),head.completions,tuple(suspensions.values()))
        result=replace(head,id=ProviderID(_digest(payload)),ingresses=tuple(ingresses),suspensions=tuple(suspensions.values()))
        self.interfaces[body]=result
        return result


def body_interface(view, body):
    """Read one exact original body, independent of FunctionFact existence."""
    return BodyInterfaceResolver(view).resolve(body)


def _modules():
    from scar.analysis import source_connection_contracts, source_namespace_interfaces
    from scar.analysis import source_productions, program_view
    from scar.ir import record_codec
    return (
        ('producer', __import__(__name__, fromlist=['__file__'])), ('types', R),
        ('entry_contract', source_connection_contracts), ('original_ports', source_namespace_interfaces),
        ('productions', P), ('port_types', G), ('plan_reader',source_productions),
        ('graph_projection',program_view), ('codec',record_codec))


def _pins():
    return {name: sha256(Path(module.__file__).read_bytes()).hexdigest() for name,module in _modules()}


def _counts(rows):
    return dict(interfaces=len(rows), entries=len(rows),
        resume_ingresses=sum(len(row.ingresses)-1 for row in rows),
        suspensions=sum(len(row.suspensions) for row in rows),
        parameters=sum(len(ingress.parameters) for row in rows for ingress in row.ingresses),
        completion_ports=sum(len(completion.ports) for row in rows for completion in row.completions),
        kinds=dict(Counter(type(row.instruction).__name__ for row in rows)))


def _initialize(catalog, out):
    global _WORKER
    _WORKER = ProgramView(catalog), Path(out)


def _unit(unit):
    view, out = _WORKER; started = time.monotonic()
    rows = unit_body_interfaces(view, unit)
    folder = out/'units'/unit; _durable_mkdir(folder)
    table = write_table(folder/'interfaces.jsonl.gz', rows)
    result = dict(path='units/'+unit, interfaces=table, counts=_counts(rows),
        seconds=time.monotonic()-started)
    # Bodies stay in their original files; release decoded plans between units.
    view.units.clear(); view.namespaces.clear()
    return unit, result


def build_body_interfaces(catalog, out, *, units=(), jobs=4):
    started = time.monotonic(); out = Path(out).absolute()
    if out.resolve() != out or out.exists() or type(jobs) is not int or not 1 <= jobs <= 32:
        raise ValueError('body interfaces require fresh output and jobs in [1,32]')
    view = ProgramView(catalog); all_units = tuple(view.catalog.fact_store.rows)
    selected = tuple(sorted(set(units) if units else all_units))
    if not set(selected) <= set(all_units):
        raise ValueError('body unit selection is outside its original source catalog')
    parent = _artifact(view.catalog.path/'result.json', view.catalog.report['schema'])
    pins = _pins(); _durable_mkdir(out)
    with ProcessPoolExecutor(max_workers=min(jobs,len(selected) or 1),
            mp_context=multiprocessing.get_context('spawn'), initializer=_initialize,
            initargs=(str(view.catalog.path),str(out))) as pool:
        shards = dict(pool.map(_unit, selected))
    if pins != _pins() or _artifact(view.catalog.path/'result.json',parent.schema) != parent:
        raise ValueError('body interface declaration or source catalog changed')
    report = dict(schema=SCHEMA, schema_version=1, catalog=encode(parent), pins=pins,
        scope='EXPLICIT_UNITS' if units else 'DECLARED_CATALOG', units=list(selected), shards=shards,
        counts={key:sum(row['counts'][key] for row in shards.values()) for key in (
            'interfaces','entries','resume_ingresses','suspensions','parameters','completion_ports')},
        target_executed=False, source_bodies_copied=False, runtime_bindings_proven=False,
        first_stage_complete=False, seconds=time.monotonic()-started)
    _durable_bytes(out/'result.json',_json(report),replace=False)
    return report


class SourceBodyInterfaceStore:
    """Lazy original-source replay, cached per immutable unit and read session."""
    def __init__(self, path, *, view=None):
        self.path = Path(path).resolve(); report = self.path/'result.json'
        self.raw = report.read_bytes(); self.report = json.loads(self.raw)
        r = self.report
        if ((r['schema'],r['schema_version'],r['pins']) != (SCHEMA,1,_pins())
                or any(r[name] is not False for name in ('target_executed','source_bodies_copied',
                    'runtime_bindings_proven','first_stage_complete'))):
            raise ValueError('body interface declaration schema or implementation differs')
        self.view = ProgramView(Path(r['catalog']['uri']).parent) if view is None else view
        if encode(_artifact(self.view.catalog.path/'result.json',r['catalog']['schema'])) != r['catalog']:
            raise ValueError('body interfaces refer to another original source catalog')
        available = set(self.view.catalog.fact_store.rows)
        if (r['scope'] not in ('DECLARED_CATALOG','EXPLICIT_UNITS')
                or tuple(r['shards']) != tuple(r['units']) or not set(r['units']) <= available
                or r['scope']=='DECLARED_CATALOG' and set(r['units']) != available):
            raise ValueError('body interface unit denominator differs from the declared catalog')
        if r['counts'] != {key:sum(row['counts'][key] for row in r['shards'].values()) for key in r['counts']}:
            raise ValueError('body interface totals differ from declared unit counts')
        self.guards = {report:_stamp(report)}; self.loaded = {}
        self.guards.update((Path(module.__file__),_stamp(Path(module.__file__))) for _,module in _modules())
        def freeze(value):
            if type(value) is dict:return MappingProxyType({key:freeze(item) for key,item in value.items()})
            if type(value) is list:return tuple(map(freeze,value))
            return value
        self.report = self._frozen_report = freeze(r)

    def check(self):
        if self.report is not self._frozen_report or any(_stamp(path) != stamp for path,stamp in self.guards.items()):
            raise ValueError('admitted body interface material changed')

    def read_unit(self, unit):
        self.check()
        if unit in self.loaded:
            self.view.unit(unit).check(); return self.loaded[unit]
        shard = self.report['shards'][unit]
        if shard['path'] != 'units/'+unit or shard['interfaces']['path'] != 'interfaces.jsonl.gz':
            raise ValueError('body interface shard location differs')
        folder = self.path/shard['path']; path = folder/shard['interfaces']['path']; before = _stamp(path)
        rows = tuple(decode(R.SourceBodyInterface,row,record_tags=P.PRODUCTION_RECORD_TAGS)
            for row in _table(folder,shard['interfaces']))
        expected = unit_body_interfaces(self.view,unit)
        if rows != expected or _counts(rows) != shard['counts'] or _stamp(path) != before:
            raise ValueError('body interfaces differ from the complete original source entry/exit protocols')
        self.guards[path] = before; self.loaded[unit] = rows; self.check()
        return rows


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument('--catalog'); inputs.add_argument('--read')
    parser.add_argument('--out', required=True); parser.add_argument('--unit',action='append',default=[])
    parser.add_argument('--jobs',type=int,default=4)
    args = parser.parse_args(argv)
    if args.read:
        started=time.monotonic(); store=SourceBodyInterfaceStore(args.read)
        for unit in store.report['units']:store.read_unit(unit)
        store.check()
        report=dict(schema=SCHEMA+'.readback',schema_version=1,status='VERIFIED',
            parent=encode(_artifact(store.path/'result.json',SCHEMA)),units=len(store.loaded),
            counts=dict(store.report['counts']),target_executed=False,first_stage_complete=False,
            seconds=time.monotonic()-started)
        out=Path(args.out); out.parent.mkdir(parents=True,exist_ok=True)
        _durable_bytes(out,_json(report),replace=False)
    else:
        report=build_body_interfaces(args.catalog,args.out,units=tuple(args.unit),jobs=args.jobs)
    print(json.dumps(report,indent=2))
    return 0


if __name__=='__main__':
    raise SystemExit(main())
