"""Source-only ownership boundaries compose without executing the application."""
from dataclasses import replace
from hashlib import sha256

import pytest

from scar.analysis.program_lowering import SourceProgram, prepare_source_text
from scar.analysis.source_expression_validation import validate_source_expressions
from scar.analysis.source_language import SourceLanguageOptions
from scar.analysis.static_compilation import compile_source_unit
from scar.analysis.static_lexical import inspect_lexical
from scar.analysis.static_rules import plan_static_entry
from scar.ir.program.functions import BodyLoweringProfile
from scar.ir.program.model import ReferenceValue
from scar.ir.program.source_language import SourceLanguageCapability as C
from scar.ir.program.structured import PythonProtocolKind as K
from scar.ir.record_codec import decode
from scar.ir.v2.common import SourceReference
from scar.ir.v2.ids import OperationDefinitionID


SOURCE = """def mapping_compare(row):
    return row['a'] == {'b': 1}
def comprehension(items):
    return [item for item in items]
def lazy(items):
    return any(s + '://' for s in items)
def formatting(path, item):
    return path / f'{item.name}_weights'
raise RuntimeError('the application must never execute')
"""


def test_source_expression_handoffs_preserve_identity_and_reject_substituted_refs(tmp_path):
    path = tmp_path / 'application.py'
    # The source path need not exist: preparation and compiler evidence consume
    # supplied source bytes, not importlib or application initialization.
    prepared = prepare_source_text(path, SOURCE, project_root=tmp_path, root_is_package=False)
    fingerprint = 'sha256:' + sha256(SOURCE.encode()).hexdigest()
    catalog = inspect_lexical(prepared.tree, path=str(path), namespace_root=str(tmp_path),
        fingerprint=fingerprint, semantic=prepared.semantic, source_text=SOURCE)
    compiled = compile_source_unit(prepared)
    session = prepared.seal_for_lowering()
    bodies = {}
    for entry in catalog['entries']:
        if entry['kind'] != 'FUNCTION':
            continue
        plan = plan_static_entry(prepared.tree, entry, path=str(path), fingerprint=fingerprint)
        definition = decode(OperationDefinitionID, entry['semantic_definition_ids'][0])
        reference = decode(SourceReference, entry['source_ref'])
        evidence = compiled.for_definition(definition, reference)
        options = SourceLanguageOptions(capabilities=tuple(C(value) for value in plan['capabilities']),
                                        code_evidence=evidence)
        body = session.lower(entry['name'], source=reference, max_operations=10000,
            expand_candidates=False, profile=BodyLoweringProfile.STRUCTURED_ENV, language_options=options)
        assert body.graph is not None, body.metadata.gaps
        program = SourceProgram(body.graph, body.metadata, prepared.semantic, prepared.semantics,
            prepared.control, BodyLoweringProfile.STRUCTURED_ENV, body.interface, body.frame,
            body.structured, body.language)
        reread = SourceProgram.read_structure(program.to_dict(), source_texts={str(path): SOURCE})
        assert reread.graph == body.graph
        bodies[entry['name'].rsplit('.', 1)[-1]] = body
    assert len(bodies) == 4 and not path.exists()

    body = bodies['mapping_compare']
    forwards = [marker for marker in body.structured.protocols if marker.kind is K.FRAME_FORWARD_TEMPORARY]
    assert len(forwards) == 1
    forward = next(op for op in body.graph.operations if op.id == forwards[0].operation)
    wrong = next(value.id for value in body.graph.values
                 if type(value) is ReferenceValue and value.id != forward.uses[0].value)
    substituted = replace(forward, uses=(replace(forward.uses[0], value=wrong), forward.uses[1]))
    altered = replace(body.graph, operations=tuple(substituted if op.id == forward.id else op
                                                  for op in body.graph.operations))
    with pytest.raises(ValueError, match='forwarded reference is not the original expression result'):
        validate_source_expressions(body.structured, altered, body.interface, body.metadata,
            prepared.semantic, body.language, source_tree=prepared.tree, structural_only=True,
            selected_operations={forward.id})
    historical = replace(body.language, capabilities=tuple(cap for cap in body.language.capabilities
                                                          if cap is not C.SOURCE_REFERENCE_LIFETIME_314_V1))
    with pytest.raises(ValueError, match='helper forwarding cannot silently upgrade'):
        validate_source_expressions(body.structured, body.graph, body.interface, body.metadata,
            prepared.semantic, historical, source_tree=prepared.tree, structural_only=True,
            selected_operations={forward.id})
