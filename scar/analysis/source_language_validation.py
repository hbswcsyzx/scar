"""Validate new source protocols against original ports and exact source.

Structural reading is distinct from source/CodeWitness verification. Neither
mode establishes runtime code-instance identity or operation purity.
"""
from __future__ import annotations

from scar.analysis.source_language import function_exception_types

import ast
import dis

from scar.analysis.program_lowering import _REF
from scar.analysis.source_language import SourceLanguageOptions, require_source_tree
from scar.ir.program.model import (
    AccessMode, BlockArgument, CompletionResult, ExitKind, ReferenceValue,
    StateVersionValue, LocalBindingValue, TerminatorKind, value_type,
)
from scar.ir.program.source_language import (
    SourceLanguageOverlay, SourceLanguageCapability as Capability, EXTENDED_PROTOCOLS,
)
from scar.ir.record_codec import encode


def _need(condition, detail):
    if not condition:
        raise ValueError("source language validation: " + detail)


def validate_language_body(model, graph, interface, metadata, semantic, language,
                           *, source_tree=None, options=None, structural_only=False):
    if (language is not None and Capability.GENEXPR_314_V1 in language.capabilities
            and graph.resumable_creates):
        from scar.analysis.source_generator_validation import validate_generator_regions, root_projection
        delegated = validate_generator_regions(model, graph, interface, metadata, semantic, language,
            source_tree=source_tree, options=options, structural_only=structural_only)
        model, graph, metadata, language = root_projection(model, graph, metadata, language, delegated)
    _need(type(language) is SourceLanguageOverlay and language.source == metadata.source,
          "overlay source differs from original body metadata")
    _need(type(structural_only) is bool, "verification mode must be explicit")
    if not structural_only:
        _need(isinstance(source_tree, ast.Module) and type(options) is SourceLanguageOptions,
              "exact source/CodeWitness verification requires explicit source AST and independent options")
        _need(options.capabilities == language.capabilities, "requested and reported language capabilities differ")
        expected_evidence = options.code_evidence.to_dict() if options.code_evidence is not None else None
        _need(language.code_evidence == expected_evidence, "code provenance differs from the independent archive inputs")
        if options.code_evidence is not None:
            options.code_evidence.require_definition(metadata.source, interface.definition, model.source)
    operations = {row.id: row for row in graph.operations}
    values = {row.id: row for row in graph.values}
    blocks = {block.id: block for region in graph.regions for block in region.blocks}
    protocols = {row.operation: row for row in model.protocols}
    links = {row.operation: row for row in metadata.operation_links}
    world_type = value_type(values[interface.world])
    unpack = {row.operation: row for row in language.unpackings}
    slices = {row.operation: row for row in language.slices}
    constants = {row.operation: row for row in language.constants}
    _need(len(unpack) == len(language.unpackings) and len(slices) == len(language.slices)
          and len(constants) == len(language.constants), "duplicate language shape/provenance record")
    from scar.analysis.source_call_validation import CALL_PROTOCOLS, validate_call_protocols
    calls = {identity for identity, protocol in protocols.items() if protocol.kind in CALL_PROTOCOLS}
    from scar.analysis.source_function_try_validation import validate_function_try_protocols
    try_protocols = validate_function_try_protocols(model, graph, interface, metadata, semantic, language, source_tree=source_tree)
    indexed = set(unpack) | set(slices) | set(constants) | calls | try_protocols
    actual = {key for key, row in protocols.items() if row.kind.value in EXTENDED_PROTOCOLS}
    _need(indexed == actual and len(indexed) == len(unpack) + len(slices) + len(constants) + len(calls) + len(try_protocols),
          "new language operations must have one exact shape/provenance record")

    def source_node(reference, classes):
        atom = semantic.source_atoms.get(reference.atom_id)
        _need(atom is not None and atom.reference == reference, "protocol source is not the original source atom")
        _need(atom.kind in tuple(kind.__name__ for kind in classes), "protocol source AST kind differs")
        if structural_only:
            return None
        candidates = [node for node in require_source_tree(source_tree, language.source, reference)
                      if isinstance(node, classes)]
        _need(len(candidates) == 1, "protocol needs one exact source AST node")
        return candidates[0]

    def invoke(identity, count, result_count):
        operation = operations[identity]
        _need(operation.terminator is not None and operation.terminator.kind is TerminatorKind.INVOKE
              and not operation.effects_complete and len(operation.invoke_arguments) == count + 1,
              "protocol must retain incomplete invoke operands/completions")
        uses = {row.id: row for row in operation.uses}
        operands = tuple(uses[key] for key in operation.invoke_arguments)
        _need(all(type(values[row.value]) is ReferenceValue for row in operands[:-1])
              and type(values[operands[-1].value]) is StateVersionValue,
              "protocol references/world are not their original typed Uses")
        _need(tuple(row.kind for row in operation.completions) == (ExitKind.NORMAL, ExitKind.RAISE),
              "protocol must keep ordered normal and exceptional completions")
        normal, failure = operation.completions
        _need(normal.types == (_REF,) * result_count + (world_type,)
              and failure.types == function_exception_types(language, _REF, world_type), "protocol payload/world types differ")
        _need(tuple(row.kind for row in operation.terminator.successors) == (ExitKind.NORMAL, ExitKind.RAISE)
              and all(edge.arguments == tuple(CompletionResult(i) for i in range(len(signature.types)))
                      for edge, signature in zip(operation.terminator.successors, operation.completions)),
              "normal/raise ports are not this invoke's ordered CompletionResults")
        edge = operation.terminator.successors[0]
        return operation, operands, blocks[edge.block]

    for identity in indexed:
        _need(identity in operations and identity in links and links[identity].source == protocols[identity].source,
              "language operation lost its exact source/core correspondence")
    for identity, shape in unpack.items():
        _need(Capability.FIXED_UNPACK in language.capabilities and protocols[identity].kind.value == "UNPACK_FIXED"
              and shape.source == protocols[identity].source, "unpack shape/kind/capability differs")
        node = source_node(shape.source, (ast.Tuple, ast.List))
        if node is not None:
            _need(isinstance(node.ctx, ast.Store) and not any(isinstance(row, ast.Starred) for row in ast.walk(node)),
                  "fixed unpack cannot accept starred/load syntax")
            _need(tuple((row.lineno, row.end_lineno, row.col_offset, row.end_col_offset) for row in node.elts)
                  == tuple((row.start_line, row.end_line, row.start_column, row.end_column) for row in shape.child_targets),
                  "unpack target sequence differs from exact source")
        operation, operands, normal = invoke(identity, 1, len(shape.child_targets))
        _need(operands[0].value != operands[-1].value, "unpack input/world alias typed ports")
        source_uses = {(row.operation, row.use): row for row in metadata.use_links}
        source_use = source_uses.get((identity, operands[0].id))
        _need(source_use is not None and source_use.role == "unpack-source" and source_use.index == 0
              and source_use.source == shape.source, "unpack original RHS Use/source role differs")
        # Every normal result is published exactly once before the first leaf
        # store/inner unpack. The primitive owns its arity/error internals.
        published = []
        for key in normal.operations[:len(shape.child_targets)]:
            protocol = protocols.get(key)
            if protocol is None or protocol.kind.value != "FRAME_HOLD_TEMPORARY":
                break
            reference = next(row.value for row in operations[key].uses if type(values[row.value]) is ReferenceValue)
            published.append(reference)
        _need(tuple(published) == tuple(reversed(normal.arguments[:-1])),
              "unpack must publish all same-level results before ordered target stores")
        for reference in shape.child_targets:
            atom = semantic.source_atoms.get(reference.atom_id)
            _need(atom is not None and atom.reference == reference and atom.kind in ("Name", "Tuple", "List"),
                  "local unpack child has no permitted original target atom")
    # Verify normal-path target order and direct original assigned ports. A
    # nested unpack starts only when its outer siblings before it were stored.
    visiting = set()
    def stores(identity):
        _need(identity not in visiting, "unpack target shape is cyclic")
        visiting.add(identity)
        shape = unpack[identity]
        _, _, normal = invoke(identity, 1, len(shape.child_targets))
        block, position = normal, len(shape.child_targets)
        for index, reference in enumerate(shape.child_targets):
            _need(position < len(block.operations), "unpack target store is missing")
            key = block.operations[position]
            protocol = protocols.get(key)
            atom = semantic.source_atoms[reference.atom_id]
            if atom.kind in ("Tuple", "List"):
                _need(key in unpack and unpack[key].source == reference,
                      "nested unpack does not follow its original target position")
                nested_uses = {row.id: row for row in operations[key].uses}
                _need(nested_uses[operations[key].invoke_arguments[0]].value == normal.arguments[index],
                      "inner unpack did not consume the corresponding outer normal result")
                block, position = stores(key)
            else:
                _need(protocol is not None and protocol.kind.value == "FRAME_BIND"
                      and protocol.source == reference, "local target store order/source differs")
                assigned = [row.value for row in operations[key].uses if type(values[row.value]) is ReferenceValue]
                _need(assigned == [normal.arguments[index]], "local target did not receive its exact unpack result")
                _need(position + 1 < len(block.operations), "local target has no binding definition")
                definition = operations[block.operations[position + 1]]
                _need(len(definition.results) == 1 and type(values[definition.results[0]]) is LocalBindingValue
                      and len(definition.uses) == 1 and definition.uses[0].value == normal.arguments[index],
                      "local binding token did not retain its assigned original reference")
                slot = values[definition.results[0]].slot
                _need(semantic.slots[slot].owner == interface.definition,
                      "unpack introduced a binding in another lexical scope")
                position += 2
        visiting.remove(identity)
        return block, position
    for identity in unpack:
        stores(identity)
    for identity, shape in slices.items():
        _need(Capability.SLICE_KEYS in language.capabilities and protocols[identity].kind.value == "BUILD_SLICE"
              and shape.source == protocols[identity].source, "slice shape/kind/capability differs")
        node = source_node(shape.source, (ast.Slice,))
        if node is not None:
            for part, expected in ((node.lower, shape.lower), (node.upper, shape.upper), (node.step, shape.step)):
                _need((part is None) == (expected is None), "slice omission differs from source")
                if part is not None:
                    _need((part.lineno, part.end_lineno, part.col_offset, part.end_col_offset)
                          == (expected.start_line, expected.end_line, expected.start_column, expected.end_column),
                          "slice bound source differs")
        _, operands, _ = invoke(identity, 3 if shape.step is not None else 2, 1)
        source_uses = {(row.operation, row.use): row for row in metadata.use_links}
        components = (shape.lower, shape.upper, shape.step)[:len(operands) - 1]
        for index, (use, reference) in enumerate(zip(operands[:-1], components)):
            link = source_uses.get((identity, use.id))
            _need(link is not None and link.role == ('slice-lower', 'slice-upper', 'slice-step')[index]
                  and link.index == index and link.source == (reference or shape.source),
                  "slice bound ordered Use source/role differs")
            if reference is None:
                from scar.ir.program.model import LiteralOrigin
                _need(type(values[use.value].origin) is LiteralOrigin and values[use.value].origin.value is None,
                      "omitted slice bound is not exact None")
        if not structural_only:
            evidence = options.code_evidence
            _need(evidence is not None, "dynamic slice requires its independent compiler witness")
            candidates = [row for row in dis.get_instructions(evidence.code)
                if row.opname == "BUILD_SLICE" and row.arg == len(operands) - 1
                and tuple(row.positions) == (node.lineno, node.end_lineno, node.col_offset, node.end_col_offset)]
            _need(len(candidates) == 1, "dynamic slice does not match its exact BUILD_SLICE code position")
    if Capability.SLICE_KEYS in language.capabilities:
        from scar.ir.program.state_addresses import AddressCoverage, AddressEffect, Element, InvokeStateOperand, ReferenceOwner
        from scar.ir.semantics_v2 import Opcode
        from scar.ir.v2.semantic import OperationKind
        addresses = {row.site.operation: row for row in graph.state_address_refinements}
        source_uses = {(row.operation, row.use): row for row in metadata.use_links}
        for identity, link in links.items():
            if link.opcode is not Opcode.INDEX:
                continue
            definition = semantic.definitions.get(link.semantic_operation)
            _need(definition is not None and definition.kind is OperationKind.INDEX
                  and definition.code_id == link.source.atom_id.wire
                  and link.source.atom_id in definition.source_atoms,
                  "index operation lost its exact original source definition")
            node = source_node(link.source, (ast.Subscript,))
            _need(node is None or isinstance(node.ctx, ast.Load), "load-key capability cannot certify a store")
            operation, operands, _ = invoke(identity, 2, 1)
            _need(operation.callee is None and values[operands[-1].value].location == values[interface.world].location,
                  "index invoke does not consume its original coarse world")
            row = addresses.get(identity)
            expected = AddressEffect(ReferenceOwner(operands[0].id), (Element(operands[1].id),), AccessMode.READ)
            _need(row is not None and row.site == InvokeStateOperand(identity, operands[-1].id)
                  and row.coverage is AddressCoverage.PARTIAL and row.protocol is None and row.effects == (expected,),
                  "index partial address differs from its exact receiver/key/world Uses")
            for index, role in enumerate(("receiver", "index")):
                source_use = source_uses.get((identity, operands[index].id))
                _need(source_use is not None and source_use.role == role and source_use.index == index,
                      "index original receiver/key Use order differs")
                atom = semantic.source_atoms.get(source_use.source.atom_id)
                _need(atom is not None and atom.reference == source_use.source,
                      "index operand has no exact original source atom")
                if node is not None:
                    child = (node.value, node.slice)[index]
                    _need((source_use.source.path, source_use.source.fingerprint) == (language.source.path, language.source.fingerprint)
                          and (source_use.source.start_line, source_use.source.end_line,
                               source_use.source.start_column, source_use.source.end_column)
                          == (child.lineno, child.end_lineno, child.col_offset, child.end_col_offset),
                          "index receiver/key differs from exact source expression")
    for identity, constant in constants.items():
        atom = semantic.source_atoms.get(constant.source.atom_id)
        call_constant = atom is not None and atom.kind == "Call"
        capability = Capability.CALL_KWARGS_314_V1 if call_constant else Capability.SLICE_KEYS
        _need(capability in language.capabilities and protocols[identity].kind.value == "READ_CODE_CONSTANT"
              and constant.source == protocols[identity].source, "code constant kind/capability differs")
        node = source_node(constant.source, (ast.Call,) if call_constant else (ast.Slice, ast.Tuple))
        operation = operations[identity]
        _need(operation.terminator is None and not operation.effects_complete and len(operation.results) == 1
              and type(values[operation.results[0]]) is ReferenceValue
              and values[operation.results[0]].referent_identity is None
              and len(operation.accesses) == 1 and operation.accesses[0].mode is AccessMode.READ
              and len(operation.uses) == 1 and type(values[operation.uses[0].value]) is StateVersionValue,
              "code constant reference must be a nonallocating, identity-unproved table read")
        from scar.ir.program.model import Behavior
        _need(operation.behaviors == (Behavior.READ,), "constant table read cannot claim fresh allocation or mutation")
        if not structural_only:
            evidence = options.code_evidence
            _need(evidence is not None and evidence.captured.key == constant.code_key,
                  "constant provenance is not backed by the independently loaded CodeWitness")
            _need(len(constant.constant_path) == 1, "this capability only indexes direct code constants")
            candidates = [row for row in dis.get_instructions(evidence.code)
                if row.opname == "LOAD_CONST" and row.arg == constant.constant_path[0]
                and tuple(row.positions) == (node.lineno, node.end_lineno, node.col_offset, node.end_col_offset)]
            allowed = (str, tuple) if call_constant else (slice, tuple)
            _need(len(candidates) == 1 and type(candidates[0].argval) in allowed
                  and (not call_constant or type(candidates[0].argval) is str or candidates[0].argval == ()),
                  "source constant does not name its exact witnessed LOAD_CONST slot")
    call_protocols = validate_call_protocols(model, graph, interface, metadata, semantic, language,
        source_tree=source_tree, options=options, structural_only=structural_only)
    from scar.analysis.source_string_validation import validate_string_source
    string_protocols = validate_string_source(model, graph, interface, metadata, semantic,
        source_tree=source_tree, options=options, structural_only=structural_only)
    tuple_ownership = None
    if Capability.SLICE_KEYS in language.capabilities:
        from scar.analysis.source_tuple_validation import validate_tuple_key_ownership
        tuple_ownership = validate_tuple_key_ownership(model, graph, interface, metadata, semantic,
            source_tree=source_tree, options=options, structural_only=structural_only)
    _need(len({row.name for row in language.compiler_locals}) == len(language.compiler_locals),
          "compiler-local names are not uniquely classified")
    for mapping in language.compiler_locals:
        _need(Capability.LEXICAL_LOCALS in language.capabilities, "compiler local mapping lacks explicit capability")
        _need(bool(mapping.lexical_slots) and len(set(mapping.lexical_slots)) == len(mapping.lexical_slots),
              "compiler local has no unique original lexical slots")
        for slot in mapping.lexical_slots:
            _need(slot in semantic.slots and semantic.slots[slot].name == mapping.name,
                  "compiler-local mapping introduced a non-source slot")
        if mapping.category == "LEXICAL_FUNCTION":
            _need(all(semantic.slots[slot].owner == interface.definition for slot in mapping.lexical_slots),
                  "function local points to another lexical scope")
        else:
            _need(mapping.comp_iteration or mapping.comp_cell, "transient local has no compiler comprehension classification")
            _need(all(semantic.slots[slot].metadata.get("scope_kind") == "comprehension" for slot in mapping.lexical_slots),
                  "transient comprehension local was projected as an outer slot")
            for slot in mapping.lexical_slots:
                owner, seen = semantic.slots[slot].owner, set()
                while owner in semantic.definitions and owner not in seen and owner != interface.definition:
                    seen.add(owner)
                    definition = semantic.definitions[owner]
                    _need(getattr(definition.kind, 'value', definition.kind) not in ('function', 'method', 'class'),
                          "comprehension local crossed a different function/class scope")
                    owner = definition.parent_id
                _need(owner == interface.definition, "comprehension local belongs to another function")
    return {"valid": True, "verification": "STRUCTURE" if structural_only else "SOURCE_AND_CODE_WITNESS",
            "source_shape_verified": not structural_only,
            "code_constant_provenance_verified": bool(constants) and not structural_only,
            "runtime_code_instance_established": False, "effects_established": False,
            "tuple_key_pending_references": tuple_ownership, "kwargs_call_protocols": call_protocols,
            "string_protocols": string_protocols}


__all__ = ["validate_language_body"]
