"""Expose retained unresolved method targets through the shared graph.

No unknown operation is invented. The original call/body is already modeled;
its missing target/class/descriptor selection is a field-level obligation.
"""
from collections import defaultdict

from scar.analysis.source_call_view import prepare_source_ports, source_call_site, source_active_scope
from scar.analysis.source_declared_calls import _owners
from scar.analysis.source_reference_slice import source_port
from scar.ir.program.dependencies import DependencyFrontier, DependencyNeighborhood
from scar.ir.program.source_protocol_frontiers import ProtocolCallFrontier
from scar.ir.program.ids import OperationID, ValueID, UseID, ControlPortID, RegionID


class SourceProtocolFrontierProvider:
    def __init__(self, view, materials):
        if view.catalog is None or (view.catalog.path,view.catalog.report)!=(materials.catalog.path,materials.catalog.report):
            raise ValueError('protocol frontiers must share their original source catalog')
        self.view=view; self.materials=materials; self.records={}; self.by_unit=defaultdict(list)
        self.attached=set(); self.points=defaultdict(list); self.scopes={}
        if materials.members is not None:
            for i, _ in enumerate(materials.members.frontiers):
                context, call, evidence, reason=materials.member_frontier(i)
                row=ProtocolCallFrontier(i,context,call,evidence,reason)
                self.records[i]=row; self.by_unit[context.body.unit].append(i)
        self.available_units=frozenset(self.by_unit)
        view.register(self)

    @staticmethod
    def _key(point): return point.namespace,point.node

    def attach(self, unit):
        if unit in self.attached: return
        indices=self.by_unit.get(unit,()); source=self.view.unit(unit); facts=source.facts
        ports=[]; bodies=[]
        for i in indices:
            row=self.records[i]
            if row.call is None: bodies.append(row.context.body)
            else:
                call=row.call.call
                ports.extend(source_port(facts,p) for p in (call.callee,call.result,call.world,call.result_world))
        prepare_source_ports(self.view,ports,bodies=bodies)
        owners=_owners(facts) if any(self.records[i].call is not None for i in indices) else ()
        for i in indices:
            row=self.records[i]
            if row.call is None:
                body=row.context.body; points=(self.view.source_region(unit,body.template,body.region),)
                function=next(f for f in facts.functions if source_port(facts,f.value)==row.context.source_callable)
                self.scopes[i]=(function.body_scope.owner,)
            else:
                call=row.call.call; ordinal=facts.calls.index(call); self.scopes[i]=owners[ordinal]
                # Resolve its actual source operation/callee Use, without
                # inventing an invocation or selecting a target body.
                from types import SimpleNamespace
                site=SimpleNamespace(result=source_port(facts,call.result),callee=source_port(facts,call.callee))
                operation,use,callee=source_call_site(self.view,site)
                points=(operation,use,callee,*(self.view.source_port(source_port(facts,p))
                    for p in (call.result,call.world,call.result_world)))
            for point in points:
                key=self._key(point)
                if i not in self.points[key]: self.points[key].append(i)
        self.attached.add(unit); self.materials.check()

    def at(self, point):
        if type(point.node) not in (OperationID,ValueID,UseID,ControlPortID,RegionID): return ()
        source=self.view.namespaces.get(point.namespace); unit=getattr(source,'unit',None)
        if unit not in self.available_units: return ()
        if unit not in self.attached: self.attach(unit)
        indices=self.points.get(self._key(point),())
        if not indices: return ()
        self.materials.check(); self.view.get(point)
        active=source_active_scope(self.view,point.namespace,point.context)
        return tuple(self.records[i] for i in indices if active is None or active in self.scopes[i])

    def _neighbors(self, point):
        rows=self.at(point)
        frontiers=tuple(DependencyFrontier(point,row.reason,
            'Original member context '+str(row.ordinal)+'; target/class/descriptor selection remains unresolved at '
            +row.evidence.artifact.uri+row.evidence.locator) for row in rows)
        return DependencyNeighborhood(frontiers=frontiers)

    def incoming(self, point): return self._neighbors(point)
    def outgoing(self, point): return self._neighbors(point)

    def summary(self):
        return dict(declared=len(self.records),available_units=len(self.available_units),units=len(self.attached),
            attached_records=len({i for values in self.points.values() for i in values}),
            endpoint_bindings=sum(map(len,self.points.values())),unresolved_targets_resolved=0,
            unknown_nodes_created=0,runtime_dispatch_proven=False)

    def publish(self, out):
        from pathlib import Path
        from scar.analysis.normal_output import write_table
        from scar.analysis.source_stage import _durable_bytes,_durable_mkdir
        from scar.analysis.source_template_links import _json
        from scar.analysis.source_value_flow import _artifact
        from scar.ir.record_codec import encode
        out=Path(out).absolute()
        if out.exists(): raise ValueError('fresh frontier-view output required')
        self.materials.check(); _durable_mkdir(out); shards={}
        for unit,indices in sorted(self.by_unit.items()):
            folder=out/'units'/unit; _durable_mkdir(folder)
            table=write_table(folder/'frontiers.jsonl.gz',(self.records[i] for i in indices))
            shards[unit]=dict(path='units/'+unit,table=table)
        report=dict(schema='scar.source-protocol-frontiers',schema_version=1,shards=shards,
            parent=encode(_artifact(self.materials.member_path/'result.json',self.materials.member_report['schema']))
                if self.materials.member_path is not None else None,
            summary=self.summary(),target_executed=False,first_stage_complete=False)
        self.materials.check(); _durable_bytes(out/'result.json',_json(report),replace=False)
        return report
