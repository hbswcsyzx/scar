"""Optional fair scheduling of the original context solver's pending events.

The two lanes retain every event and invoke no transfer functions. Priority is
chosen from consumers already installed when an event is appended; later
subscriptions leave that event pending in its original lane. The original
reference-copy closure and all ordinary transfer rules remain unchanged.
"""
import argparse
from collections import deque
from contextlib import ExitStack
from hashlib import sha256
import json
from pathlib import Path
import sys
from types import FunctionType, SimpleNamespace

from scar.analysis import source_context_build as base_build
from scar.analysis import source_context_query as base_query
from scar.analysis.source_context_solver import ContextEntrySolver
from scar.analysis.source_stage import _durable_bytes


PROFILE = 'FAIR_INSTALLED_CONSUMER_WORKLIST_8_TO_1'
URGENT_BURST = 8
_CLASSIFICATION = 'INSTALLED_NON_COPY_CONSUMERS_AT_ENQUEUE'
_INDEXES = {
    'solver': ('writes', 'gets', 'call_watch', 'instance_call_watch',
               'base_watch', 'classmethod_watch', 'dynamic_gets'),
    'descriptors': ('accesses', 'sinks', 'targets'),
    'constructions': ('lookups', 'results', 'refresh_points', 'allocations'),
}


class FairWorklist:
    """Two FIFO lanes, serving an ordinary event after at most eight urgent ones.

    Priority is a scheduling hint, never an admission or a value filter. In
    particular, neither token tags nor source names select a lane. Iteration
    previews the current dequeue order without copying or consuming events.
    """
    def __init__(self, solver, events=()):
        self.s = solver
        self.urgent = deque()
        self.ordinary = deque()
        self.urgent_quota_used = 0
        self.enqueued_urgent = self.enqueued_ordinary = 0
        self.popped_urgent = self.popped_ordinary = 0
        self.peak_pending = 0
        self.initial_solver_events = solver.events
        self.extend(events)
        self.initial_events = len(self)

    def _urgent(self, point):
        for owner, names in _INDEXES.items():
            instance = self.s if owner == 'solver' else getattr(self.s, owner, None)
            if instance is not None and any(getattr(instance, name, {}).get(point)
                                            for name in names):
                return True
        return False

    def append(self, event):
        if self._urgent(event[0]):
            self.urgent.append(event)
            self.enqueued_urgent += 1
        else:
            self.ordinary.append(event)
            self.enqueued_ordinary += 1
        self.peak_pending = max(self.peak_pending, len(self))

    def extend(self, events):
        for event in events:
            self.append(event)

    def popleft(self):
        if self.urgent and (not self.ordinary or self.urgent_quota_used < URGENT_BURST):
            event = self.urgent.popleft()
            self.urgent_quota_used = min(URGENT_BURST, self.urgent_quota_used + 1)
            self.popped_urgent += 1
        else:
            event = self.ordinary.popleft()  # Empty queues retain deque's IndexError.
            self.urgent_quota_used = 0
            self.popped_ordinary += 1
        return event

    def __len__(self):
        return len(self.urgent) + len(self.ordinary)

    def __iter__(self):
        urgent, ordinary = iter(self.urgent), iter(self.ordinary)
        urgent_left, ordinary_left = len(self.urgent), len(self.ordinary)
        quota = self.urgent_quota_used
        while urgent_left or ordinary_left:
            if urgent_left and (not ordinary_left or quota < URGENT_BURST):
                yield next(urgent)
                urgent_left -= 1
                quota = min(URGENT_BURST, quota + 1)
            else:
                yield next(ordinary)
                ordinary_left -= 1
                quota = 0

    @property
    def stats(self):
        return dict(profile=PROFILE, urgent_burst=URGENT_BURST,
            classification=_CLASSIFICATION,
            consumer_indexes={owner: list(names) for owner, names in _INDEXES.items()},
            initial_events=self.initial_events, initial_solver_events=self.initial_solver_events,
            enqueued=self.enqueued_urgent + self.enqueued_ordinary,
            enqueued_urgent=self.enqueued_urgent, enqueued_ordinary=self.enqueued_ordinary,
            popped=self.popped_urgent + self.popped_ordinary,
            popped_urgent=self.popped_urgent, popped_ordinary=self.popped_ordinary,
            pending=len(self), pending_urgent=len(self.urgent), pending_ordinary=len(self.ordinary),
            peak_pending=self.peak_pending, urgent_quota_used=self.urgent_quota_used,
            normal_events_include_all_worklist_pops=True,
            transfers_invoked_by_worklist=False, whole_transfer_order_equivalence_claimed=False)


class WorklistContextSolver(ContextEntrySolver):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Keep the already queued event objects, each exactly once.
        self.queue = FairWorklist(self, self.queue)


def pins():
    return dict(base_build.pins(), **{name: sha256(Path(module.__file__).read_bytes()).hexdigest()
        for name, module in (('base_context_builder', base_build), ('base_context_reader', base_query),
                            ('worklist_context_profile', sys.modules[__name__]))})


def _local_function(function, **bindings):
    local = FunctionType(function.__code__, dict(function.__globals__, **bindings),
                         function.__name__, function.__defaults__, function.__closure__)
    local.__kwdefaults__ = function.__kwdefaults__
    return local


def _publish(solver, *args, **kwargs):
    if not isinstance(solver.queue, FairWorklist):
        raise ValueError('fair worklist publisher requires its own queue')
    extra = args[-1]
    extra['analysis_worklist_profile'] = PROFILE
    extra['worklist'] = solver.queue.stats
    # The base builder clones this wrapper with its result-writing interceptor.
    # Forward that local interceptor to the original relation publisher too.
    publish = _local_function(base_build.normal_targets._publish, _durable_bytes=_durable_bytes)
    return publish(solver, *args, **kwargs)


def build_context_targets(facts, namespaces, entry, interfaces, out, *, max_events=2_000_000,
                          jobs=4, supplements=(), observe_ports=()):
    build = _local_function(base_build._build_context_targets, __file__=__file__, pins=pins,
        source_context_solver=SimpleNamespace(ContextEntrySolver=WorklistContextSolver),
        normal_targets=SimpleNamespace(_publish=_publish))
    with ExitStack() as resources:
        return build(facts, namespaces, entry, interfaces, out, max_events=max_events, jobs=jobs,
                     resources=resources, supplements=tuple(supplements), observe_ports=tuple(observe_ports))


def _validate_worklist_report(report):
    stats = report.get('worklist', {})
    integers = ('initial_events', 'initial_solver_events', 'enqueued', 'enqueued_urgent',
                'enqueued_ordinary', 'popped', 'popped_urgent', 'popped_ordinary',
                'pending', 'pending_urgent', 'pending_ordinary', 'peak_pending', 'urgent_quota_used')
    if (report.get('analysis_worklist_profile') != PROFILE or stats.get('profile') != PROFILE
            or type(stats.get('urgent_burst')) is not int or stats['urgent_burst'] != URGENT_BURST
            or stats.get('classification') != _CLASSIFICATION
            or stats.get('consumer_indexes') != {k: list(v) for k, v in _INDEXES.items()}
            or stats.get('normal_events_include_all_worklist_pops') is not True
            or stats.get('transfers_invoked_by_worklist') is not False
            or stats.get('whole_transfer_order_equivalence_claimed') is not False
            or any(type(stats.get(key)) is not int or stats[key] < 0 for key in integers)):
        raise ValueError('fair worklist profile or counters differ')
    if (stats['enqueued'] != stats['enqueued_urgent'] + stats['enqueued_ordinary']
            or stats['popped'] != stats['popped_urgent'] + stats['popped_ordinary']
            or stats['pending'] != stats['pending_urgent'] + stats['pending_ordinary']
            or stats['enqueued_urgent'] != stats['popped_urgent'] + stats['pending_urgent']
            or stats['enqueued_ordinary'] != stats['popped_ordinary'] + stats['pending_ordinary']
            or stats['enqueued'] != stats['popped'] + stats['pending']
            or stats['pending'] != report['frontier']
            or stats['initial_solver_events'] + stats['popped'] != report['value_events']
            or not stats['pending'] <= stats['peak_pending'] <= stats['enqueued']
            or stats['initial_events'] > stats['enqueued']
            or stats['urgent_quota_used'] > URGENT_BURST):
        raise ValueError('fair worklist event conservation differs')


class WorklistContextGraph(base_query.ContextTargetGraph):
    def __init__(self, path):
        initialize = _local_function(base_query.ContextTargetGraph.__init__, producer=sys.modules[__name__])
        initialize(self, path)
        _validate_worklist_report(self.report)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('facts', 'namespaces', 'entry', 'interfaces', 'out'):
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--max-events', type=int, default=2_000_000)
    parser.add_argument('--until-fixed-point', action='store_true')
    parser.add_argument('--jobs', type=int, default=4)
    parser.add_argument('--supplement', nargs=2, action='append', default=[])
    parser.add_argument('--observe-port', nargs=2, action='append', default=[])
    args = parser.parse_args()
    report = build_context_targets(args.facts, args.namespaces, args.entry, args.interfaces, args.out,
        max_events=None if args.until_fixed_point else args.max_events, jobs=args.jobs,
        supplements=args.supplement, observe_ports=tuple((unit, int(local)) for unit, local in args.observe_port))
    print(json.dumps({k: report[k] for k in ('status', 'value_events', 'frontier', 'seconds', 'worklist')}, flush=True))


if __name__ == '__main__':
    main()
