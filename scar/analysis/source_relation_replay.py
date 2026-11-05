"""Avoid repeated analysis queries while retaining the existing may domain."""
from collections import defaultdict

from scar.analysis.source_construction import ConstructionFlow
from scar.analysis.source_container_delta import DeltaContainerFlow
from scar.analysis.source_class_queries import subtype_relation, inherited_object_relation


class SharedConstructionFlow(ConstructionFlow):
    def __init__(self, solver):
        super().__init__(solver)
        self.base_semantics = defaultdict(set)
        self.query_stats = dict(subtype_queries=0,object_queries=0,classes_read=0,
            semantic_refreshes=0,redundant_base_refreshes=0)

    def bases(self, cls):
        self.query_stats['classes_read']+=1
        unit,descriptor = self.s.classes[cls]
        offset = self.s.offsets[unit.unit]
        return descriptor.bases_pack is not None,tuple((offset+base,self.s.values.get(offset+base,()))
            for base in descriptor.bases)

    def subtype(self, cls, requested, call, seen=None):
        if seen is not None:
            return super().subtype(cls,requested,call,seen)
        self.query_stats['subtype_queries']+=1
        return subtype_relation(cls,requested,self.bases,
            lambda point:self.refresh_points[point].add((call.index,call.cls)))

    def inherited_object(self, cls, name, call, seen=None):
        if seen is not None:
            return super().inherited_object(cls,name,call,seen)
        self.query_stats['object_queries']+=1
        return inherited_object_relation(cls,lambda value:self.declared(value,name),self.bases,
            lambda point:self.refresh_points[point].add((call.index,call.cls)))

    def consume(self, point, value):
        if point in self.lookups:
            self.target(*self.lookups[point],value)
        for identity in tuple(self.results.get(point,())):
            self.returned(self.calls[identity],value)
        if point in self.refresh_points:
            semantic = (('class',value[1]) if value[0]=='class' else
                ('object',) if value==('external','builtins.object') else ('open',))
            if semantic not in self.base_semantics[point]:
                self.base_semantics[point].add(semantic)
                for identity in tuple(self.refresh_points[point]):
                    self.query_stats['semantic_refreshes']+=1
                    self.refresh(self.calls[identity])
            else:
                self.query_stats['redundant_base_refreshes']+=1
        for index in tuple(self.allocations.get(point,())):
            self.allocate(index,value)


class SharedContainerFlow(DeltaContainerFlow):
    def __init__(self, solver, units):
        self.subscription_stats = dict(iteration_replays=0,iteration_reuses=0,
            mode_replays=0,mode_reuses=0)
        super().__init__(solver,units)

    @property
    def analysis_stats(self):
        return dict(super().analysis_stats,subscriptions=dict(self.subscription_stats))

    def iterate(self, container, target):
        if container[0]=='container':
            if target in self.iter_sources[container]:
                self.subscription_stats['iteration_reuses']+=1
                return
            self.subscription_stats['iteration_replays']+=1
        super().iterate(container,target)

    def iterate_mode(self, container, target, mode):
        if (mode,target) in self.content_readers[container]:
            self.subscription_stats['mode_reuses']+=1
            return
        self.subscription_stats['mode_replays']+=1
        super().iterate_mode(container,target,mode)

    def _notify_write(self, container, key, source):
        super()._notify_write(container,key,source)
        namespace = getattr(self.s,'namespace_flow',None)
        if namespace is not None:
            namespace.builtins.content_write(container,key,source)
