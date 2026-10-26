"""Source-profile checks over canonical environment/Use/state records.

Core validation owns CFG/SSA and port typing.  This check adds only the source
profile's namespace/cell ownership, ordered operands and protocol refinements.
Exact compiler layout/order remains an independent fixed-source replay check.
"""
from __future__ import annotations

from scar.ir.program.environments import EnvironmentRole
from scar.ir.program.functions import BodyLoweringProfile
from scar.ir.program.model import (
    Behavior, BlockArgument, CompletionResult, ExitKind, LiteralOrigin,
    LocalBindingValue, ReferenceValue, StateVersionValue, TerminatorKind, ValueKind, ValueType,
)
from scar.ir.program.state_addresses import (
    AddressCoverage, AddressEffect, CellContent, Element, InvokeStateOperand, NamespaceKey, ReferenceOwner,
)
from scar.ir.program.state_modes import AccessMode
from scar.ir.program.structured import PythonProtocolKind as Kind
from scar.ir.semantics_v2 import Opcode
from scar.ir.v2.semantic import OperationKind, SemanticRelation


_KINDS = frozenset((Kind.LOOKUP_GLOBAL, Kind.READ_FREE_CELL, Kind.READ_LOCAL_CELL,
                    Kind.MAKE_CELL, Kind.STORE_CELL, Kind.STORE_GLOBAL,
                    Kind.STORE_ATTRIBUTE, Kind.STORE_SUBSCRIPT))
_STORES = frozenset((Kind.STORE_CELL, Kind.STORE_GLOBAL, Kind.STORE_ATTRIBUTE, Kind.STORE_SUBSCRIPT))


def validate_environment_body(model, graph, interface, metadata, semantic, *, language=None):
    from scar.analysis.environment_lowering import captured_cell_slot
    from scar.analysis.source_language import function_exception_types

    def need(condition, detail):
        if not condition:
            raise ValueError("source environment: " + detail)

    need(interface.profile is BodyLoweringProfile.STRUCTURED_ENV, "wrong source profile")
    need(len(graph.environments) == len(graph.function_entries) == len(graph.locations) == 1,
         "requires one canonical environment, entry layout and coarse world")
    environment, layout = graph.environments[0], graph.function_entries[0]
    need((environment.region, environment.code_definition) == (interface.region, interface.definition)
         and layout.environment == environment.id and layout.parameters == interface.parameters,
         "environment/body ownership or formal partition differs")
    values = {value.id: value for value in graph.values}
    operations = {operation.id: operation for operation in graph.operations}
    blocks = {block.id: block for region in graph.regions for block in region.blocks}
    region = next(region for region in graph.regions if region.id == interface.region)
    entry = blocks[region.entry]
    world = values[interface.world]
    need(type(world) is StateVersionValue and world.location == graph.locations[0].id,
         "entry world is not the existing coarse state")
    need(entry.arguments == tuple(member.reference for member in environment.members)
         + tuple(port.value for port in interface.parameters) + (interface.world,),
         "entry must contain ordered environment, formals and world exactly")
    for position, identity in enumerate(entry.arguments):
        need(values[identity].origin == BlockArgument(entry.id, position), "entry origin/order differs")
    for member in environment.members:
        need(type(values[member.reference]) is ReferenceValue and member.locations == (world.location,),
             "environment references must depend on the existing coarse world")
        if member.role is EnvironmentRole.CAPTURED_CELL:
            need(member.cell_slot not in semantic.slots, "captured port reuses an outer/local source slot")
    for port in interface.parameters:
        slot = semantic.slots.get(port.slot)
        need(slot is not None and slot.owner == interface.definition and slot.direction == "input",
             "formal source slot belongs to another definition")
    links = {link.operation: link for link in metadata.operation_links}
    protocols = {protocol.operation: protocol for protocol in model.protocols}
    need(len(protocols) == len(model.protocols), "duplicate protocol for an operation")
    rows = {row.site.operation: row for row in graph.state_address_refinements}
    need(len(rows) == len(graph.state_address_refinements), "duplicate state refinement")
    free_owners = {member.reference: member for member in environment.members[5:]}
    namespaces = {member.role: member.reference for member in environment.members[:5]}
    own_cells, own_names, expected_rows = {}, {}, set()
    source_bindings = {}
    for edge in semantic.edges.values():
        if edge.relation in (SemanticRelation.READS_SLOT, SemanticRelation.WRITES_SLOT):
            source_bindings.setdefault((edge.source.id, edge.relation), []).append(semantic.slots[edge.target.id])
    for protocol in model.protocols:
        if protocol.kind is not Kind.MAKE_CELL:
            continue
        operation = operations[protocol.operation]
        normal = next(edge for edge in operation.terminator.successors if edge.kind is ExitKind.NORMAL)
        own_cells[blocks[normal.block].arguments[0]] = operation
    for protocol in model.protocols:
        operation, kind = operations[protocol.operation], protocol.kind
        link = links[operation.id]
        if kind is Kind.CALL_FUNCTION_EX:
            from scar.analysis.source_call_validation import is_original_call_definition
            from scar.ir.program.source_language import SourceLanguageCapability
            source = semantic.definitions.get(link.semantic_operation)
            atom = semantic.source_atoms.get(link.source.atom_id)
            need(language is not None and SourceLanguageCapability.CALL_KWARGS_314_V1 in language.capabilities
                 and source is not None and is_original_call_definition(semantic, source, link.source)
                 and source.code_id == link.source.atom_id.wire and link.source.atom_id in source.source_atoms
                 and atom is not None and atom.kind == "Call" and atom.reference == link.source
                 and link.opcode is Opcode.CALL, "kwargs call lost its capability or exact original SG Call")
            continue  # Exact call ports/pending/world are checked by the language validator.
        if kind is Kind.MAKE_NESTED_FUNCTION:
            from scar.ir.program.source_language import SourceLanguageCapability
            declaration = semantic.definitions.get(link.semantic_operation)
            atom = semantic.source_atoms.get(link.source.atom_id)
            need(language is not None and SourceLanguageCapability.NESTED_FUNCTION_314_V1 in language.capabilities
                 and declaration is not None and declaration.kind is OperationKind.OPERATOR
                 and declaration.metadata.get('phase') == 'definition_time' and len(declaration.output_slots) == 1
                 and declaration.code_id == link.source.atom_id.wire and link.source.atom_id in declaration.source_atoms
                 and atom is not None and atom.kind == 'FunctionDef' and atom.reference == link.source
                 and link.opcode is None, 'function creation lost its capability or original definition-time declaration')
            continue  # Exact code/default/cell/name/world checks remain in the ordinary language validator.
        if kind is Kind.BUILD_SET_DISPLAY:
            from scar.ir.program.source_language import SourceLanguageCapability
            declaration = semantic.definitions.get(link.semantic_operation)
            atom = semantic.source_atoms.get(link.source.atom_id)
            need(language is not None and SourceLanguageCapability.SET_DISPLAY_314_V1 in language.capabilities
                 and declaration is not None and declaration.kind is OperationKind.OPERATOR
                 and declaration.metadata.get('ast_type') == 'Set' and len(declaration.output_slots) == 1
                 and declaration.code_id == link.source.atom_id.wire and link.source.atom_id in declaration.source_atoms
                 and atom is not None and atom.kind == 'Set' and atom.reference == link.source
                 and link.opcode is Opcode.BUILD_SET, 'set display lost its capability or original SG source')
            continue  # Ordered elements, incomplete world and both completions remain independently checked below.
        if kind not in _KINDS:
            need(link.semantic_operation is None, "a source-linked operation has an invented protocol")
            continue
        inputs = operation.uses[:-1]
        need(operation.terminator is not None and operation.terminator.kind is TerminatorKind.INVOKE
             and not operation.effects_complete and operation.callee is None
             and tuple(use.id for use in operation.uses) == operation.invoke_arguments
             and all(type(values[use.value]) is ReferenceValue for use in inputs),
             "environment protocol requires its ordinary reference inputs and incomplete invoke")
        need(type(values[operation.uses[-1].value]) is StateVersionValue
             and values[operation.uses[-1].value].location == world.location,
             "environment protocol does not consume the coarse world")
        reference_type = ValueType(ValueKind.REFERENCE)
        state_type = ValueType(ValueKind.STATE, location=world.location)
        payload = () if kind in _STORES else (reference_type,)
        need(tuple((signature.kind, signature.types) for signature in operation.completions)
             == ((ExitKind.NORMAL, payload + (state_type,)),
                 (ExitKind.RAISE, function_exception_types(language, reference_type, state_type))), "normal/raise payload or state differs")
        need(tuple(edge.kind for edge in operation.terminator.successors) == (ExitKind.NORMAL, ExitKind.RAISE)
             and all(edge.arguments == tuple(CompletionResult(index) for index in range(len(signature.types)))
                     for edge, signature in zip(operation.terminator.successors, operation.completions)),
             "completion edges do not carry their own payload and post-world")
        if kind is Kind.MAKE_CELL:
            need(link.semantic_operation is None and len(inputs) <= 1
                 and all(use.value in {port.value for port in interface.parameters} for use in inputs)
                 and Behavior.MEMORY in operation.behaviors, "own-cell creation has an invalid initializer")
            continue
        if kind in (Kind.STORE_ATTRIBUTE, Kind.STORE_SUBSCRIPT):
            from scar.analysis.source_heap_validation import validate_heap_store
            validate_heap_store(operation, kind, link, rows.get(operation.id), semantic)
            expected_rows.add(operation.id)
            continue
        source = semantic.definitions.get(link.semantic_operation)
        atom = semantic.source_atoms[link.source.atom_id]
        unpacked_source=False
        if kind in (Kind.STORE_CELL,Kind.STORE_GLOBAL) and language is not None and link.opcode is Opcode.OPAQUE:
            from scar.ir.program.source_language import SourceLanguageCapability
            if SourceLanguageCapability.UNPACK_TARGETS_314_V1 in language.capabilities:
                # The old overlay had no tuple-element value, hence OPAQUE.
                # Preserve that original record. Only the exact new NORMAL
                # result -> original Name store is owned by the unpack rule.
                for shape in language.unpackings:
                    original=operations[shape.operation]
                    normal=[e for e in original.terminator.successors if e.kind is ExitKind.NORMAL]
                    if len(normal)!=1:continue
                    arguments=blocks[normal[0].block].arguments
                    for index,target in enumerate(shape.child_targets):
                        if target==link.source and index<len(arguments)-1 and operation.uses[-2].value==arguments[index]:
                            unpacked_source=True
        need(source is not None and source.code_id == link.source.atom_id.wire and atom.kind == "Name"
             and (link.opcode is (Opcode.ALIAS if kind in _STORES else Opcode.READ) or unpacked_source),
             "cell/namespace protocol must correspond to its exact Name read/write: "+kind.value+" / "+str(link.opcode)+" / "+str(link.source.start_line))
        relation = SemanticRelation.WRITES_SLOT if kind in _STORES else SemanticRelation.READS_SLOT
        slots = source_bindings.get((source.id, relation), ())
        need(len(slots) == 1, "Name has no unique source binding slot")
        slot, effects = slots[0], ()
        if kind in (Kind.READ_FREE_CELL, Kind.READ_LOCAL_CELL, Kind.STORE_CELL):
            need(len(inputs) == (2 if kind is Kind.STORE_CELL else 1), "cell operand arity differs")
            owner = inputs[0].value
            if owner in free_owners:
                need(kind is not Kind.READ_LOCAL_CELL
                     and free_owners[owner].cell_slot == captured_cell_slot(interface.definition, slot.name)
                     and slot.owner != interface.definition, "captured cell has the wrong source owner/name")
            else:
                need(kind is not Kind.READ_FREE_CELL and owner in own_cells
                     and slot.owner == interface.definition, "local cell has no invocation-owned creation")
                need(owner not in own_names or own_names[owner] == slot.slot_id,
                     "one local cell is used for different compiler bindings")
                own_names[owner] = slot.slot_id
            effects = (AddressEffect(ReferenceOwner(inputs[0].id), (CellContent(),),
                                    AccessMode.WRITE if kind in _STORES else AccessMode.READ),)
        else:
            expected = ((namespaces[EnvironmentRole.GLOBALS_NAMESPACE],
                         namespaces[EnvironmentRole.BUILTINS_NAMESPACE])
                        if kind is Kind.LOOKUP_GLOBAL else (namespaces[EnvironmentRole.GLOBALS_NAMESPACE],))
            key_index = len(expected)
            need(len(inputs) == 3 and tuple(use.value for use in inputs[:key_index]) == expected,
                 "globals and saved-builtins lookup order differs")
            origin = values[inputs[key_index].value].origin
            need(type(origin) is LiteralOrigin and type(origin.value) is str and origin.value == slot.name,
                 "namespace key is not the exact source Name")
            owner = semantic.definitions.get(slot.owner)
            need(owner is not None and owner.kind is OperationKind.MODULE,
                 "namespace protocol incorrectly substitutes for a local/free binding")
            effects = tuple(AddressEffect(ReferenceOwner(inputs[index].id),
                (NamespaceKey(inputs[key_index].id),), AccessMode.WRITE if kind in _STORES else AccessMode.READ)
                for index in range(key_index))
        row = rows.get(operation.id)
        need(row is not None and row.site == InvokeStateOperand(operation.id, operation.uses[-1].id)
             and row.coverage is AddressCoverage.PARTIAL and row.protocol is None and row.effects == effects,
             "state address must name this operation's exact owner/key/world Uses")
        expected_rows.add(operation.id)
    if language is not None:
        from scar.ir.program.source_language import SourceLanguageCapability
        if SourceLanguageCapability.SLICE_KEYS in language.capabilities:
            for link in metadata.operation_links:
                if link.opcode is not Opcode.INDEX:
                    continue
                operation = operations[link.operation]
                source = semantic.definitions.get(link.semantic_operation)
                atom = semantic.source_atoms.get(link.source.atom_id)
                need(source is not None and source.kind is OperationKind.INDEX
                     and source.code_id == link.source.atom_id.wire
                     and link.source.atom_id in source.source_atoms
                     and atom is not None and atom.kind == "Subscript" and atom.reference == link.source,
                     "language index address has no exact original source INDEX")
                need(operation.terminator is not None and operation.terminator.kind is TerminatorKind.INVOKE
                     and not operation.effects_complete and operation.callee is None
                     and len(operation.uses) == 3
                     and tuple(use.id for use in operation.uses) == operation.invoke_arguments
                     and all(type(values[use.value]) is ReferenceValue for use in operation.uses[:2])
                     and type(values[operation.uses[-1].value]) is StateVersionValue
                     and values[operation.uses[-1].value].location == world.location,
                     "language index address needs original receiver/key/world invoke Uses")
                effect = AddressEffect(ReferenceOwner(operation.uses[0].id),
                                       (Element(operation.uses[1].id),), AccessMode.READ)
                row = rows.get(operation.id)
                need(row is not None and row.site == InvokeStateOperand(operation.id, operation.uses[-1].id)
                     and row.coverage is AddressCoverage.PARTIAL and row.protocol is None
                     and row.effects == (effect,), "language index address differs from its exact receiver/key/world Uses")
                expected_rows.add(operation.id)
    if language is not None:
        from scar.ir.program.source_language import SourceLanguageCapability
        if SourceLanguageCapability.NESTED_FUNCTION_314_V1 in language.capabilities:
            # Its original FunctionDef source/name/cell/address correspondence
            # is checked by the dedicated ordinary language validator below.
            expected_rows.update(p.operation for p in model.protocols if p.kind is Kind.STORE_NESTED_FUNCTION_CELL)
        if SourceLanguageCapability.FUNCTION_IMPORT_314_V1 in language.capabilities:
            # Exact import source/builtins/key/world correspondence is checked
            # by the ordinary opt-in language validator, not the Name rule.
            expected_rows.update(p.operation for p in model.protocols if p.kind is Kind.FUNCTION_IMPORT_NAME)
    need(set(rows) == expected_rows, "unexpected or missing source environment address refinement")
    for value in values.values():
        if type(value) is LocalBindingValue:
            need(value.slot not in set(own_names.values()), "cell content was replaced with a local binding token")


__all__ = ["validate_environment_body"]
