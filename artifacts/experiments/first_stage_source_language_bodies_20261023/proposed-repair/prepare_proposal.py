"""Write a reviewed candidate patch; never modify production modules."""
import ast
import difflib
from hashlib import sha256
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
originals = {}
candidates = {}


def current(name):
    text = (ROOT / name).read_text()
    originals[name] = text
    return text


name = 'scar/analysis/structured_lowering.py'
text = current(name)
old = 'validate_environment_body(model, graph, interface, metadata, semantic)'
assert text.count(old) == 1
candidates[name] = text.replace(old, old[:-1] + ', language=language)')

name = 'scar/analysis/source_environment_validation.py'
text = current(name)
old = 'def validate_environment_body(model, graph, interface, metadata, semantic):'
assert text.count(old) == 1
text = text.replace(old, old[:-2] + ', *, language=None):')
anchor = '    need(set(rows) == expected_rows, "unexpected or missing source environment address refinement")'
extra = '''    if language is not None:
        from scar.ir.program.source_language import SourceLanguageCapability
        from scar.ir.v2.semantic import OperationKind
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
'''
# The old complete equality is deliberately retained; there is no wildcard
# skip or deletion of an address record.
assert text.count(anchor) == 1
text = text.replace(anchor, extra + anchor)
text = text.replace('AddressCoverage, AddressEffect, CellContent, InvokeStateOperand, NamespaceKey, ReferenceOwner,',
                    'AddressCoverage, AddressEffect, CellContent, Element, InvokeStateOperand, NamespaceKey, ReferenceOwner,')
candidates[name] = text

name = 'scar/analysis/source_language_validation.py'
text = current(name)
anchor = '    for identity, constant in constants.items():'
extra = '''    if Capability.SLICE_KEYS in language.capabilities:
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
'''
assert text.count(anchor) == 1
candidates[name] = text.replace(anchor, extra + anchor)

patches = []
rows = []
for name, text in candidates.items():
    ast.parse(text, filename=name)
    patches.extend(difflib.unified_diff(originals[name].splitlines(keepends=True), text.splitlines(keepends=True),
                                      fromfile='a/' + name, tofile='b/' + name))
    rows.append({'path': name, 'original_sha256': sha256(originals[name].encode()).hexdigest(),
                 'candidate_sha256': sha256(text.encode()).hexdigest()})
patch = ''.join(patches).encode()
(HERE / 'attempt02-proposed.patch').write_bytes(patch)
(HERE / 'proposal.json').write_text(json.dumps({'status': 'PROPOSED_NOT_APPLIED', 'modules': rows,
    'patch_sha256': sha256(patch).hexdigest(), 'ast_candidate_pass': True,
    'production_files_edited': False, 'new_actual_runtime_events': False,
    'index_read_scope': 'partial source address only; custom getitem side effects/alias/resources remain incomplete'}, indent=2) + '\n')
print(json.dumps(rows, indent=2))
