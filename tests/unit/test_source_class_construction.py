"""Parent class ports are built from source; the application never runs."""
from copy import deepcopy
from dataclasses import replace

import pytest

from scar.analysis.program_lowering import SourceProgram, prepare_source_text
from scar.analysis.source_class_construction_validation import validate_class_constructions
from scar.analysis.source_language import SourceLanguageOptions
from scar.analysis.source_module_lowering import lower_module_entry, module_unit
from scar.analysis.static_compilation import compile_source_unit
from scar.analysis.static_lexical import inspect_lexical
from scar.analysis.static_rules import plan_static_entry
from scar.ir.program.functions import BodyLoweringProfile
from scar.ir.program.module_entries import FrameBodyProfile
from scar.ir.program.source_language import SourceLanguageCapability as C
from scar.ir.record_codec import decode
from scar.ir.v2.common import SourceReference
from scar.ir.v2.ids import OperationDefinitionID


MODULE = """@first()
@second
class C(Base, other(), metaclass=Meta, flag=value):
    x = 1
after = 2
raise RuntimeError('this application must never execute')
"""

FUNCTION = """def factory(x):
    @first()
    @second
    class C(Base, other(), metaclass=Meta, flag=x):
        value = x
    return C
raise RuntimeError('this application must never execute')
"""


def test_parent_class_ports_roundtrip_without_running_and_reject_substitutions(tmp_path):
    path = tmp_path / 'module_application.py'
    prepared = prepare_source_text(path, MODULE, project_root=tmp_path, root_is_package=False)
    unit = module_unit(prepared)
    evidence = compile_source_unit(prepared).for_module(unit)
    module = lower_module_entry(prepared, unit, code_evidence=evidence,
        profile=FrameBodyProfile.STRUCTURED_MAPPING_CLASS_314_V1)
    wire = module.to_dict()
    assert wire['schema_version'] == 12
    assert len(module.module.class_constructions) == 1
    assert any(row.source.start_line == 5 for row in module.module.expansions)
    assert SourceProgram.read_structure(wire, source_texts={str(path): MODULE}).graph == module.graph
    assert not path.exists()

    # Passing a class can expose a later function factory in a module whose
    # annotation machinery owns compiler cells. The historical root profile
    # still rejects those cells; the explicit compiler profile must connect
    # and validate their real prologue before consuming the function factory.
    annotation_source = ('"""Module with annotations."""\nfrom __future__ import annotations\nclass C: pass\n'
                         'def f(): return 1\ncache: dict[str, int] = {}\n')
    annotation_path = tmp_path / 'annotation_application.py'
    annotation_prepared = prepare_source_text(annotation_path, annotation_source,
        project_root=tmp_path, root_is_package=False)
    annotation_unit = module_unit(annotation_prepared)
    annotation_evidence = compile_source_unit(annotation_prepared).for_module(annotation_unit)
    assert annotation_evidence.code.co_cellvars == ('__conditional_annotations__',)
    from scar.analysis.source_module_lowering import require_root_evidence
    with pytest.raises(ValueError, match='exact non-resumable exec root'):
        require_root_evidence(annotation_unit, annotation_evidence)
    annotation_module = lower_module_entry(annotation_prepared, annotation_unit,
        code_evidence=annotation_evidence, profile=FrameBodyProfile.STRUCTURED_MAPPING_CLASS_314_V1)
    assert annotation_module.module.compiler_prologue is not None
    assert any(row.source.start_line == 4 for row in annotation_module.module.expansions)
    assert SourceProgram.read_structure(annotation_module.to_dict(),
        source_texts={str(annotation_path): annotation_source}).graph == annotation_module.graph
    assert not annotation_path.exists()

    function_path = tmp_path / 'function_application.py'
    parent = prepare_source_text(function_path, FUNCTION, project_root=tmp_path, root_is_package=False)
    fingerprint = parent.semantics.sources[str(function_path)].fingerprint
    catalog = inspect_lexical(parent.tree, path=str(function_path), namespace_root=str(tmp_path),
        fingerprint=fingerprint, semantic=parent.semantic, source_text=FUNCTION)
    entry = next(row for row in catalog['entries'] if row['kind'] == 'FUNCTION')
    plan = plan_static_entry(parent.tree, entry, path=str(function_path), fingerprint=fingerprint)
    definition = decode(OperationDefinitionID, entry['semantic_definition_ids'][0])
    reference = decode(SourceReference, entry['source_ref'])
    function_evidence = compile_source_unit(parent).for_definition(definition, reference)
    options = SourceLanguageOptions(tuple(C(value) for value in plan['capabilities']), function_evidence)
    body = parent.seal_for_lowering().lower(entry['name'], source=reference, max_operations=10000,
        expand_candidates=False, profile=BodyLoweringProfile.STRUCTURED_ENV, language_options=options)
    assert body.graph is not None, body.metadata.gaps
    function = SourceProgram(body.graph, body.metadata, parent.semantic, parent.semantics,
        parent.control, BodyLoweringProfile.STRUCTURED_ENV, body.interface, body.frame,
        body.structured, body.language)
    assert function.language.version == 'PYTHON_SOURCE_LANGUAGE_V3'
    assert len(function.language.class_constructions) == 1
    class_record = function.language.class_constructions[0]
    assert len(class_record.factory_closure) == 1
    assert class_record.suite_entry_status == 'PARENT_FACTORY_REFERENCE_ONLY_PREPARED_NAMESPACE_UNCONNECTED'
    assert SourceProgram.read_structure(function.to_dict(),
        source_texts={str(function_path): FUNCTION}).graph == function.graph
    assert not function_path.exists()

    original = module.module.class_constructions[0]
    arguments = dict(graph=module.graph, metadata=module.metadata, records=(original,),
        protocols={row.operation: row for row in module.module.protocols}, code_evidence=evidence,
        source_tree=prepared.tree, semantic=prepared.semantic, module_overlay=module.module,
        structural_only=True)
    altered_suite = replace(original.suite, code_path=(*original.suite.code_path[:-1],
                                                     original.suite.code_path[-1] + 100))
    with pytest.raises(ValueError, match='exact lexical compiler path'):
        validate_class_constructions(**{**arguments, 'records': (replace(original, suite=altered_suite),)})
    wrong_ports = replace(original.builder_call, callee=original.factory_code)
    with pytest.raises(ValueError, match='implicit-call ports'):
        validate_class_constructions(**{**arguments, 'records': (replace(original, builder_call=wrong_ports),)})
    operations = {row.id: row for row in module.graph.operations}
    lookup, factory = operations[original.builder_lookup], operations[original.factory]
    changed_lookup = replace(lookup, uses=(replace(lookup.uses[0], value=factory.uses[1].value),
                                           *lookup.uses[1:]))
    changed_graph = replace(module.graph, operations=tuple(changed_lookup if row.id == lookup.id else row
                                                          for row in module.graph.operations))
    with pytest.raises(ValueError, match='parent saved builtins'):
        validate_class_constructions(**{**arguments, 'graph': changed_graph})

    historical_module = deepcopy(wire)
    historical_module['schema_version'] = 11
    with pytest.raises(ValueError):
        SourceProgram.read_structure(historical_module, source_texts={str(path): MODULE})
    historical_function = deepcopy(function.to_dict())
    historical_function['language']['version'] = 'PYTHON_SOURCE_LANGUAGE_V2'
    with pytest.raises(ValueError):
        SourceProgram.read_structure(historical_function, source_texts={str(function_path): FUNCTION})
