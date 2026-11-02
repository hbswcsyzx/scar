"""Source attribute ports and conditional state paths over the original graph.

Attribute names are protocol selectors, not newly evaluated Python strings.
These helpers do not resolve descriptors, identify module objects, equate
receiver references, or prove that a setter committed its input.  Consumers
select the relevant owners and retain those conditions on their relations.
"""
from __future__ import annotations

import ast
from collections import defaultdict, deque
import hashlib

from scar.ir.record_codec import decode
from scar.ir.program.ids import BlockID, OperationID
from scar.ir.program.model import (
    AccessMode, ExitKind, ReferenceValue, StateVersionValue, TerminatorKind, UseRole,
)
from scar.ir.program.queries import ProgramIndex
from scar.ir.program.source import LoweringMetadata
from scar.ir.program.state_addresses import InvokeStateOperand, ObjectField, ReferenceOwner
from scar.ir.program.static_calls import StaticAttributeAccess
from scar.ir.program.structured import ControlEdgeReference
from scar.ir.semantics_v2 import Opcode
from scar.ir.v2.common import SourceReference
from scar.ir.v2.semantic import OperationKind, SemanticGraph, SemanticRelation
from scar.analysis.static_namespace import normal_reference, protocol_kinds


def _need(condition, detail):
    if not condition:
        raise ValueError('static field: ' + detail)


def _span(value):
    if isinstance(value, ast.AST):
        return value.lineno, value.end_lineno, value.col_offset, value.end_col_offset
    return value.start_line, value.end_line, value.start_column, value.end_column


def derive_attribute_accesses(body, *, source_text=None, semantic=None):
    """Recover explicitly source-mapped reads/writes without target execution.

    ``body`` carries its original namespace, graph/index and envelope. A public
    reader supplies the retained source text and original SG explicitly; the
    linker may use its already loaded immutable source context. A missing
    address refinement is not interpreted as an empty effect: the exact AST,
    SG and original receiver/world ports still describe the attribute read.
    Compiler-only attribute operations lacking this source adapter remain
    outside this function's scope, rather than acquiring invented source IDs.
    """
    context = getattr(body, 'context', None)
    if source_text is None and context is not None:
        source_text = context.docs['source']['text']
    if semantic is None and context is not None:
        semantic = context.semantic
    _need(type(source_text) is str and type(semantic) is SemanticGraph,
          'attribute derivation requires retained source text and its original SG')
    index = body.index
    _need(type(index) is ProgramIndex and index.graph is body.graph
          and body.namespace.region == body.graph.root,
          'attribute inputs belong to different original graphs')
    metadata = getattr(body, 'metadata', None)
    if metadata is None:
        metadata = decode(LoweringMetadata, body.document['metadata'])
    _need(body.namespace.entry == metadata.entry
          and (body.namespace.source is None
               or (body.namespace.source.path == metadata.source.path
                   and body.namespace.source.fingerprint == metadata.source.fingerprint)),
          'attribute namespace differs from its original source entry')
    _need('sha256:' + hashlib.sha256(source_text.encode()).hexdigest() == metadata.source.fingerprint,
          'attribute source text differs from the retained snapshot')
    module = getattr(body, 'module', None)
    if module is None and body.document.get('module') is not None:
        from scar.ir.program.module_entries import decode_frame_body
        module = decode_frame_body(body.document['module'])
    sources = module if module is not None else metadata
    operations = defaultdict(list)
    uses = defaultdict(list)
    for row in sources.operation_links:
        operations[row.operation].append(row)
    for row in sources.use_links:
        uses[row.operation].append(row)
    tree = ast.parse(source_text, filename=metadata.source.path, type_comments=True)
    attributes = defaultdict(list)
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            attributes[_span(node)].append(node)
    protocols = protocol_kinds(body.document)
    blocks = {block.id: block for region in body.graph.regions for block in region.blocks}
    reads = defaultdict(set)
    for edge in semantic.edges.values():
        if edge.relation is SemanticRelation.READS_SLOT:
            reads[edge.source.id].add(edge.target.id)
    by_atom = defaultdict(list)
    for definition in semantic.definitions.values():
        for atom in definition.source_atoms:
            by_atom[atom].append(definition)

    def reference(reference, node):
        if type(reference) is not SourceReference:
            return False
        atom = semantic.source_atoms.get(reference.atom_id)
        return (atom is not None
                and atom.reference == reference and atom.kind == type(node).__name__
                and reference.path == metadata.source.path
                and reference.fingerprint == metadata.source.fingerprint
                and _span(reference) == _span(node))

    result = []
    for identity, links in operations.items():
        writing = protocols.get(identity) == 'STORE_ATTRIBUTE'
        reading = any(link.opcode is Opcode.ATTRIBUTE for link in links)
        if not writing and not reading:
            continue
        _need(len(links) == 1, 'attribute operation has no unique source correspondence')
        link = links[0]
        _need(type(link.source) is SourceReference, 'attribute lacks an original source atom')
        nodes = attributes.get(_span(link.source), ())
        _need(len(nodes) == 1 and reference(link.source, nodes[0]),
              'attribute selector is not its exact original AST/SG occurrence')
        node = nodes[0]
        definition = semantic.definitions.get(link.semantic_operation)
        _need(definition is not None and definition.code_id == link.source.atom_id.wire
              and link.source.atom_id in definition.source_atoms
              and definition.source_file == metadata.source.path,
              'attribute does not retain its original SG definition')
        _need((writing and isinstance(node.ctx, ast.Store)
               and definition.metadata.get('role') == 'binding' and link.opcode is Opcode.OPAQUE)
              or (not writing and definition.kind is OperationKind.ATTRIBUTE
                  and definition.metadata.get('role') != 'binding'
                  and definition.metadata.get('attribute') == node.attr
                  and bool(definition.output_slots)),
              'attribute read/write role differs from its source definition')
        operation = index.operations[identity]
        _need(operation.terminator is not None
              and operation.terminator.kind is TerminatorKind.INVOKE,
              'attribute lacks its original normal/raise boundary')
        rows = uses[identity]
        receiver_role = 'heap-owner' if writing else 'receiver'
        owners = [row for row in rows if row.role == receiver_role and row.index == 0]
        _need(len(owners) == 1 and reference(owners[0].source, node.value),
              'attribute receiver source/role is not the original operand')
        owner = index.use_site(owners[0].use)
        _need(owner.operation == identity and owner.use.id in operation.invoke_arguments
              and owner.use.role is UseRole.REFERENCE
              and type(index.values[owner.use.value]) is ReferenceValue,
              'attribute receiver changed its original reference Use')
        children = [child for child in by_atom[owners[0].source.atom_id]
                    if child.code_id == owners[0].source.atom_id.wire
                    and child.metadata.get('role') != 'binding'
                    and set(child.output_slots) & reads[definition.id]]
        _need(len(children) == 1, 'attribute receiver is not its original SG input port')
        worlds = [use for use in operation.uses if use.id in operation.invoke_arguments
                  and use.role is UseRole.STATE_CONTENT
                  and type(index.values[use.value]) is StateVersionValue]
        _need(len(worlds) == 1, 'attribute lacks a unique original world Use')
        world = worlds[0]
        normal = [(ordinal, edge) for ordinal, edge in enumerate(operation.terminator.successors)
                  if edge.kind is ExitKind.NORMAL]
        _need(len(normal) == 1, 'attribute has no unique normal completion')
        edge = ControlEdgeReference(identity, normal[0][0])
        assigned = None
        value = None
        if writing:
            payloads = [row for row in rows if row.role == 'assigned-reference' and row.index == 0]
            _need(len(payloads) == 1 and payloads[0].source == link.source,
                  'attribute write lost its original assigned source Use')
            payload = index.use_site(payloads[0].use)
            _need(payload.operation == identity
                  and payload.use.role is UseRole.REFERENCE
                  and type(index.values[payload.use.value]) is ReferenceValue,
                  'attribute assigned operand is not its original reference')
            assigned = payload.use.id
            expected = owner.use.id, assigned, world.id
        else:
            output = normal_reference(index, identity, blocks=blocks)
            _need(output is not None and output[0] == edge,
                  'attribute read lost its normal reference result')
            value = output[1]
            expected = owner.use.id, world.id
        _need(operation.invoke_arguments == expected,
              'attribute operands differ from their original ordered receiver/payload/world')
        address = index.state_address(InvokeStateOperand(identity, world.id))
        mode = AccessMode.WRITE if writing else AccessMode.READ
        if writing or address['refinement'] is not None:
            effects = [item['effect'] for item in address['effects']]
            _need(len(effects) == 1 and type(effects[0].owner) is ReferenceOwner
                  and effects[0].owner.use == owner.use.id
                  and effects[0].path == (ObjectField(node.attr),)
                  and effects[0].mode is mode,
                  'attribute address changed its original receiver, field or access mode')
        result.append(StaticAttributeAccess(body.namespace, identity, link.source, node.attr,
                      owner.use.id, world.id, edge, value, assigned))
    return tuple(result)


class FieldCFGPaths:
    """Original CFG witnesses under explicitly selected field-store guards.

    A supplied kill set is conditional: the consumer must retain that these
    selected normal setter completions commit the field binding. Raising
    setters may have partial effects and never become empty writes here.
    One witness proves a possible path, not coverage of every program path.
    """
    def __init__(self, body_or_index, *, max_steps=4096, check=None):
        index = body_or_index if type(body_or_index) is ProgramIndex else body_or_index.index
        _need(type(index) is ProgramIndex and type(max_steps) is int and max_steps > 0,
              'field CFG needs its original index and a positive traversal budget')
        _need(check is None or callable(check), 'field CFG check must be callable')
        self.index, self.max_steps, self.check = index, max_steps, check or (lambda: None)
        self.blocks = {block.id: block for region in index.graph.regions for block in region.blocks}
        self.owners = {identity: (region.id, block.id, offset)
                       for region in index.graph.regions for block in region.blocks
                       for offset, identity in enumerate(block.operations)}

    def _query(self, start, operation, field, kills):
        _need(type(start) is BlockID and type(operation) is OperationID
              and type(field) is str and bool(field) and operation in self.owners,
              'field path needs original block/operation and a field selector')
        region, target, offset = self.owners[operation]
        _need(start in self.blocks and self.index._blocks[start] == region,
              'field path starts outside its original query region')
        kills = frozenset(kills)
        for identity in kills:
            _need(type(identity) is OperationID and identity in self.owners
                  and self.owners[identity][0] == region,
                  'field kill belongs to a different original graph/region')
            op = self.index.operations[identity]
            _need(op.terminator is not None and op.terminator.kind is TerminatorKind.INVOKE,
                  'field replacement needs its original completion boundary')
            worlds = [use for use in op.uses if use.id in op.invoke_arguments
                      and type(self.index.values[use.value]) is StateVersionValue]
            _need(len(worlds) == 1, 'field replacement lost its original world')
            address = self.index.state_address(InvokeStateOperand(identity, worlds[0].id))
            _need(any(item['effect'].path == (ObjectField(field),)
                      and item['effect'].mode in (AccessMode.WRITE, AccessMode.READ_WRITE)
                      for item in address['effects']),
                  'field replacement changed its declared selector or write mode')
        return region, target, offset, kills

    def _edge(self, reference):
        _need(type(reference) is ControlEdgeReference
              and reference.operation in self.index.operations,
              'field path edge is not an original control reference')
        op = self.index.operations[reference.operation]
        _need(op.terminator is not None
              and 0 <= reference.successor_index < len(op.terminator.successors),
              'field path edge has no original successor')
        return op.terminator.successors[reference.successor_index]

    def find_path(self, start_block, query_operation, field, kill_operations=()):
        region, target, offset, kills = self._query(start_block, query_operation, field, kill_operations)
        pending = deque(((start_block, (), ()),))
        seen = set()
        while pending:
            self.check()
            block_id, path, prefix = pending.popleft()
            if block_id in seen:
                continue
            seen.add(block_id)
            if len(seen) > self.max_steps:
                raise OverflowError('field CFG reachability budget exhausted')
            block = self.blocks[block_id]
            local = block.operations[:offset] if block_id == target else block.operations
            intervening = prefix + tuple(local)
            if block_id == target:
                if not any(identity in kills for identity in local):
                    return path, intervening
                continue
            if not block.operations:
                continue
            op = self.index.operations[block.operations[-1]]
            if op.terminator is None:
                continue
            for ordinal, edge in enumerate(op.terminator.successors):
                if op.id in kills and edge.kind is ExitKind.NORMAL:
                    continue
                if edge.block not in self.blocks or self.index._blocks[edge.block] != region:
                    continue
                pending.append((edge.block, path + (ControlEdgeReference(op.id, ordinal),), intervening))
        return None

    def validate_path(self, start_block, query_operation, field, kill_operations, path, intervening):
        region, target, offset, kills = self._query(start_block, query_operation, field, kill_operations)
        _need(type(path) is tuple and type(intervening) is tuple,
              'field path must retain ordered edge/operation tuples')
        if len(path) > self.max_steps:
            raise OverflowError('field CFG witness budget exhausted')
        current, traversed = start_block, []
        for reference in path:
            self.check()
            block = self.blocks[current]
            _need(block.operations and reference.operation == block.operations[-1],
                  'field witness is not a contiguous original CFG path')
            edge = self._edge(reference)
            _need(not (reference.operation in kills and edge.kind is ExitKind.NORMAL),
                  'field witness crosses a selected committed replacement')
            _need(edge.block in self.blocks and self.index._blocks[edge.block] == region,
                  'field witness crosses another original region')
            traversed.extend(block.operations)
            current = edge.block
        _need(current == target, 'field witness does not reach its query operation')
        tail = self.blocks[current].operations[:offset]
        traversed.extend(tail)
        _need(tuple(traversed) == intervening and not any(identity in kills for identity in tail),
              'field witness changed original operations or crosses a replacement')
        return True


__all__ = ['derive_attribute_accesses', 'FieldCFGPaths']
