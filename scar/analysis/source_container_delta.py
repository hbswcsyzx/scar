"""Incremental notifications for the existing source-content relation.

The initial subscription replays existing contents. Later writes and dynamic
keys visit only their new facts. ContentLink.key consistently identifies the
read selector; unknown writes reach every subscribed selector. This removes
the old arrival-order dependence of labels without dropping reference flows.
Source ports, key presence, defaults and position constraints are retained.
"""
from collections import defaultdict
from scar.analysis.normal_containers import ContainerFlow, _key
from scar.analysis.source_pack_shapes import StaticPackShapes


class DeltaContainerFlow(ContainerFlow):
    def __init__(self, solver, units):
        self.pack_shapes = StaticPackShapes(self)
        self.content_key_semantics = 'READ_SELECTOR_V1'
        self.selected_readers = defaultdict(lambda: defaultdict(set))
        self.delta_stats = dict(copy_replays=0, copy_reuses=0,
            copy_deltas=0, iterator_deltas=0, read_replays=0, read_reuses=0,
            dynamic_key_events=0, dynamic_key_accesses=0)
        super().__init__(solver, units)

    @property
    def analysis_stats(self):
        return dict(self.delta_stats, pack_shapes=self.pack_shapes.stats)

    def _closed_pack(self, point, kind, seen=frozenset()):
        return self.pack_shapes.closed(point, kind, seen)

    def invocation_arguments(self, invocation):
        return self.pack_shapes.arguments(invocation)

    def _iterator_delta(self, container, key, source, target):
        if container[2] == 'MAPPING':
            if key is not None:
                self.s.add(target, ('constant', key[0], key[1]))
        else:
            self.link(source, target, container[1])

    def _copy_delta(self, source, target, key, point):
        self.delta_stats['copy_deltas'] += 1
        if target[2] == 'MAPPING' and source[2] == target[2]:
            self.write(target, key, point)
        elif source[2] != 'MAPPING':
            self.write(target, None, point)

    def _notify_write(self, container, key, source):
        if key is None:
            selectors = tuple((wanted, tuple(targets))
                for wanted, targets in self.selected_readers[container].items())
        else:
            selectors = tuple((wanted, tuple(self.selected_readers[container].get(wanted, ())))
                for wanted in (key, None))
        for wanted, targets in selectors:
            for target in targets:
                self.link(source, target, container[1], wanted)
        for target in tuple(self.iter_sources[container]):
            self.delta_stats['iterator_deltas'] += 1
            self._iterator_delta(container, key, source, target)
        for mode, target in tuple(self.content_readers[container]):
            self.delta_stats['iterator_deltas'] += 1
            if mode == 'values':
                self.link(source, target, container[1])
            elif mode == 'keys':
                self._iterator_delta(container, key, source, target)
            elif key is not None:
                self.s.add(target, ('pair', container, key))
        for target in tuple(self.copies[container]):
            self._copy_delta(container, target, key, source)
        for spec in tuple(self.remainder_projections.get(container, ())):
            self.project_remainder(container, key, source, spec)

    def read(self, container, key, target):
        if container[2] == 'SEQUENCE' and key is not None and key[0] == 'int' and key[1] < 0:
            key = None
        if container[2] == 'SET' and key is not None:
            return
        if target in self.selected_readers[container][key]:
            self.delta_stats['read_reuses'] += 1
            return
        self.selected_readers[container][key].add(target)
        self.delta_stats['read_replays'] += 1
        super().read(container, key, target)

    def copy(self, source, target):
        if (source[0] == 'container' and target[0] == 'container'):
            if target in self.copies[source]:
                self.delta_stats['copy_reuses'] += 1
                return
            self.delta_stats['copy_replays'] += 1
        # Includes original kind admission and deferred-consumer obligations.
        # Subscription precedes replay, so reentrant writes are not lost.
        super().copy(source, target)

    def consume(self, point, value):
        if hasattr(self.s, 'generators'):
            for target in tuple(self.iterator_getters.get(point, ())):
                self.s.generators.get_iterator(value, target)
        for spec in tuple(self.argument_projections.get(point, ())):
            self.project_value(value, spec)
        for key, target, write in tuple(self.items.get(point, ())):
            self.apply_item(value, key, target, write)
        # A new receiver needs the existing keys once. A new key needs only
        # that key against existing receivers, never all historical keys.
        watched_key = point in self.keys or point in self.method_keys
        if watched_key:
            self.delta_stats['dynamic_key_events'] += 1
        key_ready = watched_key and value[0] in ('constant', 'external_value', 'external_member')
        selected = _key(value[2]) if key_ready and value[0] == 'constant' else None
        if key_ready:
            for receiver, target, write in tuple(self.keys.get(point, ())):
                for container in tuple(self.s.values[receiver]):
                    self.delta_stats['dynamic_key_accesses'] += 1
                    self.access(container, selected, target, write)
        for target in tuple(self.updates.get(point, ())):
            for container in tuple(self.s.values[target]):
                self.copy(value, container)
        if value[0] == 'container':
            for source in tuple(self.update_targets.get(point, ())):
                for container in tuple(self.s.values[source]):
                    self.copy(container, value)
        for target in tuple(self.iterators.get(point, ())):
            if value[0] == 'iterator':
                self.iter_sources[value[1]].add(target)
                for container in tuple(self.s.values[value[1]]):
                    self.iterate(container, target)
            elif value[0] == 'source_deferred':
                self.s.generators.advance(value, target)
        for target in tuple(self.iter_sources.get(point, ())):
            self.iterate(value, target)
        if key_ready:
            for container, target in tuple(self.method_keys.get(point, ())):
                self.delta_stats['dynamic_key_accesses'] += 1
                self.access(container, selected, target, False)
        for key in tuple(self.pack_watch.get(point, ())):
            retry = self.pending_invocations.get(key)
            if retry is not None and retry():
                self.pending_invocations.pop(key, None)
                for watched in (key[1].positional_pack, key[1].keyword_pack):
                    if watched is not None:
                        self.pack_watch[watched].discard(key)
