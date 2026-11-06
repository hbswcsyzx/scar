"""Fair scheduling conserves pending events without executing consumers."""
from collections import Counter, defaultdict, deque
from types import SimpleNamespace

import pytest

from scar.analysis.source_worklist_context import (
    FairWorklist, PROFILE, _validate_worklist_report,
)


def test_fairness_conservation_and_late_subscription():
    solver = SimpleNamespace(events=7, writes=defaultdict(set), gets=defaultdict(set),
        call_watch=defaultdict(list), descriptors=SimpleNamespace(sinks={}, targets={}),
        constructions=SimpleNamespace(lookups={}, results={}))
    existing = deque([(0, ('constant', 'int', 0)), (1, ('constant', 'int', 1))])
    queue = FairWorklist(solver, existing)
    assert tuple(queue) == tuple(existing) and queue.initial_events == 2
    # Classification reads installed indexes without creating subscriptions.
    assert not solver.writes and not solver.gets and not solver.call_watch
    urgent = [(100 + i, ('constant', 'int', i)) for i in range(19)]
    for point, _ in urgent:
        solver.call_watch[point].append(123)
    queue.extend(urgent)
    expected = urgent[:8] + [existing[0]] + urgent[8:16] + [existing[1]] + urgent[16:]
    assert list(queue) == expected
    assert len(queue) == 21 and solver.events == 7
    actual = [queue.popleft() for _ in range(9)]
    assert actual == expected[:9] and actual[-1] is existing[0]
    assert list(queue) == expected[9:]

    # A pending event is retained when a consumer is installed later. Only new
    # events at that point are classified with the newly installed subscription.
    late = (5, ('constant', 'int', 5))
    queue.append(late)
    solver.gets[5].add(('member', 42))
    newer = (5, ('constant', 'int', 6))
    queue.append(newer)
    assert late in queue.ordinary and newer in queue.urgent
    assert sum(event is late for event in queue) == 1
    # Internal descriptor/construction points also use the same priority hint.
    sink = ('descriptor_sink', 1)
    solver.descriptors.sinks[sink] = (1, 2)
    descriptor = (sink, ('function', 9)); queue.append(descriptor)
    solver.constructions.results[-3] = {1}
    constructor = (-3, ('instance', 9, -3)); queue.append(constructor)
    assert descriptor in queue.urgent and constructor in queue.urgent
    pending = list(queue)
    actual.extend(queue.popleft() for _ in range(len(queue)))
    assert actual[9:] == pending
    assert Counter(actual) == Counter([*existing, *urgent, late, newer, descriptor, constructor])
    assert not queue and not list(queue) and solver.events == 7
    stats = queue.stats
    assert stats['enqueued'] == stats['popped'] == 25
    report = dict(analysis_worklist_profile=PROFILE, worklist=stats,
                  frontier=0, value_events=7 + stats['popped'])
    _validate_worklist_report(report)
    with pytest.raises(IndexError):
        queue.popleft()
    assert queue.stats == stats
    with pytest.raises(ValueError, match='conservation'):
        _validate_worklist_report(dict(report, frontier=1))

    # An empty lane cannot stall the other lane; a newly waiting ordinary
    # event gets service after an urgent-only run has exhausted its quota.
    only = FairWorklist(solver)
    only.extend(urgent)
    for _ in range(12): only.popleft()
    only.append(late)  # Its gets watcher is installed: explicitly ordinary below.
    plain = (6, ('constant', 'NoneType', None)); only.append(plain)
    assert only.popleft() is plain
    assert len(only) == 8
