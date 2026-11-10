"""Lazy resource interfaces over original F4 identities in a ProgramView.

Host interpreter/object-representation demands are conditional on execution.
Device candidates require the retained native normalization/type interface;
source effect labels alone never manufacture a GPU, copy or file operation.
Hardware projections reference the existing inventory without probing the OS.
"""
from collections import defaultdict
from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path

from scar.analysis.build_resources import BuildResourceProvider, _key
from scar.analysis.program_view import SOURCE_REPRESENTATION, _digest
from scar.analysis.source_effects import classify_instruction
from scar.analysis.source_resource_graph import SourceResourceGraph, _target, _pins as resource_pins
from scar.analysis.source_world_returns import _table_ref
from scar.analysis.source_reference_slice import source_port
from scar.ir.program import build_f4_resources as R, source_effects as F
from scar.ir.program import source_productions as P, normal_graph as G, model as M, view as V
from scar.ir.program import target_hardware as H, source_resource_graph as S
from scar.ir.program.resources import ResourceDefinition, ExternalResource, ResourceKind, ResourceRole
from scar.ir.program.ids import OperationID, RegionID, ResourceDefinitionID
from scar.ir.program.dependencies import (
    DependencyPoint as Point, DependencyEdge as Edge, DependencyKind as K,
    DependencyMeaning as Meaning, DependencyStrength as Strength,
    DependencyCondition as Condition, DependencyEvidence as Evidence,
    DependencyNeighborhood as Neighborhood)
from scar.ir.program.source_references import SourceArtifactLocator
from scar.ir.program.providers import ProviderArtifact
from scar.ir.record_codec import encode


SCHEMA = 'scar.build-f4-resource-interfaces.v1'
_HOST_GUARDS = ('SOURCE_SCOPE_AND_OPERATION_OCCURRENCE_ENTERED',
    'PYTHON_HOST_INTERPRETER_AND_REFERENCE_REPRESENTATION_INTERFACE',
    'NO_TENSOR_STORAGE_ALLOCATION_PLACEMENT_OR_TRANSFER_PROOF')


class _Requirements(BuildResourceProvider):
    # Reuse existing resource records, pool identities and contextual adjacency.
    # All source demand edges retain scope/occurrence conditions in payload too.
    def _edge(self, source, target, rule, *, condition=None, may=False, guards=(), evidence=()):
        conditions = (*_HOST_GUARDS, *guards, *((condition,) if condition else ()))
        edge = Edge(source, target, K.RESOURCE, Meaning.DEPENDENCE,
            (Evidence(rule, (source.namespace.graph, *evidence), (source, target)),),
            tuple(Condition(SCHEMA, name, target) for name in dict.fromkeys(conditions)), Strength.MAY)
        self.edges.append(edge); self._incoming[target].append(edge); self._outgoing[source].append(edge)


class LazyF4Resources:
    """Demand individual operations or one region's direct operation records.

    ``source_resources`` is optional (path or authenticated SourceResourceGraph).
    Its per-unit native routes load only when a matching source call is demanded.
    ``target`` optionally overrides the retained hardware snapshot; otherwise the
    resource report's target, or the existing canonical target-hardware, is used.
    No source-resource material means external device/file interfaces stay open.
    """
    relation_kinds = frozenset((K.RESOURCE,))

    def __init__(self, view, source_resources=None, *, target=None):
        self.view = view; self.provider = _Requirements(view)
        self.interfaces = {}; self.hardware = {}; self.routes = []
        self._sources = {}; self._guard = {}; self._seen = set(); self._unit_routes = {}
        self.gaps = []; self._resource_error = None
        self.resource_store = source_resources if isinstance(source_resources, SourceResourceGraph) else None
        self.resource_path = (self.resource_store.path if self.resource_store is not None
            else None if source_resources is None else Path(source_resources).absolute())
        self.resource_report = None
        if self.resource_path is not None:
            raw = self._remember(self.resource_path/'result.json'); report = json.loads(raw)
            if (report['schema'], report['schema_version'], report['pins']) != (
                    'scar.source-resource-graph', 1, resource_pins()):
                raise ValueError('F4 resources need the original source-resource rules/report')
            if any(report[name] is not False for name in (
                    'runtime_placement_proven','physical_resource_use_proven','transfers_observed',
                    'allocations_observed','target_executed','first_stage_complete')):
                raise ValueError('source resource candidates cannot grant runtime authority')
            self.resource_report = report
            if target is not None and Path(target).absolute() != Path(report['target']).absolute():
                raise ValueError('F4 resource and explicit target snapshots differ')
            target = report['target']
        if target is None:
            candidate = Path(__file__).resolve().parents[2]/'artifacts/current/queries/target-hardware'
            target = candidate if (candidate/'result.json').is_file() else None
        self.target = None; self.target_resources = (); self.connections = (); self.paths = ()
        if target is not None:
            self.target, self.target_resources = _target(target)
            self.connections = self.target.connections(); self.paths = self.target.paths()
            raw = self._remember(self.target.path/'result.json')
            artifact = ProviderArtifact(str(self.target.path/'result.json'), sha256(raw).hexdigest(),
                len(raw), self.target.report['schema'])
            self.target_ref = artifact
            self.target_locator = SourceArtifactLocator(artifact, artifact.sha256, artifact.size_bytes, 'canonical-json')
            self._remember(Path(self.target.report['inventory']['uri']))
            for receipt in (*self.target.report['nodes'].values(), self.target.report['connections'], self.target.report['paths']):
                self._remember(self.target.path/receipt['path'])
        self._rules = self._pins()
        view.register(self)

    @staticmethod
    def _pins():
        from scar.analysis import build_resources, source_effects, source_resource_graph, target_graph
        return tuple((module.__file__, sha256(Path(module.__file__).read_bytes()).hexdigest())
            for module in (build_resources, source_effects, source_resource_graph, target_graph, R))

    def _remember(self, path):
        path = Path(path).absolute(); raw = path.read_bytes()
        if path in self._guard and self._guard[path] != raw:
            raise ValueError('F4 resource material changed during admission')
        self._guard[path] = raw; return raw

    def check(self):
        if self._pins() != self._rules or any(path.read_bytes() != raw for path, raw in self._guard.items()):
            raise ValueError('F4 resource rules or admitted materials changed')
        for source in self._sources.values(): source.check()
        if self.resource_store is not None: self.resource_store.validate()

    def _hardware(self, source):
        if self.target is None: return
        if any(p.namespace == source.namespace for p in self.hardware): return
        root = Point(source.namespace, source.namespace.root, None); points = {}
        for record in self.target_resources:
            if type(record) is H.CpuExecutor: kind, role = ResourceKind.CPU, ResourceRole.EXECUTOR
            elif type(record) is H.Accelerator: kind, role = ResourceKind.GPU, ResourceRole.EXECUTOR
            elif type(record) is H.MemoryDomain: kind, role = ResourceKind.MEMORY, ResourceRole.MEMORY_POOL
            else: kind, role = ResourceKind.STORAGE, ResourceRole.STORAGE_ENDPOINT
            identity = ResourceDefinitionID(_digest((SCHEMA, self.target_ref, record.id)))
            point = Point(source.namespace, identity, None)
            definition = ResourceDefinition(identity, kind, role,
                ExternalResource(source.namespace.root, 'target-snapshot:'+str(record.id)))
            self.provider._record(point, definition, root)
            self.hardware[point] = R.F4TargetResource(definition, H.TargetResourceRef(self.target_ref, record.id))
            points[record.id] = point
        for connection in self.connections:
            pairs = ((connection.source,connection.target),)
            if connection.bidirectional: pairs += ((connection.target,connection.source),)
            for a,b in pairs:
                self.provider._edge(points[a],points[b],'scar.build.f4.retained-hardware-topology.v1',
                    guards=(*connection.conditions,'RETAINED_TOPOLOGY_'+connection.kind.value,
                        'HARDWARE_SNAPSHOT_LINK_NOT_OBSERVED_TRANSFER'), evidence=(self.target_locator,))

    def _target_point(self, source, reference):
        self._hardware(source)
        matches = [p for p,r in self.hardware.items() if p.namespace == source.namespace and r.target == reference]
        if len(matches) != 1: raise ValueError('resource option is outside the retained target snapshot')
        return matches[0]

    def _host_targets(self, source, operation):
        if self.target is None: return
        for record in self.target_resources:
            name = 'cpu' if type(record) is H.CpuExecutor else (
                'dram' if type(record) is H.MemoryDomain and record.kind is H.MemoryKind.HOST else None)
            if name is None: continue
            pool = self.provider.pools.get((source.namespace, name))
            if pool is not None:
                target = self._target_point(source,H.TargetResourceRef(self.target_ref,record.id))
                edge_key = target,pool
                if edge_key in self._host_edges: continue
                self._host_edges.add(edge_key)
                self.provider._edge(target,pool,'scar.build.f4.host-pool-target-candidate.v1',
                    guards=('HOST_AFFINITY_NUMA_AND_MEMORY_ACCESS_POLICY_SELECT_RECORDED_TARGET',
                        'INVENTORY_CAPACITY_NOT_AVAILABLE_ALLOCATION_BUDGET'), evidence=(self.target_locator,))

    def _resource_unit(self, source):
        unit = source.unit
        if self._resource_error is not None: return ()
        if unit in self._unit_routes: return self._unit_routes[unit]
        if self.resource_report is None or unit not in self.resource_report['shards']:
            self._unit_routes[unit] = (); return ()
        if self.resource_store is None: self.resource_store = SourceResourceGraph(self.resource_path)
        store = self.resource_store
        declared = json.loads(store.native.parents.source_raw)
        if self.view.catalog is None or Path(declared['catalog']).absolute() != self.view.catalog.path:
            raise ValueError('F4 resource normalization belongs to a different source catalog')
        # The source catalog is itself an original parent of the declaration.
        expected = declared.get('parent')
        if expected is not None:
            actual = self._remember(self.view.catalog.path/'result.json')
            if (expected['uri'],expected['sha256'],expected['size_bytes']) != (
                    str(self.view.catalog.path/'result.json'),sha256(actual).hexdigest(),len(actual)):
                raise ValueError('F4 resource source catalog receipt differs')
        routes = store.read_unit(unit); normalized = store.native.read_unit(unit)
        shard = store.native.report['shards'][unit]; folder = store.native.path/shard['path']
        inputs = {_table_ref(folder,shard['tables']['inputs'],'scar.source-native-input-normalization',i):r
            for i,r in enumerate(normalized.inputs)}
        outputs = {_table_ref(folder,shard['tables']['outputs'],'scar.source-native-output-normalization',i):r
            for i,r in enumerate(normalized.outputs)}
        resources = []
        for i, route in enumerate(routes):
            value = store.rows['values'][route.value]
            options = tuple(r for r in store.rows['options'] if r.value == route.value)
            if route.normalization in inputs:
                normal = inputs[route.normalization]; call = normal.dependency.call
                endpoints = normal.dependency.actuals; guards = (*normal.dependency.conditions,
                    'CONVERSION_DEPENDENCY_NOT_PYTHON_OBJECT_STORAGE_PLACEMENT')
            elif route.normalization in outputs:
                normal = outputs[route.normalization]; call = normal.result; endpoints = (normal.result,)
                guards = (*normal.conditions,'WRAPPED_MEMBER_NOT_PYTHON_CONTAINER_DEVICE_STORAGE')
            else: raise ValueError('source resource route lost its original normalization row')
            resources.append((call,endpoints,route,value,options,guards,_table_ref(store.path/store.report['shards'][unit]['path'],
                store.report['shards'][unit]['tables']['routes'],'scar.source-resource-route',i)))
            self._remember(Path(value.evidence.artifact.uri))
        for receipt in store.report['tables'].values():
            # Only the five shared metadata tables and the selected unit shard.
            if receipt['path'].startswith('units/') and not receipt['path'].startswith('units/'+unit+'/'): continue
            self._remember(store.path/receipt['path'])
        for receipt in shard['tables'].values(): self._remember(folder/receipt['path'])
        self._unit_routes[unit] = tuple(resources); return self._unit_routes[unit]

    def _add(self, source, point):
        point = _key(point)
        if point in self._seen: return
        original = source.records.get(point.node)
        if type(original) is not P.ProductionStep: return
        rule = classify_instruction(original.instruction)
        refs=[];worlds=[]
        for node in source.nodes.values():
            if node.owner is None or node.owner.node != point.node: continue
            if node.role not in (V.ProgramNodeRole.ARGUMENT,V.ProgramNodeRole.RESULT): continue
            if type(node.value_type) is M.ValueType and node.value_type.kind is M.ValueKind.REFERENCE: refs.append(node.point)
            elif type(node.value_type) is M.ValueType and node.value_type.kind is M.ValueKind.STATE: worlds.append(node.point)
        structural = rule.resolution in (F.EffectResolution.REGION_COMPOSITION,
            F.EffectResolution.COMPILE_INPUT,F.EffectResolution.DEFERRED_DECLARATION)
        self.interfaces[point] = R.F4ResourceInterface(point,rule,tuple(refs),tuple(worlds),structural)
        self._seen.add(point)
        if structural:
            self.provider._frontier(point,'F4_STRUCTURAL_OR_COMPILER_INTERFACE_HAS_NO_SEPARATE_RUNTIME_RESOURCE_DEMAND',
                'Original control/declaration interfaces remain shared; resolve their entered primitive bodies separately.')
            return
        self.provider.add_operation(point,tuple(refs),original)
        self._host_targets(source,point)
        try:
            resource_rows = self._resource_unit(source)
        except (OSError, ValueError) as error:
            # Optional source/native material may be stale; host declarations
            # remain usable while the precise admission failure stays visible.
            self._resource_error = type(error).__name__+': '+str(error)
            self.gaps.append(dict(layer='source_resources',kind=type(error).__name__,detail=str(error)))
            self.resource_store = None; self._unit_routes.clear(); resource_rows = ()
        if self._resource_error is not None:
            self.provider._frontier(point,'OPTIONAL_SOURCE_RESOURCE_MATERIAL_UNAVAILABLE',self._resource_error)
        for call,endpoints,route,value,options,guards,evidence in resource_rows:
            if call.port.template != source.nodes[point.node].anchor.template or call.port.owner != original.id: continue
            actuals=tuple(self.view.source_port(p) for p in endpoints) or (point,)
            for option in options:
                target=self._target_point(source,option.target)
                conditions=(*route.conditions,*guards,*option.conditions,
                    'RETAINED_NAMED_BINDING_AND_NATIVE_SCHEMA_ALTERNATIVE_SELECTED',
                    'NO_PARSER_ACCEPTANCE_RUNTIME_DISPATCH_OR_STORAGE_IDENTITY_PROOF')
                record=R.F4ResourceRoute(point,actuals,route.normalization,evidence,value,option.target,conditions)
                self.routes.append(record)
                for endpoint in actuals:
                    self.provider._edge(target,endpoint,'scar.build.f4.original-native-resource-option.v1',
                        guards=conditions,evidence=(self.target_locator,))
            if not endpoints:
                self.provider._frontier(point,'NATIVE_RESOURCE_ARGUMENT_SOURCE_REMAINS_OPEN',
                    'A declared default, receiver or conversion has no original source actual; no constant value is invented.')

    def demand(self, point):
        if point.namespace.representation != SOURCE_REPRESENTATION: return
        source=self.view.namespaces.get(point.namespace)
        if source is None: return
        source.check(point); self._sources[source.namespace]=source
        if not hasattr(self,'_host_edges'): self._host_edges=set()
        self._hardware(source)
        if point.node in self.provider.records: self.check(); return
        if point.node not in source.nodes: return
        source.ensure(point); original=source.records[point.node]
        if type(original) is G.Port:
            point=source._node(original.template,original.owner); original=source.records[point.node]
        if type(original) is P.ProductionRegion:
            anchor=source.nodes[point.node].anchor
            for step in original.steps: self._add(source,source._node(anchor.template,step))
        elif type(original) is P.ProductionStep:self._add(source,point)
        self.check()

    def incoming(self, point): self.demand(point); return self.provider.incoming(point)
    def outgoing(self, point): self.demand(point); return self.provider.outgoing(point)
    def describe(self, point):
        node = self.provider.describe(point)
        if node is not None: self.check()
        return node
    def original(self, point):
        return self.hardware.get(_key(point),self.provider.records.get(_key(point)))
    def expand(self, point): return ()
    def explain(self, point):
        self.check(); base=_key(point)
        return dict(original=self.original(point),interface=self.interfaces.get(base),
            routes=tuple(r for r in self.routes if r.operation==base or base in r.endpoints),
            target_snapshot=None if self.target is None else self.target_ref,
            runtime_placement_proven=False,transfers_observed=False,effects_closed=False,
            tensor_storage_identity_proven=False)

    def payload(self):
        self.check()
        return dict(schema=SCHEMA,resources=self.provider.payload(),
            interfaces=encode(tuple(self.interfaces.values())),hardware=encode(tuple(self.hardware.items())),
            routes=encode(tuple(self.routes)),gaps=self.gaps,source_bodies_copied=False,loops_unrolled=False,
            actual_placement_established=False,transfers_observed=False,first_stage_complete=False)
