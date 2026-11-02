"""Original SG/AST ports and actual completion/hold checks for expressions."""
from __future__ import annotations

import ast

from scar.analysis.program_lowering import _REF
from scar.analysis.source_expression_lowering import BINARY_OPCODES, COMPARE_OPERATORS, source_operator
from scar.analysis.source_language import function_exception_types, require_source_tree
from scar.ir.program.control import ProtocolValueKind as P
from scar.ir.program.model import (AccessMode, Behavior, BlockArgument, CompletionResult, DataValue, ExitKind,
    LiteralOrigin, OperationResult, ProtocolValue, ReferenceValue, StateVersionValue,
    TerminatorKind, value_type)
from scar.ir.program.source_language import SourceLanguageCapability as C, SOURCE_EXPRESSION_PROTOCOLS
from scar.ir.program.structured import PythonProtocolKind as K
from scar.ir.semantics_v2 import Opcode
from scar.ir.v2.semantic import OperationKind, SemanticRelation


def _need(condition, detail):
    if not condition:
        raise ValueError('source expression: ' + detail)


def _span(reference):
    return reference.start_line, reference.end_line, reference.start_column, reference.end_column


def _node_span(node):
    return node.lineno, node.end_lineno, node.col_offset, node.end_col_offset


def validate_source_expressions(model, graph, interface, metadata, semantic, language, *,
                                source_tree=None, options=None, structural_only=False,
                                selected_operations=None,pending_protocols=None):
    protocols = {row.operation: row for row in model.protocols}
    selected = {identity for identity, row in protocols.items()
                if row.kind.value in SOURCE_EXPRESSION_PROTOCOLS
                and (selected_operations is None or identity in selected_operations)}
    if not selected:
        return set()
    _need(language is not None and C.SOURCE_EXPRESSIONS_314_V1 in language.capabilities,
          'new expression protocols require their explicit capability')
    # STRUCTURE loads the retained source too. It cannot certify an operator
    # tag against a guessed AST or against only its source line number.
    _need(isinstance(source_tree, ast.Module), 'original retained AST is required for operator/port identity')
    operations = {row.id: row for row in graph.operations}
    if pending_protocols is not None:
        for row in pending_protocols:
            if row.operation not in operations:
                continue
            _need(row.operation not in protocols or protocols[row.operation] == row,
                  'pending query changed an existing original protocol record')
            protocols[row.operation] = row
    values = {row.id: row for row in graph.values}
    blocks = {row.id: row for region in graph.regions for row in region.blocks}
    links = {row.operation: row for row in metadata.operation_links}
    uses = {(row.operation, row.use): row for row in metadata.use_links}
    value_sources = {(row.value, row.source.atom_id) for row in metadata.value_links}
    own_regions = {row.id: region.id for region in graph.regions for row in region.blocks}
    positions = {identity: (block.id, index) for block in blocks.values()
                 for index, identity in enumerate(block.operations)}
    order = {identity: index for index, identity in enumerate(operations)}

    def arguments(operation):
        indexed = {use.id: use for use in operation.uses}
        return tuple(indexed[key] for key in operation.invoke_arguments)

    def failure_pending(operation, failed):
        # String primitives explicitly release interpreter-consumed inputs at
        # the beginning of each completion. The pending query is at the INVOKE
        # landing, before those releases, whereas C0/C1's handoff query is at
        # its later propagation boundary. Reconstruct precisely that prefix;
        # never treat a failed string input as an unconsumed outer reference.
        offset, post_world, released = 0, failed.arguments[-1], ()
        marker = protocols.get(operation.id)
        if marker is not None and marker.kind in (K.FSTRING_CONVERT, K.FSTRING_FORMAT, K.BUILD_STRING):
            refs = tuple(use.value for use in arguments(operation)[:-1])
            consumed = refs
            if marker.kind is K.FSTRING_CONVERT or (marker.kind is K.FSTRING_FORMAT
                    and type(values[refs[1]].origin) is LiteralOrigin
                    and values[refs[1]].origin.value is None):
                consumed = refs[:1]
            for reference in reversed(consumed):
                _need(offset < len(failed.operations), 'string failure lost its consumed-input release')
                release = operations[failed.operations[offset]]
                source = uses.get((release.id, release.uses[0].id)) if release.uses else None
                _need(protocols.get(release.id) is not None
                      and protocols[release.id].kind is K.FRAME_RELEASE_TEMPORARY
                      and len(release.uses) == 2 and release.uses[0].value == reference
                      and source is not None and source.role == 'fstring-consumed-reference'
                      and release.uses[-1].value == post_world and len(release.results) == 1,
                      'string failure reordered its original consumed references or post-world')
                post_world = release.results[0]; offset += 1
            released = consumed
        if len(failed.arguments) == 3 and type(values[failed.arguments[1]]) is ProtocolValue:
            _need(values[failed.arguments[1]].protocol is P.DRIVE_CALLER_CONTEXT,
                  'lazy failure carries a different protocol context')
            _need(offset < len(failed.operations), 'lazy failure has no original PEP479 adapter')
            adapter = operations[failed.operations[offset]]
            _need(protocols.get(adapter.id) is not None
                  and protocols[adapter.id].kind is K.GENERATOR_ESCAPE_STOPITER_TO_RUNTIME_ERROR
                  and adapter.terminator is not None and adapter.terminator.kind is TerminatorKind.INVOKE
                  and tuple(use.value for use in arguments(adapter)) ==
                      (failed.arguments[0], post_world),
                  'lazy failure bypasses its original exception/post-world adapter')
            outcomes = []
            for edge in adapter.terminator.successors:
                block = blocks[edge.block]
                _need(bool(block.operations), 'PEP479 outcome lost its frame cleanup')
                cleanup = operations[block.operations[0]]
                _need(protocols.get(cleanup.id) is not None and protocols[cleanup.id].kind is K.FRAME_EXIT
                      and cleanup.uses[-1].value == block.arguments[-1]
                      and [use.value for use in cleanup.uses if uses[cleanup.id, use.id].role == 'held-payload']
                          == [block.arguments[0]], 'PEP479 outcome changed exception/frame/post-world')
                outcomes.append(tuple(use.value for use in cleanup.uses
                    if uses[cleanup.id, use.id].role == 'held-temporary'))
            _need(len(outcomes) == 2 and outcomes[0] == outcomes[1],
                  'lazy adapter outcomes disagree on pending references')
            return outcomes[0] + released
        if len(failed.arguments) == 3:
            from scar.analysis.source_function_try_validation import exception_handoff_holds
            _need(all(type(values[value]) is ReferenceValue for value in failed.arguments[:2]),
                  'paired failure lost original exception/traceback')
            return exception_handoff_holds(failed.id, operations, protocols, blocks, uses) + released
        from scar.analysis.source_slice_validation import _raw_handoff_holds
        return _raw_handoff_holds(failed, operation, operations, protocols, values, uses)

    def forward_reference(operation, protocol, link):
        """The same helper result survives to its explicit ownership boundary."""
        _need(C.SOURCE_REFERENCE_LIFETIME_314_V1 in language.capabilities,
              'helper forwarding cannot silently upgrade the historical expression profile')
        nodes = [node for node in require_source_tree(source_tree, metadata.source, protocol.source)
                 if isinstance(node, (ast.Dict, ast.List, ast.ListComp, ast.SetComp, ast.DictComp))]
        _need(len(nodes) == 1 and link.source == protocol.source and link.semantic_operation is None
              and link.opcode is None, 'forward marker has no original helper result source')
        node, = nodes
        _need(operation.terminator is None and operation.callee is None and not operation.effects_complete
              and set(operation.behaviors) == {Behavior.READ, Behavior.WRITE, Behavior.MEMORY}
              and len(operation.uses) == 2 and len(operation.results) == len(operation.accesses) == 1,
              'ownership forwarding is an ordinary frame transition, not a call or new reference')
        reference, before = operation.uses
        access = operation.accesses[0]
        _need(type(values[reference.value]) is ReferenceValue
              and type(values[before.value]) is StateVersionValue
              and type(values[operation.results[0]]) is StateVersionValue
              and value_type(values[before.value]) == value_type(values[operation.results[0]])
              and access.before == before.id and access.after == operation.results[0]
              and access.mode is AccessMode.READ_WRITE and not access.full_overwrite,
              'forwarding changed its existing reference or coarse-world continuity')
        source = uses.get((operation.id, reference.id))
        _need(source is not None and source.source == protocol.source
              and (source.role, source.index) == ('forwarded-expression-reference', 0)
              and source.semantic_value is None
              and (reference.value, protocol.source.atom_id) in value_sources,
              'forwarded reference is not the original expression result')
        origin = values[reference.value].origin
        expected = K.BUILD_MAP if isinstance(node, ast.Dict) else (
            K.BUILD_DISPLAY_LIST if isinstance(node, ast.List) else K.COMPREHENSION_BUILD)
        producers = [identity for identity, marker in protocols.items()
            if marker.kind is expected and marker.source == protocol.source
            and operations[identity].terminator is not None
            and any(edge.kind is ExitKind.NORMAL and type(origin) is BlockArgument
                    and origin.index == 0 and edge.block == origin.block
                    and blocks[edge.block].arguments[0] == reference.value
                    for edge in operations[identity].terminator.successors)]
        _need(len(producers) == 1, 'forwarded result lost its exact helper NORMAL producer')
        holders = [identity for identity, marker in protocols.items()
            if marker.kind is K.FRAME_HOLD_TEMPORARY and marker.source == protocol.source
            and order[identity] < order[operation.id] and len(operations[identity].uses) == 2
            and operations[identity].uses[0].value == reference.value]
        _need(len(holders) == 1, 'forwarding must transfer one original helper-owned hold instance')
        held = holders[0]; block, offset = positions[held]
        pending, seen, reached = [(block, offset + 1)], set(), False
        while pending:
            point = pending.pop()
            if point in seen:
                continue
            seen.add(point)
            _need(len(seen) <= max(32, len(operations) * 2), 'helper forwarding exceeds its finite CFG')
            block, offset = point
            _need(offset < len(blocks[block].operations), 'helper result falls out before ownership transfer')
            identity = blocks[block].operations[offset]
            if identity == operation.id:
                reached = True; continue
            current, marker = operations[identity], protocols.get(identity)
            kind = marker.kind if marker is not None else None
            if kind in (K.FRAME_RELEASE_TEMPORARY, K.FRAME_FORWARD_TEMPORARY, K.FRAME_HOLD_TEMPORARY):
                _need(current.uses[0].value != reference.value,
                      'helper result hold was released, duplicated or already forwarded')
            term = current.terminator
            if term is None:
                pending.append((block, offset + 1)); continue
            if term.kind is TerminatorKind.INVOKE:
                operands = arguments(current)
                refs = tuple(use.value for use in operands[:-1])
                if reference.value in refs:
                    _need(kind in (K.DICT_UPDATE, K.MAP_ADD, K.COMPREHENSION_ADD,
                                   K.APPEND_DISPLAY, K.EXTEND_DISPLAY)
                          and refs[0] == reference.value and reference.value not in refs[1:],
                          'helper result entered an unproved consuming primitive before forwarding')
                pending.extend((edge.block, 0) for edge in term.successors if edge.kind is ExitKind.NORMAL)
                if kind is K.COMPREHENSION_NEXT:
                    # The comprehension checker independently owns the exact
                    # NEXT failure -> StopIteration matcher -> natural edge.
                    # Only that original exhaustion edge returns the helper's
                    # result; the other arm propagates an exception.
                    failed = blocks[term.successors[1].block]
                    branch = operations[failed.operations[-1]]
                    match = operations[failed.operations[-2]]
                    _need(branch.terminator is not None and branch.terminator.kind is TerminatorKind.BRANCH
                          and protocols.get(match.id) is not None
                          and protocols[match.id].kind is K.MATCH_STOP_ITERATION
                          and branch.uses[0].value == match.results[0],
                          'helper exhaustion lost its original NEXT/matcher/branch')
                    pending.append((branch.terminator.successors[0].block, 0))
            elif term.kind in (TerminatorKind.JUMP, TerminatorKind.BRANCH):
                pending.extend((edge.block, 0) for edge in term.successors)
            else:
                _need(term.kind is TerminatorKind.RAISE,
                      'a normal helper result escapes its ownership boundary')
        _need(reached, 'helper-owned reference never reaches its forwarding operation')

    for identity in selected:
        operation, protocol, link = operations[identity], protocols[identity], links[identity]
        if protocol.kind is K.FRAME_FORWARD_TEMPORARY:
            forward_reference(operation, protocol, link)
            continue
        index_rule = protocol.kind is K.SOURCE_INDEX
        if index_rule:
            _need(C.SOURCE_REFERENCE_LIFETIME_314_V1 in language.capabilities,
                  'source index lifetime requires its distinct capability')
        binary = protocol.kind is K.SOURCE_BINARY
        expected_type = ast.Subscript if index_rule else ast.BinOp if binary else ast.Compare
        nodes = [node for node in require_source_tree(source_tree, metadata.source, protocol.source)
                 if isinstance(node, expected_type)]
        _need(len(nodes) == 1, 'primitive lost its unique original source expression')
        node, = nodes
        selector = 'Subscript' if index_rule else source_operator(node)
        definition = semantic.definitions.get(link.semantic_operation)
        atom = semantic.source_atoms.get(link.source.atom_id)
        _need(atom is not None and atom.reference == link.source == protocol.source
              and atom.kind == expected_type.__name__ and definition is not None
              and definition.kind is (OperationKind.INDEX if index_rule else OperationKind.OPERATOR)
              and definition.metadata.get('ast_type') == expected_type.__name__
              and definition.code_id == link.source.atom_id.wire
              and link.source.atom_id in definition.source_atoms and len(definition.output_slots) == 1,
              'expression has no original SG/source operator/output')
        expected_opcode = Opcode.INDEX if index_rule else BINARY_OPCODES[selector] if binary else (
            Opcode.IS if selector == 'Is' else Opcode.IS_NOT if selector == 'IsNot' else Opcode.OPAQUE)
        _need(link.opcode is expected_opcode, 'operator selector/source opcode differs')
        args = arguments(operation)
        _need(operation.terminator is not None and operation.terminator.kind is TerminatorKind.INVOKE
              and operation.callee is None and not operation.effects_complete and len(args) == (3 if index_rule else 4)
              and all(type(values[use.value]) is ReferenceValue for use in args[:2])
              and (index_rule or type(values[args[2].value]) is DataValue
              and values[args[2].value].data_type == 'builtins.str'
              and type(values[args[2].value].origin) is LiteralOrigin
              and values[args[2].value].origin.value == selector)
              and type(values[args[-1].value]) is StateVersionValue
              and all(tag in operation.behaviors for tag in (Behavior.CONTROL, Behavior.READ, Behavior.WRITE)),
              'incomplete expression must retain two references, exact DATA operator and world')
        state_type = value_type(values[args[-1].value])
        normal, failure = operation.terminator.successors
        lazy = len(operation.uses) == len(args) + 2
        failed_types = (_REF, state_type) if lazy else function_exception_types(language, _REF, state_type)
        _need(tuple((row.kind, row.types) for row in operation.completions)
              == ((ExitKind.NORMAL, (_REF, state_type)), (ExitKind.RAISE, failed_types))
              and (normal.kind, failure.kind) == (ExitKind.NORMAL, ExitKind.RAISE),
              'expression result/exception/post-world completion types differ')
        for edge, signature in zip((normal, failure), operation.completions):
            landing = blocks[edge.block]
            _need(own_regions[edge.block] == values[args[-1].value].region,
                  'expression completion crossed a different frame')
            if lazy:
                index = (normal, failure).index(edge)
                forward = operation.uses[len(args) + index]
                _need(type(values[forward.value]) is ProtocolValue
                      and values[forward.value].protocol is P.DRIVE_CALLER_CONTEXT
                      and edge.arguments == (CompletionResult(0), forward.id, CompletionResult(1))
                      and len(landing.arguments) == 3
                      and type(values[landing.arguments[1]]) is ProtocolValue
                      and values[landing.arguments[1]].protocol is P.DRIVE_CALLER_CONTEXT,
                      'lazy completion lost its exact caller forwarding')
            else:
                _need(operation.uses == args and edge.arguments == tuple(CompletionResult(i)
                      for i in range(len(signature.types)))
                      and tuple(value_type(values[value]) for value in landing.arguments) == signature.types,
                      'completion lost its own ordered payload/post-world ports')
        children = ((node.value, node.slice) if index_rule else
                    (node.left, node.right if binary else node.comparators[0]))
        if index_rule:
            _need(isinstance(node.ctx, ast.Load) and not isinstance(node.slice, (ast.Slice, ast.Tuple)),
                  'source index requires its exact ordinary Load key')
        original_ports = {edge.target.id for edge in semantic.edges.values()
                          if edge.source.id == definition.id and edge.relation is SemanticRelation.READS_SLOT}
        roles = ('receiver', 'index') if index_rule else ('left', 'right')
        for index, (child, role, use) in enumerate(zip(children, roles, args[:2])):
            source = uses.get((identity, use.id))
            _need(source is not None and (source.role, source.index) == (role, index)
                  and _span(source.source) == _node_span(child), 'ordered operand Use/source differs')
            declarations = [row for row in semantic.definitions.values()
                if row.code_id == source.source.atom_id.wire and source.source.atom_id in row.source_atoms
                and set(row.output_slots) & original_ports]
            _need(len(declarations) == 1, 'operand lost its original SG parent/output port')
            origin = values[use.value].origin
            matched = (use.value, source.source.atom_id) in value_sources
            if not matched and type(origin) is BlockArgument and origin.index == 0:
                producers = [row for row in operations.values() if row.terminator is not None
                    and row.terminator.kind is TerminatorKind.INVOKE
                    and links[row.id].source == source.source
                    and any(edge.kind is ExitKind.NORMAL and edge.block == origin.block
                            and edge.arguments[0] == CompletionResult(0) for edge in row.terminator.successors)]
                matched = len(producers) == 1
            _need(matched, 'operand value is detached from its original source producer')
            if isinstance(child, ast.Constant):
                _need(type(origin) is LiteralOrigin and type(origin.value) is type(child.value)
                      and origin.value == child.value, 'scalar literal changed original value/type')
        if index_rule:
            from scar.ir.program.state_addresses import AddressCoverage, AddressEffect, Element, InvokeStateOperand, ReferenceOwner
            addresses = [row for row in graph.state_address_refinements if row.site.operation == identity]
            expected = AddressEffect(ReferenceOwner(args[0].id), (Element(args[1].id),), AccessMode.READ)
            _need(len(addresses) == 1 and addresses[0].site == InvokeStateOperand(identity, args[-1].id)
                  and addresses[0].coverage is AddressCoverage.PARTIAL and addresses[0].protocol is None
                  and addresses[0].effects == (expected,),
                  'source index address is detached from its original receiver/key/world Uses')
        else:
            tag_source = uses.get((identity, args[2].id))
            _need(tag_source is not None and tag_source.source == protocol.source
                  and (tag_source.role, tag_source.index) == ('source-operator', 0)
                  and tag_source.semantic_value is None, 'protocol selector is not its original static source configuration')
        from scar.analysis.source_slice_validation import _validate_local_transfer
        _validate_local_transfer(identity, operations, protocols, blocks, values, links, uses, language,
            target_operands=args[:2], target_failure_consumes=not (binary or index_rule), failure_pending=failure_pending)
    return selected


__all__ = ['validate_source_expressions']
