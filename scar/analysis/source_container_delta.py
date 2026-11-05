"""Incremental notifications for the existing source-content relation.

The initial subscription replays existing contents. A later write visits only
its new (key, source) pair; it does not replay every older entry for every
iterator and copy subscriber. Original source ports, labels, key-presence
facts, default edges and descending-position constraints are unchanged.

This implementation is independent of the production solver until its
relation-equivalence gate passes. It does not execute the target program.
"""
from scar.analysis.normal_containers import ContainerFlow


class DeltaContainerFlow(ContainerFlow):
    def __init__(self, solver, units):
        self.delta_stats = dict(copy_replays=0, copy_reuses=0,
                                copy_deltas=0, iterator_deltas=0)
        super().__init__(solver, units)

    def _iterator_delta(self, container, key, source, target):
        if container[2] == 'MAPPING':
            if key is not None:
                self.s.add(target, ('constant', key[0], key[1]))
        else:
            # iterate() originally calls read(None), which contributes this
            # unknown-selection label in addition to the write-key label
            # supplied by the direct readers below.
            self.link(source, target, container[1])

    def _copy_delta(self, source, target, key, point):
        self.delta_stats['copy_deltas'] += 1
        if target[2] == 'MAPPING' and source[2] == target[2]:
            self.write(target, key, point)
        elif source[2] != 'MAPPING':
            self.write(target, None, point)

    def _notify_write(self, container, key, source):
        # Preserve the existing direct-reader labels, including an unknown
        # write reaching every keyed reader. None is not a literal None key.
        for wanted in (key, None):
            for target in tuple(self.readers[container, wanted]):
                self.link(source, target, container[1], key)
        if key is None:
            for target in tuple(self.all_readers[container]):
                self.link(source, target, container[1])
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

    def copy(self, source, target):
        if (source[0] == 'container' and target[0] == 'container'):
            if target in self.copies[source]:
                self.delta_stats['copy_reuses'] += 1
                return
            self.delta_stats['copy_replays'] += 1
        # Includes original kind admission and deferred-consumer obligations.
        # Subscription precedes replay, so reentrant writes are not lost.
        super().copy(source, target)
