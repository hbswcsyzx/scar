"""Optional context profile closing admitted lexical reference bindings.

Only the solver's existing flow-insensitive LEXICAL write/read constraints
are accelerated. This does not equate object contents or bypass world edges.
Old context producers and their receipts stay readable without modification.
"""
import argparse
from collections import defaultdict
from contextlib import ExitStack
from hashlib import sha256
import json
from pathlib import Path
import sys
from types import FunctionType, SimpleNamespace

from scar.analysis import source_context_build as base_build
from scar.analysis import source_context_query as base_query
from scar.analysis.source_context_solver import ContextEntrySolver
from scar.analysis.source_reference_transport import ActiveReferenceTransport
from scar.analysis.source_stage import _durable_bytes
from scar.ir.program.normal_links import NamespaceKind


PROFILE = 'ADMITTED_LEXICAL_REFERENCE_COPY_CLOSURE'


class LexicalReferenceTransport(ActiveReferenceTransport):
    def __init__(self, solver):
        super().__init__(solver)
        self.lexical_writes = defaultdict(set)
        self.name_facts = set()
        self.namespace_visits = 0

    def enqueue(self, point, value):
        event = point, value
        if (self.edges.get(point) or self.lexical_writes.get(point)) and event not in self.queued:
            self.queued.add(event)
            self.queue.append(event)

    def admit_name(self, unit, index):
        access = unit.names[index]
        if access.namespace.kind is not NamespaceKind.LEXICAL:
            return
        if (unit.unit, 'names', index) not in self.s.admitted:
            raise ValueError('lexical closure requires an admitted original name fact')
        self.name_facts.add((unit.unit, index))
        if not access.write:
            return  # Normal admission already registers and seeds late readers.
        point = self.s.offsets[unit.unit] + access.value
        key = self.s.ns(unit.unit, access.namespace)
        if key not in self.s.writes.get(point, ()):
            raise ValueError('lexical closure requires an installed namespace write')
        if key not in self.lexical_writes[point]:
            self.lexical_writes[point].add(key)
            for value in tuple(self.s.values.get(point, ())):
                self.enqueue(point, value)

    def drain(self):
        from time import perf_counter
        started = perf_counter()
        try:
            while self.queue:
                point, value = self.queue.popleft()
                self.queued.remove((point, value))
                for target in tuple(self.edges.get(point, ())):
                    self.visits += 1
                    fresh = value not in self.s.values.get(target, ())
                    self.s.add(target, value)
                    self.additions += fresh
                for key in tuple(self.lexical_writes.get(point, ())):
                    self.namespace_visits += 1
                    self.s.namespace_value(key, value)
        finally:
            self.seconds += perf_counter() - started

    @property
    def stats(self):
        return dict(super().stats, profile=PROFILE, lexical_name_facts=len(self.name_facts),
            lexical_write_bindings=sum(map(len, self.lexical_writes.values())),
            lexical_namespace_visits=self.namespace_visits,
            lexical_semantics='EXISTING_FLOW_INSENSITIVE_MAY_BINDING_NOT_CONTENT_IDENTITY')


class LexicalContextSolver(ContextEntrySolver):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        old = self.reference_transport
        transport = LexicalReferenceTransport(self)
        transport.__dict__.update(old.__dict__)
        self.reference_transport = transport

    def admit(self, unit, table, index):
        super().admit(unit, table, index)
        if table == 'names' and isinstance(self.reference_transport, LexicalReferenceTransport):
            self.reference_transport.admit_name(unit, index)


def pins():
    return dict(base_build.pins(), **{name: sha256(Path(module.__file__).read_bytes()).hexdigest()
        for name, module in (('base_context_builder', base_build), ('base_context_reader', base_query),
            ('lexical_context_profile', sys.modules[__name__]))})


def _publish(solver, *args, **kwargs):
    # Preserve original name-table coordinates in a separate small receipt.
    extra = args[-1]
    out = Path(args[3])
    extra['analysis_transport_profile'] = PROFILE
    extra['lexical_name_facts'] = base_build.write_table(out/'lexical-name-facts.jsonl.gz',
        (dict(unit=unit, name=index) for unit, index in sorted(solver.reference_transport.name_facts)))
    original = base_build.normal_targets._publish
    publish = FunctionType(original.__code__, dict(original.__globals__, _durable_bytes=_durable_bytes),
        original.__name__, original.__defaults__, original.__closure__)
    return publish(solver, *args, **kwargs)


def build_context_targets(facts, namespaces, entry, interfaces, out, *, max_events=2_000_000,
        jobs=4, supplements=(), observe_ports=()):
    # Compose the sealed publisher with explicit local dependencies; never
    # monkeypatch a module or misattribute new output to the old producer.
    original = base_build._build_context_targets
    environment = dict(original.__globals__, __file__=__file__, pins=pins,
        source_context_solver=SimpleNamespace(ContextEntrySolver=LexicalContextSolver),
        normal_targets=SimpleNamespace(_publish=_publish))
    build = FunctionType(original.__code__, environment, original.__name__)
    with ExitStack() as resources:
        return build(facts, namespaces, entry, interfaces, out, max_events=max_events, jobs=jobs,
            resources=resources, supplements=tuple(supplements), observe_ports=tuple(observe_ports))


class LexicalContextGraph(base_query.ContextTargetGraph):
    def __init__(self, path):
        original = base_query.ContextTargetGraph.__init__
        initialize = FunctionType(original.__code__,
            dict(original.__globals__, producer=sys.modules[__name__]), original.__name__)
        initialize(self, path)
        if self.report.get('analysis_transport_profile') != PROFILE:
            raise ValueError('lexical context transport profile differs')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('facts', 'namespaces', 'entry', 'interfaces', 'out'):
        parser.add_argument('--'+name, required=True)
    parser.add_argument('--max-events', type=int, default=2_000_000)
    parser.add_argument('--jobs', type=int, default=4)
    parser.add_argument('--supplement', nargs=2, action='append', default=[])
    parser.add_argument('--observe-port', nargs=2, action='append', default=[])
    args = parser.parse_args()
    report = build_context_targets(args.facts, args.namespaces, args.entry, args.interfaces, args.out,
        max_events=args.max_events, jobs=args.jobs, supplements=args.supplement,
        observe_ports=tuple((unit, int(local)) for unit, local in args.observe_port))
    print(json.dumps({k: report[k] for k in ('status', 'value_events', 'frontier', 'seconds')}), flush=True)


if __name__ == '__main__':
    main()
