"""Conditional type-call protocols over original calls and shared bodies.

``__new__`` produces a value and a new world. Only a compatible returned
instance enters ``__init__``; init's data return is discarded. Protocol-local
interfaces have their own type and original-call anchors, not fake G.Ports.
No runtime metaclass, MRO, slot selection or object identity is proven here.
"""
from collections import defaultdict
from dataclasses import dataclass

from scar.analysis.source_function_connections import Invocation, connect
from scar.ir.program import normal_links as F, normal_targets as T


_TYPE_CALL = ('STANDARD_TYPE_CALL_SLOT_ADMISSION', 'CURRENT_CLASS_MRO_SELECTS_DECLARATION',
              'NORMAL_CONSTRUCTION_COMPLETION', 'FLOW_INSENSITIVE_MAY_DISPATCH')
_OBJECT = ('STANDARD_BUILTINS_OBJECT_IDENTITY', 'OBJECT_NEW_SLOT_COMPATIBLE',
           'NORMAL_ALLOCATION_COMPLETION')


@dataclass(frozen=True, slots=True)
class _Call:
    index: int
    cls: int
    callee: int
    result: int
    world: int
    result_world: int
    new_result: int
    new_world: int


class ConstructionFlow:
    def __init__(self, solver):
        self.s = solver
        self.calls = {}
        self.ports = {}
        self.point_keys = {}
        self.lookups = {}
        self.results = defaultdict(set)
        self.refresh_points = defaultdict(set)
        self.allocations = defaultdict(set)
        self.bound = set()
        self.links = {}
        self._declared = {}

    def point(self, index, cls, role):
        key = index, cls, role
        if key not in self.point_keys:
            unit, call = self.s.call_rows[index]
            origin = self.s.offsets[unit.unit] + call.result
            point = -len(self.ports) - 1
            self.point_keys[key] = point
            self.ports[point] = T.ConstructionPort(self.s.gp(origin), self.s.gp(cls), role)
        return self.point_keys[key]

    def record(self, c, stage, inputs=(), outputs=(), connection=None, *, detail=(), conditions=()):
        key = c.index, c.cls, stage, *detail
        self.links[key] = T.ConstructionLink(self.s.gp(c.result), self.s.gp(c.callee), self.s.gp(c.cls),
            stage, tuple(self.s.gp(p) for p in inputs), tuple(self.s.gp(p) for p in outputs),
            connection, (*_TYPE_CALL, *conditions))

    def construct(self, index, cls):
        identity = index, cls
        if identity in self.calls:
            return
        unit, call = self.s.call_rows[index]
        o = self.s.offsets[unit.unit]
        c = _Call(index, cls, o + call.callee, o + call.result, o + call.world, o + call.result_world,
                  self.point(index, cls, T.ConstructionPortKind.NEW_RESULT),
                  self.point(index, cls, T.ConstructionPortKind.NEW_WORLD))
        self.calls[identity] = c
        self.results[c.new_result].add(identity)
        self.record(c, T.ConstructionStage.NEW_LOOKUP_PENDING, (cls, c.world), (c.new_result, c.new_world),
                    conditions=('NEW_TARGET_OR_PROVIDER_OPEN',))
        sink = ('construction_new', index, cls)
        self.lookups[sink] = ('new', c, cls)
        self.s.class_lookup(cls, '__new__', sink)
        self.refresh(c)

    def declared(self, cls, name):
        unit, descriptor = self.s.classes[cls]
        if unit.unit not in self._declared:
            self._declared[unit.unit] = {
                (item.namespace.owner, item.namespace.name) for item in unit.names
                if item.write and item.namespace.kind is F.NamespaceKind.CLASS}
        key = (unit.unit, F.NamespaceKind.CLASS.value, descriptor.scope, name)
        return ((descriptor.scope, name) in self._declared[unit.unit]
                or bool(self.s.ns_values.get(key)))

    def inherited_object(self, cls, name, c, seen=None):
        """Structural absence in declared source namespaces, not an empty value set.

        Open/external bases and packed bases cannot establish the default.
        Dynamic namespace/metaclass overrides remain explicit conditions.
        """
        seen = set() if seen is None else seen
        if cls in seen or self.declared(cls, name):
            return False
        seen = seen | {cls}
        unit, descriptor = self.s.classes[cls]
        if descriptor.bases_pack is not None:
            return False
        for base in descriptor.bases:
            point = self.s.offsets[unit.unit] + base
            self.refresh_points[point].add((c.index, c.cls))
            values = self.s.values.get(point, ())
            if not values:
                return False
            for value in values:
                if value[0] == 'class':
                    if not self.inherited_object(value[1], name, c, seen):
                        return False
                elif value != ('external', 'builtins.object'):
                    return False
        return True

    def refresh(self, c):
        if self.inherited_object(c.cls, '__new__', c):
            self.links.pop((c.index, c.cls, T.ConstructionStage.NEW_LOOKUP_PENDING), None)
            self.record(c, T.ConstructionStage.OBJECT_NEW, (c.cls, c.world), (c.new_result, c.new_world),
                conditions=(*_OBJECT, 'NO_SOURCE_NEW_OVERRIDE', 'NO_DYNAMIC_NAMESPACE_OVERRIDE'))
            self.s.add(c.new_result, ('instance', c.cls, c.new_result))
        for value in tuple(self.s.values.get(c.new_result, ())):
            self.returned(c, value)

    def invocation(self, c, *, new):
        unit, call = self.s.call_rows[c.index]
        o = self.s.offsets[unit.unit]
        args = tuple(o + p for p in call.positional)
        return Invocation(c.callee, (c.cls, *args) if new else args,
            tuple((n, o + p) for n, p in call.keywords), c.new_result if new else None,
            c.world if new else c.new_world, c.new_world if new else c.result_world,
            None if call.positional_pack is None else o + call.positional_pack,
            None if call.keyword_pack is None else o + call.keyword_pack)

    def target(self, kind, c, returned_cls, value):
        if value[0] not in ('function', 'bound', 'classbound'):
            return
        fid = value[1]
        key = kind, c.index, c.cls, returned_cls, value
        if key in self.bound:
            return
        self.bound.add(key)
        receiver = value[2] if value[0] == 'bound' else value[3] if value[0] == 'classbound' else None
        class_receiver = value[2] if value[0] == 'classbound' else None
        stage = T.ConstructionStage.SOURCE_NEW if kind == 'new' else T.ConstructionStage.SOURCE_INIT
        mode = stage.value
        conditions = (*_TYPE_CALL, 'NEW_RECEIVES_SOURCE_CLASS' if kind == 'new'
                      else 'NEW_RESULT_IS_REQUESTED_CLASS_INSTANCE',
                      *(() if kind == 'new' else ('INIT_DATA_RETURN_DISCARDED',)))

        def publish(connection):
            self.s.links[('construction', *key)] = T.CallLink(self.s.gp(c.result), self.s.gp(c.callee),
                connection.source_callable, connection.body, mode, None,
                connection.parameters, connection.returns, connection.conditions,
                argument_packs=connection.argument_packs)
            self.record(c, stage, (c.cls, c.world) if kind == 'new' else (c.new_result, c.new_world),
                (c.new_result, c.new_world) if kind == 'new' else (c.result, c.result_world),
                connection, detail=(returned_cls, fid, value), conditions=conditions)
            pending = T.ConstructionStage.NEW_LOOKUP_PENDING if kind == 'new' else T.ConstructionStage.INIT_LOOKUP_PENDING
            self.links.pop((c.index, c.cls, pending) if kind == 'new'
                           else (c.index, c.cls, pending, returned_cls), None)

        connection = connect(self.s, fid, self.invocation(c, new=kind == 'new'), receiver,
            class_receiver=class_receiver, environment_source=fid, return_value=kind == 'new',
            conditions=conditions, on_ready=publish)
        if connection is not None:
            publish(connection)

    def subtype(self, cls, requested, c, seen=None):
        if cls == requested:
            return True
        seen = set() if seen is None else seen
        if cls in seen:
            return None
        seen = seen | {cls}
        unit, descriptor = self.s.classes[cls]
        open_base = descriptor.bases_pack is not None
        for base in descriptor.bases:
            point = self.s.offsets[unit.unit] + base
            self.refresh_points[point].add((c.index, c.cls))
            values = self.s.values.get(point, ())
            if not values:
                open_base = True
            for value in values:
                if value[0] == 'class':
                    match = self.subtype(value[1], requested, c, seen)
                    if match is True:
                        return True
                    open_base |= match is None
                elif value != ('external', 'builtins.object'):
                    open_base = True
        return None if open_base else False

    def returned(self, c, value):
        # The original result stays dependent on init's normal completion via
        # world/conditional protocol edges. This is may dataflow, not scheduling.
        self.s.edge(c.new_result, c.result)
        match = self.subtype(value[1], c.cls, c) if value[0] == 'instance' else (
            False if value[0] in ('constant', 'container', 'function') else None)
        if match is False:
            self.record(c, T.ConstructionStage.RETURN_FOREIGN, (c.new_result, c.new_world),
                (c.result, c.result_world), detail=(value,), conditions=('NEW_RESULT_IS_NOT_CLASS_INSTANCE', 'INIT_SKIPPED'))
        elif match is None:
            self.record(c, T.ConstructionStage.RESULT_TYPE_OPEN, (c.new_result, c.new_world),
                detail=(value,), conditions=('NEW_RESULT_INSTANCE_TEST_OPEN',))
        else:
            returned_cls = value[1]
            sink = ('construction_init', c.index, c.cls, returned_cls)
            if sink not in self.lookups:
                self.record(c, T.ConstructionStage.INIT_LOOKUP_PENDING, (c.new_result, c.new_world),
                    detail=(returned_cls,), conditions=('INITIALIZER_TARGET_OR_PROVIDER_OPEN',))
                self.lookups[sink] = ('init', c, returned_cls)
                self.s.class_lookup(returned_cls, '__init__', sink, c.new_result)
            if self.inherited_object(returned_cls, '__init__', c):
                self.links.pop((c.index, c.cls, T.ConstructionStage.INIT_LOOKUP_PENDING, returned_cls), None)
                self.record(c, T.ConstructionStage.OBJECT_INIT, (c.new_result, c.new_world),
                    (c.result, c.result_world), detail=(returned_cls,),
                    conditions=('NO_SOURCE_INIT_OVERRIDE', 'NO_DYNAMIC_NAMESPACE_OVERRIDE', 'OBJECT_INIT_SLOT_ACCEPTS_ARGUMENTS'))

    def object_new(self, index):
        unit, call = self.s.call_rows[index]
        if len(call.positional) != 1 or call.keywords or call.positional_pack is not None or call.keyword_pack is not None:
            return
        point = self.s.offsets[unit.unit] + call.positional[0]
        self.allocations[point].add(index)
        for value in tuple(self.s.values.get(point, ())):
            self.allocate(index, value)

    def allocate(self, index, value):
        if value[0] != 'class':
            return
        unit, call = self.s.call_rows[index]
        o = self.s.offsets[unit.unit]
        result = o + call.result
        self.s.add(result, ('instance', value[1], result))
        self.links[('object_new', index, value[1])] = T.ConstructionLink(self.s.gp(result), self.s.gp(o + call.callee),
            self.s.gp(value[1]), T.ConstructionStage.EXPLICIT_OBJECT_NEW,
            (self.s.gp(o + call.positional[0]), self.s.gp(o + call.world)),
            (self.s.gp(result), self.s.gp(o + call.result_world)), None, _OBJECT)

    def consume(self, point, value):
        if point in self.lookups:
            self.target(*self.lookups[point], value)
        for identity in tuple(self.results.get(point, ())):
            self.returned(self.calls[identity], value)
        for identity in tuple(self.refresh_points.get(point, ())):
            self.refresh(self.calls[identity])
        for index in tuple(self.allocations.get(point, ())):
            self.allocate(index, value)
