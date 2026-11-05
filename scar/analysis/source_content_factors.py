"""Factor stored content links without changing their transfer relations.

Only sources with equal complete target neighborhoods share a factor.  This
preserves each original container/key label, including direct default links,
and never forms a product between unequal neighborhoods.
"""
from collections import defaultdict
from hashlib import sha256
from pathlib import Path
from time import monotonic

from scar.analysis.normal_output import write_table
from scar.analysis.source_template_links import _json
from scar.ir.program import normal_targets as T, source_productions as P
from scar.ir.program.content_factors import ContentFactor
from scar.ir.record_codec import _encode, _record_tags


def factor_records(flow):
    """Yield deterministic equal-neighborhood factors after one link scan.

    Private transfer indices are used only to build the adjacency relation.
    Endpoint ordering and factor IDs use canonical original interface bytes,
    so private index numbering and link insertion order do not affect output.
    """
    neighborhoods = defaultdict(lambda: defaultdict(set))
    labels = {}
    for (source, target, container, key), link in flow.links.items():
        group = container, key
        neighborhoods[group][source].add(target)
        labels.setdefault(group, link.key)

    tags = _record_tags(P.PRODUCTION_RECORD_TAGS)
    endpoints, wires = {}, {}

    def endpoint(point):
        if point not in endpoints:
            endpoints[point] = flow.s.gp(point)
        return endpoints[point]

    def wire(point):
        if point not in wires:
            wires[point] = _json(_encode(endpoint(point), tags))
        return wires[point]

    def group_wire(group):
        return _json(_encode(dict(container=endpoint(group[0]), key=labels[group]), tags))

    for group in sorted(neighborhoods, key=group_wire):
        equal_targets = defaultdict(list)
        for source, targets in neighborhoods[group].items():
            equal_targets[frozenset(targets)].append(source)
        # Only O(E) adjacency memberships are retained.  No source/target
        # product is built for sorting, output, hashing, or statistics.
        ordered = [(tuple(sorted(targets, key=wire)), sources)
                   for targets, sources in equal_targets.items()]
        ordered.sort(key=lambda item: tuple(wire(point) for point in item[0]))
        container, key = endpoint(group[0]), labels[group]
        for targets, sources in ordered:
            target_endpoints = tuple(endpoint(point) for point in targets)
            payload = dict(container=container, key=key, targets=target_endpoints)
            identity = sha256(_json(_encode(payload, tags))).hexdigest()
            yield ContentFactor(identity, container, key,
                tuple(endpoint(point) for point in sorted(sources, key=wire)),
                target_endpoints)


def expand_factor(factor):
    """Lazily recover the original labeled ContentLink relation for queries."""
    for source in factor.sources:
        for target in factor.targets:
            yield T.ContentLink(source, target, factor.container, factor.key,
                semantics=factor.semantics)


def write_factors(flow, out, prefix=''):
    """Write factors and their receipt without expanding their products."""
    started = monotonic()
    stats = dict(factors=0, inputs=0, outputs=0, expanded_pairs=0)

    def records():
        for factor in factor_records(flow):
            stats['factors'] += 1
            stats['inputs'] += len(factor.sources)
            stats['outputs'] += len(factor.targets)
            stats['expanded_pairs'] += len(factor.sources) * len(factor.targets)
            yield factor

    descriptor = write_table(Path(out) / (prefix + 'content-factors.jsonl.gz'), records())
    cycles = write_table(Path(out) / (prefix + 'content-index-cycles.jsonl.gz'),
                         getattr(flow,'index_cycles',{}).values())
    if stats['expanded_pairs'] != len(flow.links):
        raise ValueError('content factors do not preserve the stored link count')
    stats['seconds'] = monotonic() - started
    return {prefix + 'content_factors': descriptor,
            prefix + 'content_encoding': 'EQUAL_NEIGHBORHOODS_V1',
            prefix + 'content_links': len(flow.links),
            prefix + 'content_index_cycles': cycles,
            prefix + 'content_events': getattr(flow,'content_events',0),
            prefix + 'content_factor_stats': stats}
