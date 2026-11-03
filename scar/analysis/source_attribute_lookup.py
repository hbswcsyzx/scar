"""Source/compiler lookup declarations over existing canonical ports.

Registration never allocates program IDs or changes operations/effects. Source
validation independently rederives requests from original AST/SG/compiler
inputs, rather than treating a saved selector as proof of its own spelling.
"""
from __future__ import annotations

import ast
from collections import defaultdict
from dataclasses import replace
import dis
import hashlib

from scar.ir.program.attribute_lookups import (
    AttributeLookupCompletion, AttributeLookupForm as Form, AttributeLookupInterface,
)
from scar.ir.program.ids import UseID
from scar.ir.program.model import CompletionResult, ExitKind, ReferenceValue, StateVersionValue, TerminatorKind
from scar.ir.program.structured import ControlEdgeReference
from scar.ir.semantics_v2 import Opcode
from scar.ir.v2.semantic import OperationKind, SemanticRelation


def _need(ok, detail):
    if not ok:
        raise ValueError("attribute lookup source: " + detail)


def _span(value):
    if isinstance(value, ast.AST):
        return value.lineno, value.end_lineno, value.col_offset, value.end_col_offset
    return value.start_line, value.end_line, value.start_column, value.end_column


def _source_lookup(semantic, path, fingerprint):
    references = defaultdict(list)
    for atom in semantic.source_atoms.values():
        reference = atom.reference
        if reference.path == path and reference.fingerprint == fingerprint:
            references[(atom.kind, _span(reference))].append(reference)

    def original(node):
        rows = references.get((type(node).__name__, _span(node)), ())
        if not rows:
            return None
        _need(len(rows) == 1, "source occurrence has no unique original semantic atom")
        return rows[0]
    return original


def _interface(operation, values, blocks, source, receiver, selector, form):
    _need(operation.terminator is not None and operation.terminator.kind is TerminatorKind.INVOKE,
        "lookup must retain its original INVOKE")
    owned = {use.id: use for use in operation.uses}
    _need(type(receiver) is UseID and receiver in operation.invoke_arguments
        and type(values[owned[receiver].value]) is ReferenceValue,
        "lookup receiver is not its original reference Use")
    worlds = [use for use in operation.uses if use.id in operation.invoke_arguments
        and type(values[use.value]) is StateVersionValue]
    _need(len(worlds) == 1, "lookup has no unique original coarse-world Use")
    completed = {}
    for ordinal, edge in enumerate(operation.terminator.successors):
        _need(edge.kind in (ExitKind.NORMAL, ExitKind.RAISE) and edge.kind not in completed,
            "lookup needs one real NORMAL and one real RAISE")
        signature, = [row for row in operation.completions if row.kind is edge.kind]
        arguments = blocks[edge.block]
        _need(len(arguments) == len(edge.arguments), "lookup landing arity changed")
        slots = {}
        for formal, actual in zip(arguments, edge.arguments):
            _need(type(actual) is CompletionResult and actual.index not in slots,
                "lookup landing is not its original completion-result projection")
            slots[actual.index] = formal
        _need(set(slots) == set(range(len(signature.types))), "lookup completion slots changed")
        ordered = tuple(slots[index] for index in range(len(signature.types)))
        states = [value for value in ordered if type(values[value]) is StateVersionValue]
        _need(len(states) == 1 and ordered[-1] == states[0], "lookup completion has no original final post-world")
        completed[edge.kind] = AttributeLookupCompletion(
            ControlEdgeReference(operation.id, ordinal), ordered[:-1], states[0])
    _need(set(completed) == {ExitKind.NORMAL, ExitKind.RAISE}, "lookup outcomes are incomplete")
    return AttributeLookupInterface(operation.id, source, receiver, selector, worlds[0].id,
        form, completed[ExitKind.NORMAL], completed[ExitKind.RAISE])


def register_attribute_lookup(builder, node, operation, *, receiver=None,
        selector=None, form=Form.SOURCE_GETATTR, key_use=None, source=None):
    """Register one actual GET after invoke and original source association.

    The builder's ID counters, source metadata, state addresses, effects and
    NORMAL/RAISE operations are unchanged. An unresolved name is a selector
    field, not an extra metadata gap or a replacement operation.
    """
    _need(isinstance(node, ast.Attribute) and isinstance(node.ctx, (ast.Load, ast.Store)),
        "registration accepts an actual getter, including the read half of AugAssign")
    records = getattr(builder, "operation_records", None)
    op = records.get(operation) if records is not None else None
    if op is None:
        op, = [row for row in getattr(builder, "operations", getattr(builder, "ops", ())) if row.id == operation]
    values = getattr(builder, "values_by_id", getattr(builder, "records", None))
    blocks = getattr(builder, "block_arguments", getattr(builder, "args", None))
    prepared = getattr(builder, "prepared_source", getattr(builder, "prepared", None))
    tree = getattr(builder, "tree", None) or getattr(prepared, "tree", None)
    text = getattr(builder, "text", None) or getattr(prepared, "text", None)
    semantic = getattr(builder, "semantic", None) or prepared.semantic
    snapshot = getattr(builder, "snapshot", None)
    from scar.analysis.attribute_selector import prepare_attribute_selector_source
    cache_owner = getattr(builder, "owner", builder)
    cached = getattr(cache_owner, "_attribute_lookup_source_inputs", None)
    if (cached is None or cached[0] is not semantic or cached[1] is not tree
            or cached[2] != snapshot):
        original = _source_lookup(semantic, snapshot.path, snapshot.fingerprint)
        facts = prepare_attribute_selector_source(tree, text, snapshot.path)
        cached = semantic, tree, snapshot, original, facts
        cache_owner._attribute_lookup_source_inputs = cached
    original, facts = cached[3:]
    source = original(node) if source is None else source
    _need(source is not None and source == original(node), "registered lookup lost its original Attribute source")
    if selector is None:
        from scar.analysis.attribute_selector import derive_attribute_selector
        from scar.analysis.static_compilation import StaticCodeEvidence
        evidence = getattr(builder, "evidence", None)
        evidence = evidence if type(evidence) is StaticCodeEvidence else None
        selector = derive_attribute_selector(node, source_tree=tree, source=source,
            source_text=text, source_for_node=original, compiler_evidence=evidence, source_facts=facts)
    if key_use is not None:
        selector = replace(selector, key_use=key_use)
    receiver = op.uses[0].id if receiver is None else receiver
    interface = _interface(op, values, blocks, source, receiver, selector, form)
    table = builder.attribute_lookups
    saved = [row for row in table if row.operation == operation]
    _need(not saved or saved == [interface], "lookup operation was registered with conflicting source/ports")
    if not saved:
        table.append(interface)
    return interface


def derive_source_attribute_lookups(graph, metadata, *, source_text, semantic,
        source_metadata=None, compiler_overlay=None, compiler_evidence=None):
    """Independently derive all retained GET requests from original inputs."""
    from scar.analysis.attribute_selector import derive_attribute_selector, prepare_attribute_selector_source
    _need(type(source_text) is str and hashlib.sha256(source_text.encode()).hexdigest()
        == metadata.source.fingerprint.removeprefix("sha256:"), "retained source text changed")
    tree = ast.parse(source_text, filename=metadata.source.path, type_comments=True)
    facts = prepare_attribute_selector_source(tree, source_text, metadata.source.path)
    original = _source_lookup(semantic, metadata.source.path, metadata.source.fingerprint)
    nodes = defaultdict(list)
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and isinstance(node.ctx, (ast.Load, ast.Store)):
            nodes[_span(node)].append(node)
    sources = source_metadata or metadata
    links, uses = defaultdict(list), defaultdict(list)
    for row in sources.operation_links:
        links[row.operation].append(row)
    for row in sources.use_links:
        uses[row.operation].append(row)
    operations = {row.id: row for row in graph.operations}
    values = {row.id: row for row in graph.values}
    blocks = {block.id: block.arguments for region in graph.regions for block in region.blocks}
    expected = []
    definitions_by_atom = defaultdict(list)
    for definition in semantic.definitions.values():
        for atom in definition.source_atoms:
            definitions_by_atom[atom].append(definition)
    read_slots = defaultdict(set)
    for edge in semantic.edges.values():
        if edge.relation is SemanticRelation.READS_SLOT:
            read_slots[edge.source.id].add(edge.target.id)
    for identity, rows in links.items():
        selected = [row for row in rows if row.opcode is Opcode.ATTRIBUTE]
        if not selected:
            continue
        _need(len(rows) == 1 and len(selected) == 1, "source getter lacks one original operation link")
        link = selected[0]
        node, = nodes[_span(link.source)]
        _need(original(node) == link.source, "source getter Attribute occurrence changed")
        definition = semantic.definitions.get(link.semantic_operation)
        _need(definition is not None and definition.kind is OperationKind.ATTRIBUTE
            and definition.code_id == link.source.atom_id.wire
            and link.source.atom_id in definition.source_atoms
            and definition.metadata.get("attribute") == node.attr
            and definition.metadata.get("role") != "binding", "source getter lost its original SG selector")
        owner, = [row for row in uses[identity] if row.role == "receiver" and row.index == 0]
        _need(owner.source == original(node.value), "source getter receiver occurrence changed")
        child_slots = read_slots[definition.id]
        children = [row for row in definitions_by_atom[owner.source.atom_id]
            if row.code_id == owner.source.atom_id.wire and owner.source.atom_id in row.source_atoms
            and row.metadata.get("role") != "binding" and set(row.output_slots) & child_slots]
        _need(len(children) == 1, "source getter receiver is not its original SG input")
        selector = derive_attribute_selector(node, source_tree=tree, source=link.source,
            source_text=source_text, source_for_node=original, source_facts=facts)
        expected.append(_interface(operations[identity], values, blocks, link.source,
            owner.use, selector, Form.SOURCE_GETATTR))

    if compiler_overlay is not None:
        _need(compiler_evidence is not None, "compiler lookup needs independently checked original code evidence")
        instructions = {row.offset: row for row in dis.get_instructions(
            compiler_evidence.code, adaptive=False, show_caches=False)}
        for witness in compiler_overlay.instructions:
            if witness.opcode != "LOAD_ATTR":
                continue
            instruction = instructions.get(witness.offset)
            _need(instruction is not None and instruction.opname == "LOAD_ATTR"
                and instruction.arg == witness.argument
                and tuple(instruction.positions) == witness.positions,
                "compiler lookup instruction/position differs from independent source compilation")
            rows = links[witness.operation]
            _need(len(rows) == 1 and rows[0].source == witness.source,
                "compiler lookup lost its original source correspondence")
            node, = nodes[_span(witness.source)]
            _need(original(node) == witness.source, "compiler getter lacks its exact source Attribute")
            op = operations[witness.operation]
            _need(len(op.uses) == 3, "compiler getter owner/key/world operand arity differs")
            selector = derive_attribute_selector(node, source_tree=tree, source=witness.source,
                source_text=source_text, source_for_node=original, compiler_evidence=compiler_evidence,
                source_facts=facts)
            selector = replace(selector, key_use=op.uses[1].id)
            _need(selector.lookup_name == instruction.argval,
                "compiler lookup name differs from the source/compiler selector")
            form = Form.CPYTHON_LOAD_METHOD if instruction.arg & 1 else Form.CPYTHON_LOAD_ATTR
            expected.append(_interface(op, values, blocks, witness.source, op.uses[0].id, selector, form))
    return tuple(expected)


def validate_source_attribute_lookups(graph, metadata, **inputs):
    """Legacy None is unrecorded; a new table must match fresh source inputs."""
    if graph.attribute_lookups is None:
        return True
    expected = derive_source_attribute_lookups(graph, metadata, **inputs)
    _need(len({row.operation for row in expected}) == len(expected), "lookup occurrence derived more than once")
    actual = {row.operation: row for row in graph.attribute_lookups}
    _need(len(actual) == len(graph.attribute_lookups)
        and actual == {row.operation: row for row in expected},
        "recorded lookup table differs from original source/compiler requests or omits an occurrence")
    return True


__all__ = ["register_attribute_lookup", "derive_source_attribute_lookups", "validate_source_attribute_lookups"]
