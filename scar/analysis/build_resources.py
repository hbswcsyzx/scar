"""Symbolic resource interfaces for the unified build.

These are requirements and guarded candidates, never a hardware inventory or
observations of execution. A Python value's host representation is distinct
from any tensor storage it may reference. In particular a device request does
not certify a physical copy, allocation, kernel launch or file access.
"""
from collections import defaultdict
from dataclasses import replace
from hashlib import sha256

from scar.ir.program import model as M, source_productions as P, view as V
from scar.ir.program.dependencies import (
    DependencyPoint as Point, DependencyEdge as Edge, DependencyKind as K,
    DependencyMeaning as Meaning, DependencyStrength as Strength,
    DependencyCondition as Condition, DependencyEvidence as Evidence,
    DependencyNeighborhood as Neighborhood, DependencyFrontier as Frontier)
from scar.ir.program.ids import OperationID, ResourceDefinitionID, ResourceRequirementID
from scar.ir.program.resources import (
    ResourceDefinition, ResourceRequirement, ExternalResource, ResourceKind, ResourceRole)
from scar.ir.record_codec import encode, decode

_SCHEMA = 'scar.build-resource-interfaces.v1'
# Names denote symbolic interface classes. They do not claim these devices exist.
_POOLS = {
    'cpu': (ResourceKind.CPU, ResourceRole.EXECUTOR),
    'gpu': (ResourceKind.GPU, ResourceRole.EXECUTOR),
    'dram': (ResourceKind.MEMORY, ResourceRole.MEMORY_POOL),
    'device-memory': (ResourceKind.MEMORY, ResourceRole.MEMORY_POOL),
    'file': (ResourceKind.FILE, ResourceRole.FILE_ENTITY),
    'ssd': (ResourceKind.STORAGE, ResourceRole.STORAGE_ENDPOINT),
    'nvme': (ResourceKind.STORAGE, ResourceRole.STORAGE_ENDPOINT),
}


def _key(point):
    return replace(point, context=None)


def _identity(point, suffix, cls):
    return cls(sha256((str(point.node) + ':' + suffix).encode()).hexdigest())


class BuildResourceProvider:
    """Typed dependency adapter; no target code or live probes are executed."""
    relation_kinds = frozenset((K.RESOURCE,))

    def __init__(self, view):
        self.view = view
        self.records = {}
        self.owners = {}
        self.edges = []
        self.frontiers = []
        self._incoming = defaultdict(list)
        self._outgoing = defaultdict(list)
        self._frontiers = defaultdict(list)
        self.pools = {}
        self._operations = set()
        self._candidate_operations = set()

    def _record(self, point, record, owner):
        self.records[point] = record
        self.owners[point] = owner
        return point

    def _edge(self, source, target, rule, *, condition=None, may=False):
        edge = Edge(source, target, K.RESOURCE, Meaning.DEPENDENCE,
            (Evidence(rule, (source.namespace.graph,), (source, target)),),
            () if condition is None else (Condition(_SCHEMA, condition, target),),
            Strength.MAY if may else Strength.EXACT)
        self.edges.append(edge)
        self._incoming[target].append(edge)
        self._outgoing[source].append(edge)

    def _frontier(self, point, kind, detail):
        frontier = Frontier(point, kind, detail)
        self.frontiers.append(frontier)
        self._frontiers[point].append(frontier)

    def _pool(self, operation, name):
        key = (operation.namespace, name)
        if key not in self.pools:
            kind, role = _POOLS[name]
            root = operation.namespace.root
            point = Point(operation.namespace, _identity(Point(operation.namespace, root, None),
                'symbolic-resource:' + name, ResourceDefinitionID), None)
            self._record(point, ResourceDefinition(point.node, kind, role,
                ExternalResource(root, 'symbolic:' + name)), Point(operation.namespace, root, None))
            self.pools[key] = point
        return self.pools[key]

    def _require(self, operation, name, *, ports=(), conditional=False):
        kind, role = _POOLS[name]
        requirement = Point(operation.namespace,
            _identity(operation, 'require:' + name, ResourceRequirementID), None)
        self._record(requirement, ResourceRequirement(requirement.node, operation.node, kind, role), operation)
        self._edge(requirement, operation, 'scar.build.resource-demand.v1',
            condition='RESOLVED_INTERFACE_REQUIRES_' + name.upper() if conditional else None,
            may=conditional)
        self._edge(self._pool(operation, name), requirement, 'scar.build.resource-candidate.v1',
            condition='SYMBOLIC_POOL_AVAILABLE_AND_COMPATIBLE_' + name.upper(), may=True)
        for port in ports:
            self._edge(requirement, port, 'scar.build.host-value-representation.v1',
                condition='PRESENT_HOST_VALUE_REPRESENTATION', may=True)
        return requirement

    def add_operation(self, operation, ports, original, hints=(), *, candidates=False):
        operation = _key(operation)
        ports = tuple(_key(point) for point in ports)
        if operation in self._operations:
            if candidates:
                self.add_candidates(operation, ports, original)
            return
        if type(operation.node) is not OperationID:
            raise TypeError('resource owner must be an original operation point')
        if type(original) not in (M.Operation, P.ProductionStep):
            raise TypeError('resource demands need the original typed operation')
        if any(port.namespace != operation.namespace for port in ports):
            raise ValueError('resource data ports must belong to their operation namespace')
        for name in hints:
            if name not in _POOLS:
                raise ValueError('unsupported resource interface hint: ' + str(name))
        self._operations.add(operation)
        for name in _POOLS:
            self._pool(operation, name)
        # Interpreter host execution and object representation, not tensor backing.
        self._require(operation, 'cpu')
        if ports:
            self._require(operation, 'dram', ports=ports)
        for name in dict.fromkeys(hints):
            if name not in ('cpu', 'dram'):
                self._require(operation, name, conditional=True)
        if 'file' in hints:
            requirement = self._require(operation, 'ssd', conditional=True)
            self._edge(self._pool(operation, 'nvme'), requirement,
                'scar.build.storage-topology-candidate.v1',
                condition='NVME_STORAGE_PATH_RESOLVES_TO_FILE_BACKING', may=True)
        if 'gpu' in hints:
            self._require(operation, 'device-memory', ports=(), conditional=True)
        if not hints and (type(original) is P.ProductionStep or not original.effects_complete):
            self._frontier(operation, 'UNRESOLVED_EXTERNAL_RESOURCE_INTERFACE',
                'Host execution and value representation are connected; external allocation, '
                'device dispatch and file effects require resolved interfaces or runtime evidence.')
        self._frontier(operation, 'RESOURCE_RUNTIME_EVIDENCE_MISSING',
            'Capacity, current contents, placement, physical I/O and transfers remain symbolic; '
            'no runtime event is inferred from source calls or device requests.')

        if candidates:
            self.add_candidates(operation, ports, original)

    def add_candidates(self, operation, ports, original):
        """Connect conservative resource alternatives without adding demands.

        Behavior tags describe an effect family, not dispatch or storage
        identity. All these relations therefore retain explicit conditions.
        An argument/result may participate only if the resolved interface gives
        it the indicated device value, file referent, or storage role.
        """
        operation = _key(operation)
        ports = tuple(_key(port) for port in ports)
        if operation in self._candidate_operations:
            return
        if type(operation.node) is not OperationID or type(original) not in (M.Operation, P.ProductionStep):
            raise TypeError('resource candidates need an original typed operation')
        if any(port.namespace != operation.namespace for port in ports):
            raise ValueError('resource data ports must belong to their operation namespace')
        self._candidate_operations.add(operation)
        if type(original) is not M.Operation:
            self._frontier(operation, 'RESOURCE_CANDIDATE_INTERFACE_UNRESOLVED',
                'Source instructions have no admitted core behavior classification; device and file candidates remain unresolved.')
            return
        behaviors = frozenset(original.behaviors)
        families = []
        if behaviors.intersection((M.Behavior.COMPUTE, M.Behavior.MEMORY, M.Behavior.TRANSFER)):
            families.append((('gpu', 'device-memory'), 'POSSIBLE_DEVICE_DISPATCH', 'device'))
        if behaviors.intersection((M.Behavior.READ, M.Behavior.WRITE, M.Behavior.TRANSFER)):
            families.append((('file', 'ssd', 'nvme'), 'POSSIBLE_EXTERNAL_FILE_EFFECT', 'file'))
        for names, condition, family in families:
            for name in names:
                pool = self._pool(operation, name)
                self._edge(pool, operation, 'scar.build.possible-' + family + '-resource.v1',
                    condition=condition, may=True)
                for port in ports:
                    self._edge(pool, port, 'scar.build.possible-' + family + '-value-storage.v1',
                        condition=condition + '_AND_RESOLVED_PORT_ROLE_' + name.upper(), may=True)
        if families:
            self._frontier(operation, 'RESOURCE_CANDIDATES_REQUIRE_INTERFACE_RESOLUTION',
                'Behavior tags admit guarded alternatives only; device dispatch, file effects, '
                'port roles and storage topology remain unresolved. These candidates add no resource demand or runtime event.')

    def add_operations(self, operations, *, resource_hints=None, candidates=False):
        """Append a body admitted by a lazy owner; each operation is added once."""
        hints = resource_hints or {}
        for point, ports, original in operations:
            self.add_operation(point, ports, original, hints.get(point, hints.get(_key(point), ())),
                candidates=candidates)
        return self

    def _neighbors(self, point, incoming):
        base = _key(point)
        edges = (self._incoming if incoming else self._outgoing).get(base, ())
        # Resource interfaces share their owning operation's call context.
        def qualify(endpoint):
            return replace(endpoint, context=point.context)
        return Neighborhood(tuple(replace(edge, source=qualify(edge.source), target=qualify(edge.target),
            conditions=tuple(replace(c,
                subject=None if c.subject is None else qualify(c.subject),
                operands=tuple(qualify(p) for p in c.operands)) for c in edge.conditions)) for edge in edges),
            tuple(replace(f, point=point) for f in self._frontiers.get(base, ())))

    def incoming(self, point):
        return self._neighbors(point, True)

    def outgoing(self, point):
        return self._neighbors(point, False)

    def describe(self, point):
        record = self.records.get(_key(point))
        if record is None:
            return None
        resource = type(record) is ResourceDefinition
        owner = replace(self.owners[_key(point)], context=point.context)
        return V.ProgramNode(point, V.ProgramEntityKind.RESOURCE if resource else None,
            V.ProgramNodeRole.RESOURCE if resource else V.ProgramNodeRole.RESOURCE_REQUIREMENT, owner, None)

    def original(self, point):
        return self.records[_key(point)]

    def expand(self, point):
        return ()

    def explain(self, point):
        return dict(node=self.describe(point), original=self.original(point),
            symbolic_interface=True, runtime_placement_proven=False, transfers_observed=False)

    def payload(self):
        return dict(schema=_SCHEMA,
            records=[dict(point=encode(p), record=encode(record), owner=encode(self.owners[p]),
                type=type(record).__name__) for p, record in self.records.items()],
            edges=[encode(edge) for edge in self.edges],
            frontiers=[encode(frontier) for frontier in self.frontiers],
            candidate_operations=[encode(point) for point in sorted(self._candidate_operations,
                key=lambda p: (str(p.namespace.root), str(p.node)))],
            actual_events=[], actual_placement_established=False, transfers_observed=False)

    @classmethod
    def from_payload(cls, view, payload):
        if payload.get('schema') != _SCHEMA or payload.get('actual_events') != []:
            raise ValueError('resource payload requires symbolic interfaces schema')
        if payload.get('actual_placement_established') is not False or payload.get('transfers_observed') is not False:
            raise ValueError('symbolic interfaces cannot assert placement or transfers')
        provider = cls(view)
        classes = {c.__name__: c for c in (ResourceDefinition, ResourceRequirement)}
        for row in payload['records']:
            point = decode(Point, row['point'])
            record = decode(classes[row['type']], row['record'])
            if point.node != record.id or point in provider.records:
                raise ValueError('resource record identity differs or repeats')
            owner = decode(Point, row['owner'])
            provider._record(point, record, owner)
            if type(record) is ResourceRequirement:
                provider._operations.add(owner)
        provider._candidate_operations = {decode(Point, row) for row in payload.get('candidate_operations', ())}
        for row in payload['edges']:
            edge = decode(Edge, row)
            if edge.kind is not K.RESOURCE:
                raise ValueError('resource payload contains unrelated relation')
            provider.edges.append(edge)
            provider._incoming[edge.target].append(edge)
            provider._outgoing[edge.source].append(edge)
        for row in payload['frontiers']:
            frontier = decode(Frontier, row)
            provider.frontiers.append(frontier)
            provider._frontiers[frontier.point].append(frontier)
        view.register(provider)
        return provider


def attach_build_resources(view, units=(), *, operations=(), resource_hints=None):
    """Connect already admitted endpoints; hints describe resolved interfaces.

    ``operations`` is an iterable of (operation point, data points, original
    typed operation). Hints are a mapping from operation point to symbolic
    resource classes, and remain conditional requirements, never observations.
    """
    provider = BuildResourceProvider(view)
    hints = resource_hints or {}
    seen = set()
    def add(point, ports, original):
        base = _key(point)
        if base in seen:
            return
        seen.add(base)
        provider.add_operation(base, ports, original, hints.get(point, hints.get(base, ())))
    for unit in units:
        source = view.unit(unit)
        by_owner = defaultdict(list)
        source.check()
        for node in source.nodes.values():
            if node.owner is not None and node.role in (
                    V.ProgramNodeRole.ARGUMENT, V.ProgramNodeRole.RESULT, V.ProgramNodeRole.CALL_RESULT):
                by_owner[node.owner].append(node.point)
        for node in tuple(source.nodes.values()):
            if type(node.point.node) is OperationID:
                add(node.point, tuple(by_owner[node.point]), source.records[node.point.node])
        source.check()
    for point, ports, original in operations:
        add(point, ports, original)
    view.register(provider)
    return provider
