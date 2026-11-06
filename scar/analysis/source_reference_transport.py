"""Close admitted reference-copy wires without interpreting program operations."""
from collections import defaultdict,deque
from time import perf_counter


class ActiveReferenceTransport:
    def __init__(self,solver):
        self.s=solver;self.edges=defaultdict(set);self.facts=set()
        self.queue=deque();self.queued=set()
        self.visits=0;self.additions=0;self.seconds=0.0

    def enqueue(self,point,value):
        event=point,value
        if self.edges.get(point) and event not in self.queued:
            self.queued.add(event);self.queue.append(event)

    def admit(self,unit,index):
        key=unit.unit,'aliases',index
        if key not in self.s.admitted:
            raise ValueError('reference transport requires an admitted original alias fact')
        if (unit.unit,index) in self.facts:return
        self.facts.add((unit.unit,index))
        source,target=unit.aliases[index];offset=self.s.offsets[unit.unit]
        source+=offset;target+=offset
        self.edges[source].add(target)
        # An old source value may predate this edge and its queue event.
        for value in tuple(self.s.values.get(source,())):self.enqueue(source,value)

    def drain(self):
        started=perf_counter()
        try:
            while self.queue:
                source,value=self.queue.popleft();self.queued.remove((source,value))
                for target in tuple(self.edges.get(source,())):
                    self.visits+=1
                    fresh=value not in self.s.values.get(target,())
                    self.s.add(target,value)
                    self.additions+=fresh
        finally:self.seconds+=perf_counter()-started

    @property
    def stats(self):
        return dict(profile='EAGER_ACTIVE_REFERENCE_ALIAS_CLOSURE',
            original_alias_facts=len(self.facts),edges=sum(map(len,self.edges.values())),
            pending=len(self.queue),transfer_visits=self.visits,new_values=self.additions,
            drain_seconds=self.seconds,normal_events_include_alias_closure=False,
            ordinary_add_activation_rules_retained=True,whole_transfer_order_equivalence_claimed=False)
