"""Bounded source/compiler/pending queries over existing f-string protocols.

No runtime string, conversion method, alternative graph or lifetime IR is
created. Primitive input consumption follows pinned CPython 3.14.7 bytecodes;
an unknown child contract never establishes the enclosing frame's lifetime.
"""
from __future__ import annotations

import ast
import dis

from scar.analysis.source_language import SourceLanguageOptions, require_source_tree
from scar.ir.program.model import ExitKind, LiteralOrigin, TerminatorKind
from scar.ir.program.structured import PythonProtocolKind as Kind
from scar.ir.v2.semantic import OperationKind


POLICY = "CPYTHON_314_FSTRING_SOURCE_V1"
_KINDS = frozenset((Kind.FSTRING_CONVERT, Kind.FSTRING_FORMAT, Kind.BUILD_STRING))


def _need(condition, detail):
    if not condition:
        raise ValueError("string source validation: " + detail)


def _span(node):
    return node.lineno, node.end_lineno, node.col_offset, node.end_col_offset


def _references(operation):
    return tuple(use.value for use in operation.uses[:-1])


def _consumed(operation, kind, values):
    refs = _references(operation)
    if kind is Kind.BUILD_STRING:
        return refs
    if kind is Kind.FSTRING_CONVERT:
        return refs[:1]  # The generated conversion selector has no hold.
    spec = values[refs[1]].origin
    return refs[:1] if type(spec) is LiteralOrigin and spec.value is None else refs


def _check_consumed_releases(operation, consumed, operations, protocols, blocks, use_links):
    """Inspect both actual CFG arms, not a producer-reported consumed set."""
    failure_exit = None
    for edge in operation.terminator.successors:
        block = blocks[edge.block]
        _need(len(block.operations) > len(consumed), "string completion lacks its input releases/continuation")
        for identity, reference in zip(block.operations, reversed(consumed)):
            release = operations[identity]
            protocol = protocols.get(identity)
            refs = _references(release)
            _need(protocol is not None and protocol.kind is Kind.FRAME_RELEASE_TEMPORARY
                  and refs == (reference,), "string completion lost or reordered a consumed input release")
            link = use_links.get((identity, release.uses[0].id))
            _need(link is not None and link.role == "fstring-consumed-reference",
                  "string input release lacks its original reference Use")
        following = operations[block.operations[len(consumed)]]
        first = use_links.get((following.id, following.uses[0].id)) if following.uses else None
        _need(first is None or first.role != "fstring-consumed-reference",
              "string completion releases an extra input hold")
        if edge.kind is ExitKind.RAISE:
            _need(protocols.get(following.id) is not None
                  and protocols[following.id].kind is Kind.FRAME_EXIT,
                  "string failure does not carry its post-world through FRAME_EXIT")
            failure_exit = tuple(use.value for use in following.uses
                if (link := use_links.get((following.id, use.id))) is not None
                and link.role == "held-temporary")
    _need(failure_exit is not None, "string primitive has no exceptional cleanup")
    return failure_exit


def _ordered_next(current, expected, own, operations, blocks, positions):
    """Every ordinary normal continuation must reach the next owned stage."""
    edge = operations[current].terminator.successors[0]
    pending, seen, found = [(edge.block, 0)], set(), set()
    while pending:
        position = pending.pop()
        if position in seen:
            continue
        seen.add(position)
        _need(len(seen) <= len(operations) * 2 + 1, "string staging traversal budget exceeded")
        block, index = blocks[position[0]], position[1]
        _need(index < len(block.operations), "string normal continuation falls out of a block")
        identity = block.operations[index]
        if identity in own:
            found.add(identity)
            continue
        operation = operations[identity]
        if operation.terminator is None:
            pending.append((block.id, index + 1))
        elif operation.terminator.kind is TerminatorKind.INVOKE:
            pending.append((operation.terminator.successors[0].block, 0))
        elif operation.terminator.kind in (TerminatorKind.JUMP, TerminatorKind.BRANCH):
            pending.extend((edge.block, 0) for edge in operation.terminator.successors)
        else:
            raise ValueError("string source validation: normal path skips a later string stage")
    _need(found == {expected}, "string stages can be reordered, repeated or skipped")


def _pending_group(group, sources, operations, protocols, blocks, positions, uses, values, failure_holds):
    """Track local ordered hold instances; leave the external prefix symbolic."""
    candidates = []
    for identity, operation in operations.items():
        protocol = protocols.get(identity)
        if protocol is None or protocol.kind is not Kind.FRAME_HOLD_TEMPORARY:
            continue
        link = uses.get((identity, operation.uses[0].id))
        if link is not None and link.role == "fstring-held-reference" and link.source.atom_id in sources:
            candidates.append(identity)
    _need(candidates, "string construction has no original input hold")
    order = {identity: index for index, identity in enumerate(operations)}
    begin = min(candidates, key=order.get)
    position, stack, prefix, seen = positions[begin], (), None, set()
    own, completed, frontiers = set(group), set(), []
    while position not in seen:
        seen.add(position)
        _need(len(seen) <= len(operations) + 1, "string pending traversal budget exceeded")
        block, index = blocks[position[0]], position[1]
        _need(index < len(block.operations), "string pending path falls out of a block")
        identity = block.operations[index]
        operation, protocol = operations[identity], protocols.get(identity)
        kind = protocol.kind if protocol is not None else None
        link = uses.get((identity, operation.uses[0].id)) if operation.uses else None
        if kind is Kind.FRAME_HOLD_TEMPORARY and identity in candidates:
            stack += ((identity, operation.uses[0].value),)
        elif kind is Kind.FRAME_RELEASE_TEMPORARY and link is not None and link.role == "fstring-consumed-reference":
            _need(stack and stack[-1][1] == operation.uses[0].value,
                  "string normal continuation releases a different ordered hold instance")
            stack = stack[:-1]
        if identity in own:
            consumed = _consumed(operation, kind, values)
            _need(len(stack) >= len(consumed) and tuple(row[1] for row in stack[-len(consumed):]) == consumed,
                  "string primitive does not own its ordered input hold suffix")
            remaining = stack[:-len(consumed)]
            actual = failure_holds[identity]
            expected = tuple(row[1] for row in remaining)
            _need(len(actual) >= len(expected) and (not expected or actual[-len(expected):] == expected),
                  "string failure lost or reordered its retained pieces")
            current_prefix = actual[:-len(expected)] if expected else actual
            _need(prefix is None or current_prefix == prefix,
                  "string failure changed its enclosing pending prefix")
            prefix = current_prefix
            completed.add(identity)
        if completed == own and not stack:
            return {"ordered_local_pending_checked": True, "enclosing_prefix_consistency_checked": True,
                    "intermediate_consumption_verified": not frontiers, "frontiers": frontiers,
                    "outer_pending_verified": False, "whole_lifetime_verified": False}
        term = operation.terminator
        if term is None:
            position = (block.id, index + 1)
        elif term.kind is TerminatorKind.INVOKE:
            if identity not in own:
                frontiers.append({"kind": "FSTRING_CHILD_PRIMITIVE_CONSUMPTION_UNVERIFIED", "operation": identity.wire})
            position = (term.successors[0].block, 0)
        elif term.kind is TerminatorKind.JUMP:
            position = (term.successors[0].block, 0)
        else:
            return {"ordered_local_pending_checked": False, "enclosing_prefix_consistency_checked": False,
                    "intermediate_consumption_verified": False,
                    "frontiers": frontiers + [{"kind": "FSTRING_CHILD_CONTROL_FLOW_UNVERIFIED", "operation": identity.wire}],
                    "outer_pending_verified": False, "whole_lifetime_verified": False}
    raise ValueError("string source validation: string construction repeats without completing its held suffix")


def validate_string_source(model, graph, interface, metadata, semantic, *,
                           source_tree=None, options=None, structural_only=False):
    _need(type(structural_only) is bool, "verification mode must be explicit")
    protocols = {row.operation: row for row in model.protocols}
    selected = {identity for identity, row in protocols.items() if row.kind in _KINDS}
    if not selected:
        return {"policy": POLICY, "protocol_operations": 0, "records": [], "whole_lifetime_verified": False}
    from scar.analysis.source_string_lowering import validate_string_protocols
    validate_string_protocols(model, graph, interface, metadata, semantic)
    operations = {row.id: row for row in graph.operations}
    values = {row.id: row for row in graph.values}
    blocks = {block.id: block for region in graph.regions for block in region.blocks}
    positions = {identity: (block.id, index) for block in blocks.values() for index, identity in enumerate(block.operations)}
    uses = {(row.operation, row.use): row for row in metadata.use_links}
    value_sources = {(row.value, row.source.atom_id) for row in metadata.value_links}
    by_source, failure_holds = {}, {}
    for identity in selected:
        row = protocols[identity]
        atom = semantic.source_atoms.get(row.source.atom_id)
        expected = "JoinedStr" if row.kind is Kind.BUILD_STRING else "FormattedValue"
        definitions = [d for d in semantic.definitions.values() if d.kind is OperationKind.OPERATOR
            and d.metadata.get("ast_type") == expected and d.code_id == row.source.atom_id.wire
            and row.source.atom_id in d.source_atoms and len(d.output_slots) == 1]
        _need(atom is not None and atom.reference == row.source and atom.kind == expected and len(definitions) == 1,
              "string protocol has no unique original SG operator/output")
        key = row.kind, row.source.atom_id
        _need(key not in by_source, "duplicate string stage at one original source atom")
        by_source[key] = identity
        failure_holds[identity] = _check_consumed_releases(operations[identity],
            _consumed(operations[identity], row.kind, values), operations, protocols, blocks, uses)
    if structural_only:
        return {"policy": POLICY, "protocol_operations": len(selected), "records": [],
                "source_shape_verified": False, "compiler_verified": False,
                "both_completion_releases_checked": True, "outer_pending_verified": False,
                "whole_lifetime_verified": False, "frontiers": ["FSTRING_SOURCE_AND_COMPILER_NOT_REVIEWED"]}
    _need(isinstance(source_tree, ast.Module) and type(options) is SourceLanguageOptions,
          "string source checking requires original AST and independent options")
    evidence = options.code_evidence
    instructions = ()
    if evidence is not None:
        evidence.require_definition(metadata.source, interface.definition, model.source)
        _need(evidence.store.document["runtime"]["version"][:3] == [3, 14, 7],
              "string contract requires pinned CPython 3.14.7")
        instructions = tuple(dis.get_instructions(evidence.code))
    parents = {child: parent for parent in ast.walk(source_tree) for child in ast.iter_child_nodes(parent)}

    def node_for(source, cls):
        matches = [n for n in require_source_tree(source_tree, metadata.source, source) if isinstance(n, cls)]
        _need(len(matches) == 1, "string stage does not identify one exact original AST node")
        return matches[0]

    def reference(node):
        matches = [row for row in semantic.source_atoms.values() if row.kind == type(node).__name__
                   and row.reference.path == metadata.source.path and row.reference.fingerprint == metadata.source.fingerprint
                   and (row.reference.start_line, row.reference.end_line, row.reference.start_column,
                        row.reference.end_column) == _span(node)]
        _need(len(matches) == 1, "string child has no unique original source atom")
        source = matches[0].reference
        definitions = [d for d in semantic.definitions.values() if d.code_id == source.atom_id.wire
            and source.atom_id in d.source_atoms and len(d.output_slots) == 1 and d.metadata.get("role") != "binding"]
        _need(len(definitions) == 1, "string child has no unique original SG output")
        return source

    def result(identity):
        return blocks[operations[identity].terminator.successors[0].block].arguments[0]

    def literal(value, expected):
        origin = values[value].origin
        return type(origin) is LiteralOrigin and type(origin.value) is type(expected) and origin.value == expected

    def value_matches(value, node):
        _need((value, reference(node).atom_id) in value_sources, "string child reference lost its exact source correspondence")
        if isinstance(node, ast.Constant):
            _need(literal(value, node.value), "string literal differs from its exact AST value")

    roots = set()
    for identity in selected:
        source, kind = protocols[identity].source, protocols[identity].kind
        node = node_for(source, ast.JoinedStr if kind is Kind.BUILD_STRING else ast.FormattedValue)
        if isinstance(node, ast.FormattedValue):
            node = parents.get(node)
        _need(isinstance(node, ast.JoinedStr), "formatted value has no original JoinedStr owner")
        while isinstance(parents.get(node), ast.FormattedValue) and parents[node].format_spec is node:
            node = parents.get(parents[node])
        roots.add(node)
    covered, records = set(), []
    for root in sorted(roots, key=_span):
        stages = []
        def stage(node, kind):
            identity = by_source.get((kind, reference(node).atom_id))
            _need(identity is not None, "original string AST is missing a required protocol stage")
            stages.append(identity)
            return identity

        def formatted(node, expected=None):
            identity = by_source.get((Kind.FSTRING_FORMAT, reference(node).atom_id))
            _need(identity is not None, "formatted value has no format stage")
            refs = _references(operations[identity])
            if node.conversion == -1:
                value_matches(refs[0], node.value)
                _need((Kind.FSTRING_CONVERT, reference(node).atom_id) not in by_source,
                      "string inserted a conversion absent from its AST")
            else:
                conversion = stage(node, Kind.FSTRING_CONVERT)
                inputs = _references(operations[conversion])
                value_matches(inputs[0], node.value)
                _need(literal(inputs[1], node.conversion) and refs[0] == result(conversion),
                      "string conversion selector/result differs from its AST")
            if node.format_spec is None:
                _need(literal(refs[1], None), "simple format was replaced with an explicit spec")
            else:
                _need(isinstance(node.format_spec, ast.JoinedStr), "format spec lost its original JoinedStr")
                joined(node.format_spec, refs[1])
            stage(node, Kind.FSTRING_FORMAT)
            if expected is not None:
                _need(result(identity) == expected, "join/spec uses a different formatted result")
            return result(identity)

        def joined(node, expected=None):
            _need(len(node.values) <= 30, "large string requires a separate compiler list/join contract")
            if len(node.values) > 1:
                identity = by_source.get((Kind.BUILD_STRING, reference(node).atom_id))
                _need(identity is not None, "JoinedStr has no ordered join")
                refs = _references(operations[identity])
                _need(len(refs) == len(node.values), "join piece count differs from exact AST")
            else:
                identity, refs = None, (expected,)
                _need((Kind.BUILD_STRING, reference(node).atom_id) not in by_source,
                      "zero/one-piece JoinedStr must not add BUILD_STRING")
            value = expected
            for index, child in enumerate(node.values):
                ref = refs[index]
                if isinstance(child, ast.FormattedValue):
                    value = formatted(child, ref)
                else:
                    _need(isinstance(child, ast.Constant) and type(child.value) is str,
                          "string piece is neither an exact literal nor FormattedValue")
                    if ref is None:
                        choices = [v for v, atom in value_sources if atom == reference(child).atom_id and literal(v, child.value)]
                        _need(len(choices) == 1, "string literal has no unique original reference")
                        ref = choices[0]
                    value_matches(ref, child)
                    value = ref
                    if evidence is not None:
                        matches = [i for i in instructions if i.opname == "LOAD_CONST" and tuple(i.positions) == _span(child)
                                   and type(i.argval) is str and i.argval == child.value]
                        _need(len(matches) == 1, "string literal lacks its exact compiler constant slot/position")
            if identity is not None:
                stage(node, Kind.BUILD_STRING)
                value = result(identity)
            if not node.values:
                _need(expected is not None and literal(expected, ""), "empty spec is not the exact empty-string reference")
            _need(expected is None or value == expected, "string result differs from its exact consumer")
            return value

        value = joined(root)
        _need(stages and not covered.intersection(stages), "string stages have duplicate owners")
        covered.update(stages)
        for current, following in zip(stages, stages[1:]):
            _ordered_next(current, following, set(stages), operations, blocks, positions)
        offsets = []
        if evidence is not None:
            for identity in stages:
                protocol = protocols[identity]
                node = node_for(protocol.source, ast.JoinedStr if protocol.kind is Kind.BUILD_STRING else ast.FormattedValue)
                name = ("BUILD_STRING" if protocol.kind is Kind.BUILD_STRING else "CONVERT_VALUE"
                        if protocol.kind is Kind.FSTRING_CONVERT else "FORMAT_SIMPLE" if node.format_spec is None else "FORMAT_WITH_SPEC")
                matches = [i for i in instructions if i.opname == name and tuple(i.positions) == _span(node)]
                _need(len(matches) == 1, "string stage has no unique exact compiler instruction/position")
                instruction = matches[0]
                if name == "BUILD_STRING":
                    _need(instruction.arg == len(node.values), "compiler join arity differs")
                elif name == "CONVERT_VALUE":
                    _need(instruction.arg == {115: 1, 114: 2, 97: 3}.get(node.conversion), "compiler conversion differs")
                offsets.append(instruction.offset)
            _need(offsets == sorted(set(offsets)), "compiler string stage ordering differs")
        # Select the exact AST roles held by string construction. An
        # interpolation value can be any supported expression, including a
        # Call/Attribute/Subscript; its hold is sourced at that expression,
        # not at the Names nested inside it. Hold instances still retain
        # their individual operation IDs and ordered references below.
        held_nodes = set()
        for node in ast.walk(root):
            if isinstance(node, ast.JoinedStr) and len(node.values) > 1:
                held_nodes.update(node.values)
            elif isinstance(node, ast.FormattedValue):
                held_nodes.add(node.value)
                if node.conversion != -1:
                    held_nodes.add(node)
                if node.format_spec is not None:
                    held_nodes.add(node.format_spec)
        sources = {reference(node).atom_id for node in held_nodes}
        pending = _pending_group(stages, sources, operations, protocols, blocks, positions, uses, values, failure_holds)
        parent = parents.get(root)
        if isinstance(parent, ast.Subscript) and isinstance(parent.ctx, ast.Store) and parent.slice is root:
            consumers = [row for row in metadata.use_links if row.role == "element-key" and row.source == reference(root)
                         and operations[row.operation].uses[[u.id for u in operations[row.operation].uses].index(row.use)].value == value]
            _need(len(consumers) == 1 and protocols.get(consumers[0].operation) is not None
                  and protocols[consumers[0].operation].kind is Kind.STORE_SUBSCRIPT,
                  "target string result does not reach its unique original subscript store")
            _ordered_next(stages[-1], consumers[0].operation, set(stages) | {consumers[0].operation}, operations, blocks, positions)
        records.append({"source": reference(root).atom_id.wire, "protocol_operations": len(stages),
            "source_shape_verified": True, "compiler_verified": evidence is not None,
            "both_completion_releases_checked": True, "pending": pending,
            "frontiers": ([] if evidence is not None else ["FSTRING_CODE_WITNESS_REQUIRED"])
                + ["FSTRING_OUTER_PENDING_PREFIX_UNVERIFIED", "FSTRING_RUNTIME_AND_EFFECTS_UNVERIFIED"],
            "effects_established": False, "runtime_code_instance_established": False, "whole_lifetime_verified": False})
    _need(covered == selected, "string protocol is not owned by its exact AST construction")
    return {"policy": POLICY, "protocol_operations": len(selected), "records": records,
            "effects_established": False, "runtime_code_instance_established": False,
            "outer_pending_verified": False, "whole_lifetime_verified": False}


__all__ = ["validate_string_source"]
