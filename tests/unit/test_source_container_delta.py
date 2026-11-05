"""Delta notifications preserve dependencies with canonical read selectors."""
from scar.analysis.normal_containers import ContainerFlow
from scar.analysis.normal_targets import _Solver
from scar.analysis.source_container_delta import DeltaContainerFlow
from scar.ir.program import normal_targets as T
from tests.unit.test_source_construction_connections import source_facts


def test_delta_contents_equal_replay_for_early_and_late_subscriptions():
    unit = source_facts('''
def ports(a, b, c, d, early, late, keys, pairs, unknown, exact, fallback, cyclic):
    return a
mapping = {}
copied = {}
sequence = []
tail = []
lookup = mapping[unknown_key]
''')

    def run(flow_type):
        solver = _Solver([unit])
        flow = solver.containers = flow_type(solver, [unit])
        a, b, c, d, early, late, keys, pairs, unknown, exact, fallback, cyclic = unit.functions[0].formals[1:-1]
        mappings = [x.value for x in unit.containers if x.kind.value == 'MAPPING']
        sequences = [x.value for x in unit.containers if x.kind.value == 'SEQUENCE']
        mapping, copied = (('container', x, 'MAPPING') for x in mappings)
        sequence, tail = (('container', x, 'SEQUENCE') for x in sequences)
        # Literal None keys and unknown keys must remain distinct; repeated
        # subscriptions and writes appear before and after copy creation.
        flow.read(mapping, ('str', 'key'), exact)
        flow.iterate_mode(mapping, early, 'values')
        flow.iterate_mode(mapping, keys, 'keys')
        flow.iterate_mode(mapping, pairs, 'items')
        flow.copy(mapping, copied)
        flow.write(mapping, ('str', 'key'), a)
        flow.write(mapping, ('NoneType', None), b)
        flow.read(copied, None, unknown)
        flow.iterate_mode(mapping, late, 'values')
        flow.link(d, exact, mapping[1])  # direct dict.get-style default
        flow.write(mapping, None, c)
        flow.write(mapping, ('str', 'key'), b)
        flow.write(mapping, ('int', 2), a)
        flow.read(mapping, ('str', 'key'), exact)
        flow.copy(mapping, copied)
        flow.copy(copied, mapping)
        flow.write(copied, ('str', 'late'), d)
        flow.iterate(mapping, keys)

        flow.iterate(sequence, early)
        flow.copy(sequence, tail)
        flow.read(tail, ('int', 0), fallback)
        flow.write(sequence, ('int', 0), a)
        flow.write(sequence, ('int', 1), b)
        flow.iterate(sequence, late)
        flow.copy(sequence, tail)
        flow.write(sequence, None, c)
        flow.project_argument(sequence[1], sequence[1],
            T.ProjectionKind.POSITIONAL_TAIL, index=1)
        flow.read(sequence, ('int', 0), cyclic)
        flow.write(sequence, ('int', 20), d)
        # Use the original dynamic-item ABI. Repeated key arrivals must not
        # replay all keys, and late unknown writes reach every read selector.
        item = next(x for x in unit.items if not x.write)
        solver.add(item.receiver, mapping)
        for key in ('key', 'late', 'missing'):
            solver.add(item.key, ('constant', 'str', key))
        solver.add(item.key, ('external_value', None))
        flow.write(mapping, None, d)
        assert solver.solve(100_000)
        return solver, flow

    old_solver, old = run(ContainerFlow)
    new_solver, new = run(DeltaContainerFlow)
    assert dict(new_solver.values) == dict(old_solver.values)
    assert dict(new_solver.adj) == dict(old_solver.adj)
    assert new.entries == old.entries
    relation = lambda f: {(a,b,c) for a,b,c,key in f.links}
    assert relation(new) == relation(old)
    # Independently derive the exact key-labeled relation from final content
    # and selected readers, plus the explicit fallback edge above.
    expected = {(unit.functions[0].formals[4], unit.functions[0].formals[10],
                 next(x.value for x in unit.containers if x.kind.value == 'MAPPING'), None)}
    for container, selectors in new.selected_readers.items():
        entries = new.entries[container]
        for key, targets in selectors.items():
            sources = (set().union(*entries.values()) if key is None
                       else entries.get(key,set()) | entries.get(None,set()))
            expected.update((source,target,container[1],key)
                for source in sources for target in targets if source != target)
    assert set(new.links) == expected
    assert new.index_cycles == old.index_cycles
    assert new.open_containers == old.open_containers
    assert new.delta_stats['copy_reuses'] > 0
    assert new.delta_stats['copy_replays'] == 3
    assert new.delta_stats['copy_deltas'] > 0
    assert new.delta_stats['iterator_deltas'] > 0
    assert new.delta_stats['dynamic_key_accesses'] > 0
    assert not new.content_pending and not new.content_draining

    # Labels describe selected content, independently of whether a write or
    # read subscription arrived first at the analyzer.
    variants = []
    for reads_first in (True, False):
        solver = _Solver([unit])
        flow = DeltaContainerFlow(solver, [])
        container = ('container', next(x.value for x in unit.containers
                                      if x.kind.value == 'MAPPING'), 'MAPPING')
        a, b, target = unit.functions[0].formals[1:4]
        def reads():
            flow.read(container, ('str', 'key'), target)
            flow.read(container, None, target)
        if reads_first:
            reads()
        flow.write(container, ('str', 'key'), a)
        flow.write(container, None, b)
        if not reads_first:
            reads()
        variants.append(flow.links)
    assert variants[0] == variants[1]
