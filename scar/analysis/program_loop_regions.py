"""Source-loop construct membership over original operations and ports.

This projection includes initializer, test, body, else and source-attributed
cleanup operations. It neither takes a CFG reachability closure nor claims
that source containment is a control/effect proof. External handlers/cleanup
stay outside, with their original boundary interfaces available to cut queries.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, replace

from scar.analysis.program_dependencies import ProgramDependencyGraph
from scar.analysis.program_loop_views import LoopTemplateView, loop_template_views
from scar.ir.program.dependencies import DependencyFrontier, DependencyPoint, GraphNamespace
from scar.ir.program.ids import OperationID, ValueID
from scar.ir.program.source import LoweringMetadata
from scar.ir.program.source_call_bindings import SourceBodyNamespace
from scar.ir.program.source_references import SourceArtifactLocator
from scar.ir.program.structured import StructuredBodyModel
from scar.ir.record_codec import decode


def _need(ok, detail):
    if not ok:
        raise ValueError('source loop construct: ' + detail)


def _inside(outer, inner):
    return ((outer.path, outer.fingerprint) == (inner.path, inner.fingerprint)
        and (outer.start_line, outer.start_column) <= (inner.start_line, inner.start_column)
        and (inner.end_line, inner.end_column) <= (outer.end_line, outer.end_column))


def _overlaps(left, right):
    return ((left.path, left.fingerprint) == (right.path, right.fingerprint)
        and (left.start_line, left.start_column) < (right.end_line, right.end_column)
        and (right.start_line, right.start_column) < (left.end_line, left.end_column))


@dataclass(frozen=True, slots=True)
class LoopConstructView:
    template: LoopTemplateView
    members: tuple[OperationID, ...]
    direct_members: tuple[OperationID, ...]
    internal_block_arguments: tuple[ValueID, ...]
    source_mapping: SourceArtifactLocator | None
    source_gap_locators: tuple[SourceArtifactLocator, ...]
    frontiers: tuple[DependencyFrontier, ...]
    member_provenance_knowledge: str
    kind: str = 'SOURCE_LOOP_CONSTRUCT'
    scope_complete: bool = False
    iteration_knowledge: str = 'TEMPLATE_ONLY'
    content_invariance: str = 'UNPROVED'

    def __post_init__(self):
        _need(type(self.template) is LoopTemplateView, 'original loop template required')
        self.template.__post_init__()
        for rows, kind in ((self.members, OperationID), (self.direct_members, OperationID),
                (self.internal_block_arguments, ValueID), (self.source_gap_locators, SourceArtifactLocator),
                (self.frontiers, DependencyFrontier)):
            _need(type(rows) is tuple and all(type(row) is kind for row in rows)
                and len(set(rows)) == len(rows), 'immutable unique original IDs/locators/frontiers required')
        _need(set(self.direct_members) <= set(self.members), 'direct members escape construct membership')
        if self.source_mapping is None:
            _need(any(frontier.kind == 'LOOP_SOURCE_METADATA_NOT_RECORDED' for frontier in self.frontiers),
                'missing metadata must retain its original coverage frontier')
        else:
            _need(type(self.source_mapping) is SourceArtifactLocator, 'original metadata source locator required')
            self.source_mapping.__post_init__()
            _need(self.source_mapping.artifact == self.template.namespace.graph.artifact
                and self.source_mapping.pointer == '#/metadata/operation_links', 'source mapping differs from original body')
        _need(self.member_provenance_knowledge in ('COMPLETE_FOR_RECORDED_OPERATIONS', 'PARTIAL')
            and self.kind == 'SOURCE_LOOP_CONSTRUCT' and self.scope_complete is False
            and self.iteration_knowledge == 'TEMPLATE_ONLY' and self.content_invariance == 'UNPROVED',
            'source membership cannot assert control/effect closure, runtime iteration or invariance')

    def expand(self, graph):
        """Load original operations through the existing receipt-owned graph."""
        _need(type(graph) is ProgramDependencyGraph, 'expand requires the existing ProgramDependencyGraph')
        self.__post_init__()
        index = graph.load_index(self.template.namespace)
        _need(index.graph.root == self.template.namespace.root
            and all(identity in index.operations and
                index._blocks[index._operation_blocks[identity]] == self.template.loop.region
                for identity in self.members), 'members do not belong to the original source graph/region')
        return tuple(index.operations[identity] for identity in self.members)


def loop_construct_views(body, *, templates=None):
    """Select source-attributed operations, retaining every unresolved member.

    The input is a normal session-loaded source body. Indices and source links
    are shared; no operation objects, graph, block, iteration or CFG are copied.
    ``templates`` may reuse that body's complete already checked template tuple.
    A query can select one returned construct without losing its child context.
    """
    original_templates = loop_template_views(body)
    if templates is not None:
        _need(templates == original_templates,
            'supplied templates differ from freshly checked original loop ports')
    templates = original_templates
    _need(type(templates) is tuple and all(type(item) is LoopTemplateView for item in templates),
        'templates must be the original complete immutable tuple')
    _need(type(body.namespace) is SourceBodyNamespace and body.document.get('structured') is not None,
        'original structured body evidence is not recorded')
    original = decode(StructuredBodyModel, body.document['structured'])
    namespace = GraphNamespace.from_source(body.namespace)
    _need(tuple(item.loop for item in templates) == original.loops
        and all(item.namespace == namespace and item.definition == original.definition for item in templates),
        'templates differ from the original body/recorded loop collection')
    index = body.index
    _need(index.graph is body.graph and original.region == namespace.root,
        'source body index/region differs from its original graph')
    metadata = getattr(body, 'metadata', None)
    if metadata is None and body.document.get('metadata') is not None:
        metadata = decode(LoweringMetadata, body.document['metadata'])
    _need(metadata is None or type(metadata) is LoweringMetadata, 'invalid original source metadata')
    local = tuple(operation.id for operation in body.graph.operations
        if index._blocks[index._operation_blocks[operation.id]] == original.region)
    sources = defaultdict(list)
    if metadata is not None:
        for ordinal, link in enumerate(metadata.operation_links):
            _need(link.operation in index.operations, 'source link refers outside the original graph')
            sources[link.operation].append((ordinal, link.source))
    mapping = replace(namespace.graph, pointer='#/metadata/operation_links') if metadata is not None else None
    selected, diagnostics, gaps = {}, {}, {}
    for template in templates:
        template.__post_init__()
        source, members, notes, gap_sources = template.loop.source, set(), {}, []
        at = lambda identity: DependencyPoint(namespace, identity, None)
        def note(identity, kind, detail):
            notes[DependencyFrontier(at(identity), kind, detail)] = None
        for identity in local:
            rows = sources.get(identity, ())
            if not rows:
                note(identity, 'LOOP_MEMBER_SOURCE_NOT_RECORDED',
                    'This original operation has no recorded source mapping; its loop membership is unresolved.')
                continue
            included = tuple(_inside(source, reference) for _, reference in rows)
            if all(included):
                members.add(identity)
            elif any(included):
                note(identity, 'LOOP_MEMBER_SOURCE_AMBIGUOUS',
                    'Original operation_links rows ' + ','.join(str(number) for number, _ in rows)
                    + ' have both inside and outside sources; the operation was not arbitrarily included.')
            elif any((reference.path, reference.fingerprint) != (source.path, source.fingerprint)
                     for _, reference in rows):
                note(identity, 'LOOP_MEMBER_SOURCE_VERSION_OPEN',
                    'Original operation provenance includes another source version/file; construct ownership is not inferred.')
        if metadata is None:
            note(template.loop.header, 'LOOP_SOURCE_METADATA_NOT_RECORDED',
                'Loop ports are recorded, but original operation source/coverage metadata is absent.')
        else:
            for number, gap in enumerate(metadata.gaps):
                if _overlaps(source, gap.source):
                    locator = replace(namespace.graph, pointer='#/metadata/gaps/' + str(number))
                    gap_sources.append(locator)
                    note(template.loop.header, 'LOOP_RETAINED_SOURCE_GAP',
                        locator.pointer + ': ' + gap.kind.value + ': ' + gap.detail)
        selected[source] = members
        diagnostics[source] = tuple(notes)
        gaps[source] = tuple(gap_sources)
    result = []
    root_entry = index.regions[original.region].entry
    for template in templates:
        source = template.loop.source
        nested = set()
        for child in template.nested_sources:
            _need(child in selected, 'direct child construct is absent from the original template collection')
            nested.update(selected[child])
        members = tuple(identity for identity in local if identity in selected[source])
        internal = tuple(value for block in index.regions[original.region].blocks
            if block.id != root_entry and block.operations
            and all(identity in selected[source] for identity in block.operations)
            for value in block.arguments)
        # A source correspondence gap is separate from effects/coverage gaps.
        partial = any(frontier.kind.startswith('LOOP_MEMBER_SOURCE_')
            or frontier.kind == 'LOOP_SOURCE_METADATA_NOT_RECORDED' for frontier in diagnostics[source])
        result.append(LoopConstructView(template, members,
            tuple(identity for identity in members if identity not in nested), internal,
            mapping, gaps[source], diagnostics[source],
            'PARTIAL' if partial else 'COMPLETE_FOR_RECORDED_OPERATIONS'))
    return tuple(result)


__all__ = ['LoopConstructView', 'loop_construct_views']
