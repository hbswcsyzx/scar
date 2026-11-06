"""Lexical acceleration retains original binding and activation boundaries."""
from collections import defaultdict, deque
from types import SimpleNamespace

from scar.analysis.source_lexical_context import LexicalContextSolver, LexicalReferenceTransport
from scar.ir.program.normal_links import NamespaceKind


def test_installed_bindings_late_readers_and_scope_separation():
    s = LexicalContextSolver.__new__(LexicalContextSolver)
    s.values = defaultdict(set); s.queue = deque(); s.adj = defaultdict(set)
    s.offsets = {'a': 100, 'b': 200}; s.admitted = set(); s.events = 0
    s.store = SimpleNamespace(original_source_units=set())
    s.writes = defaultdict(set); s.reads = defaultdict(set); s.ns_values = defaultdict(set)
    s.member_watch = defaultdict(set); s.star_forward = defaultdict(set)
    s.namespace_flow = None; s.frames = None
    s.containers = SimpleNamespace(namespace_sources=defaultdict(set))
    s.reference_transport = LexicalReferenceTransport(s)

    def name(kind, owner, port, write):
        return SimpleNamespace(namespace=SimpleNamespace(kind=kind, owner=owner, name='x'), value=port, write=write)

    unit = SimpleNamespace(unit='a', names=(name(NamespaceKind.LEXICAL, 7, 1, True),
        name(NamespaceKind.LEXICAL, 7, 2, False), name(NamespaceKind.LEXICAL, 8, 3, False),
        name(NamespaceKind.CLASS, 7, 4, True), name(NamespaceKind.CLASS, 7, 5, False),
        name(NamespaceKind.LEXICAL, 7, 6, False)))
    other = SimpleNamespace(unit='b', names=(name(NamespaceKind.LEXICAL, 7, 1, False),))
    for index in range(5): s.admit(unit, 'names', index)
    s.admit(other, 'names', 0)
    # Token arrives after registration: only the installed lexical copy closes.
    token = ('instance', 1234, -2)
    s.edge(100, 101); s.edge(102, 107); s.edge(107, 101)
    s.add(100, token); s.add(104, token)
    old = tuple(s.queue); s.reference_transport.drain()
    assert s.values[102] == s.values[107] == {token}
    assert not s.values.get(103) and not s.values.get(105) and not s.values.get(201)
    assert not s.values.get(106)  # Loaded but not admitted reader.
    assert tuple(s.queue)[:len(old)] == old and s.events == 0
    s.queue.clear(); s.admit(unit, 'names', 5); s.reference_transport.drain()
    assert s.values[106] == {token}  # Original read admission replays ns_values.
    # Later write admission seeds old tokens and preserves unit/owner identity.
    late = SimpleNamespace(unit='a', names=unit.names+(name(NamespaceKind.LEXICAL, 9, 8, True),
        name(NamespaceKind.LEXICAL, 9, 9, False)))
    s.add(108, token); s.queue.clear()
    s.admit(late, 'names', 6); s.admit(late, 'names', 7); s.reference_transport.drain()
    assert s.values[109] == {token}
    assert s.reference_transport.stats['whole_transfer_order_equivalence_claimed'] is False
    assert not s.reference_transport.queue and not s.reference_transport.queued
