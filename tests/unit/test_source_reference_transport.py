"""Only admitted reference wires close; ordinary events remain intact."""
from collections import defaultdict,deque
from types import SimpleNamespace

from scar.analysis.source_reference_transport import ActiveReferenceTransport


def test_directed_cycle_late_edge_and_activation_boundary():
    class Solver:
        def __init__(self):
            self.offsets={'unit':100};self.admitted=set()
            self.values=defaultdict(set);self.adj=defaultdict(set);self.queue=deque();self.events=7
            self.transport=ActiveReferenceTransport(self)

        def add(self,point,value):
            if value not in self.values.get(point,()):
                self.values[point].add(value);self.queue.append((point,value))
                self.transport.enqueue(point,value)

        def edge(self,source,target):
            self.adj[source].add(target)
            for value in tuple(self.values.get(source,())):self.add(target,value)
            self.transport.install(source,target)

    solver=Solver();transport=solver.transport
    unit=SimpleNamespace(unit='unit',aliases=tuple((i,i+1) for i in range(20))+((20,5),(20,21)))
    original_aliases=unit.aliases
    token=('instance',999,-1);solver.add(100,token)
    old_queue=tuple(solver.queue)

    def admit(index):
        solver.admitted.add(('unit','aliases',index))
        source,target=unit.aliases[index]
        solver.edge(source+100,target+100);transport.admit(unit,index)

    # A loaded unit does not authorize its unadmitted final edge.
    for index in range(19):admit(index)
    admitted=solver.admitted.copy();transport.drain()
    assert all(solver.values.get(100+i)=={token} for i in range(20))
    assert not solver.values.get(120) and not solver.values.get(121)
    assert tuple(solver.queue)[:len(old_queue)]==old_queue
    assert solver.admitted==admitted and solver.events==7

    # The source token's old event can be gone when a new edge is installed.
    solver.queue.clear();admit(19);admit(20);admit(21);transport.drain()
    assert solver.values[120]==solver.values[121]=={token}
    assert len(solver.queue)==len(set(solver.queue))==2
    assert not transport.queue and not transport.queued

    # Shared activation owners and the cycle must not duplicate registration.
    facts=len(transport.facts);admit(20);transport.drain()
    assert len(transport.facts)==facts and len(solver.queue)==2
    second=('constant','NoneType',None);solver.add(100,second);transport.drain()
    assert all(solver.values[100+i]=={token,second} for i in range(22))
    assert not solver.values.get(99) and not solver.values.get(122)
    assert unit.aliases is original_aliases and solver.offsets=={'unit':100}
    assert solver.events==7 and transport.stats['normal_events_include_alias_closure'] is False
    # Installed argument/return copies and virtual interface points use the
    # same directional rule; ordinary namespace/operation callbacks stay queued.
    solver.edge(121,-3);solver.edge(-3,-4);solver.edge(-4,123)
    transport.drain()
    assert solver.values[123]=={token,second} and solver.events==7
    assert solver.adj[121]=={-3} and transport.facts=={('unit',i) for i in range(22)}
