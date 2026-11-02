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


def test_module_literal_bool_if_maps_compiler_elision_without_executing_source(tmp_path, monkeypatch):
    import ast
    import dis
    import scar.analysis.source_module_lowering as lowering
    from scar.ir.program.module_entries import StatementSequenceField as F
    from scar.ir.program.structured import PythonProtocolKind as P

    profile=FrameBodyProfile.STRUCTURED_MAPPING_CLASS_314_V1
    def construct(text,name):
        path=tmp_path/(name+'.py')
        prepared=prepare_source_text(path,text,project_root=tmp_path,root_is_package=False)
        unit=module_unit(prepared);evidence=compile_source_unit(prepared).for_module(unit)
        result=lower_module_entry(prepared,unit,code_evidence=evidence,profile=profile)
        wire=result.to_dict()
        assert SourceProgram.read_structure(wire,source_texts={str(path):text}).graph==result.graph
        assert not path.exists()  # Compilation and independent replay never exec the source.
        return prepared,evidence,result,wire

    # Unsupported dead syntax stays in original source suites, not runtime
    # expansions.  Both choices are obtained from the original compiler rule.
    for choice in (True,False):
        active='    result = must_not_execute()\n'
        dead='    raise must_not_execute_dead()\n'
        body,orelse=(active,dead) if choice else (dead,active)
        text=f'if {choice}:\n'+body+'else:\n'+orelse+'after = 1\n'
        prepared,evidence,result,wire=construct(text,'literal_'+str(choice))
        assert result.module.remaining is None
        enclosing=next(row for row in result.module.expansions if row.source.start_line==1)
        witness=enclosing.compiler_elision
        assert witness.selected is (F.BODY if choice else F.ORELSE)
        assert witness.root_code_layout_key==evidence.root_code_layout_key
        assert tuple(row.field for row in enclosing.child_slices)==(F.BODY,F.ORELSE)
        selected_line=2 if choice else 4;dead_line=4 if choice else 2
        assert {row.source.start_line for row in result.module.expansions}=={1,selected_line,5}
        assert not any(row.source.start_line==dead_line for row in result.module.operation_links
                       if isinstance(row.source,SourceReference))
        assert not any(row.kind is P.TRUTH for row in result.module.protocols)
        assert not any(op.terminator and op.terminator.kind.value=='BRANCH' for op in result.graph.operations)
        assert {row.offset for row in dis.get_instructions(evidence.code)
                if tuple(row.positions)==(1,1,3,3+len(str(choice)))}==set(witness.test_instruction_offsets)

        if choice:
            for field,value in (('selected',F.ORELSE.value),
                    ('root_code_layout_key','pycode-v2:'+'0'*64),
                    ('test_instruction_offsets',[999999])):
                changed=deepcopy(wire)
                row=next(row for row in changed['module']['expansions'] if row.get('compiler_elision'))
                row['compiler_elision'][field]=value
                with pytest.raises(ValueError):
                    SourceProgram.read_structure(changed,source_texts={str(prepared.path):text})
            changed=deepcopy(wire)
            next(row for row in changed['module']['expansions'] if row.get('compiler_elision')).pop('compiler_elision')
            with pytest.raises(ValueError):
                SourceProgram.read_structure(changed,source_texts={str(prepared.path):text})

    # A dead annotation still causes compiler-owned state/factory setup.  A
    # source global declaration in that same dead suite still changes scope.
    for future in (False,True):
        text=('from __future__ import annotations\n' if future else '')+(
            'if False:\n    global after\n    unreachable: annotation() = rhs()\nafter = 1\n')
        prepared,evidence,result,wire=construct(text,'dead_annotation_'+str(future))
        assert result.module.remaining is None
        prologue=result.module.compiler_prologue
        assert prologue is not None and prologue.cells
        assert len(prologue.children)==(0 if future else 1)
        if not future:
            witness=next(row.compiler_elision for row in result.module.expansions if row.compiler_elision)
            assert witness.test_instruction_offsets==()  # Compiler can eliminate even the NOP.
        assert any(row.kind is P.STORE_GLOBAL and row.source.start_line==(5 if future else 4)
                   for row in result.module.protocols)
        assert not any(row.source.start_line==(4 if future else 3) for row in result.module.operation_links
                       if isinstance(row.source,SourceReference))
        changed=deepcopy(wire)
        # Keep duplicated declaration/prelude receipts internally consistent;
        # only independent recompilation can establish their true provenance.
        for receipt in (changed['module']['declaration']['compilation'],
                        changed['module']['compiler_prologue']['compilation']):
            for key in ('code_layout_key','root_code_layout_key'):
                receipt[key]='pycode-v2:'+'0'*64
        with pytest.raises(ValueError,match='independently compiled retained source'):
            SourceProgram.read_structure(changed,source_texts={str(prepared.path):text})

    # Nested selection and an empty selected suite need no invented join or
    # runtime no-op.  Implicit module completion may own the test positions.
    text='if True:\n    if False:\n        dead()\n    else:\n        pass\nelse:\n    dead_outer()\n'
    _,_,result,_=construct(text,'nested_empty')
    assert result.module.remaining is None
    assert len([row for row in result.module.expansions if row.compiler_elision])==2
    assert all(not row.operations and row.entry==row.normal for row in result.module.expansions)
    _,_,result,_=construct('if False:\n    dead()\n','empty_tail')
    assert result.module.remaining is None and not result.module.expansions[0].operations

    # Ordinary Ifs and compiler-foldable arithmetic keep their prior path.
    for test in ('flag','1+1'):
        _,_,result,_=construct(f'if {test}:\n    value = one()\nelse:\n    value = two()\n','dynamic_'+str(len(test)))
        assert not any(row.compiler_elision for row in result.module.expansions)
        assert any(row.kind is P.TRUTH for row in result.module.protocols)
    prepared,evidence,_,_=construct('def child():\n    if True: return 1\n','foreign_scope')
    child_if=next(node for node in ast.walk(prepared.tree) if isinstance(node,ast.If))
    with pytest.raises(ValueError,match='module scope'):
        lowering.mapping_literal_bool_if_plan(prepared,evidence,child_if,profile=profile)

    # Emit a historical conservative prefix using its unchanged admission
    # mode, then independently read that old wire after restoring new rules.
    original_selection=lowering.mapping_prefix_selection
    def old_selection(context,evidence,*,profile=None,literal_bool_elision=False,module_annotations=False):
        return original_selection(context,evidence,profile=profile,literal_bool_elision=False)
    text='sentinel = 0\nif True:\n    value = kept()\nelse:\n    value = dead()\nafter = 1\n'
    with monkeypatch.context() as patch:
        patch.setattr(lowering,'mapping_prefix_selection',old_selection)
        prepared,_,legacy,wire=construct(text,'legacy_prefix')
    assert [row.start_line for row in legacy.module.prefix.statements]==[1]
    assert all('compiler_elision' not in row for row in wire['module']['expansions'])
    reread=SourceProgram.read_structure(wire,source_texts={str(prepared.path):text})
    assert reread.module.remaining.subject.statements[0].start_line==2

    # Module annotation indices belong to original compilation, including
    # source in a compiler-elided arm; they must not be renumbered at runtime.
    from scar.ir.program.module_entries import ModuleAnnotationMode as AM,FrameBodyProtocolKind as MK
    from scar.ir.program.model import ExitKind
    for future in (False,True):
        text=('from __future__ import annotations\n' if future else '')+(
            'if False:\n    skipped: never_evaluate() = never_execute()\n'
            'first: annotation_one() = {}\nsecond: annotation_two()\nafter = 1\n')
        prepared,evidence,result,wire=construct(text,'live_annotation_'+str(future))
        assert result.module.remaining is None
        declarations=[row for row in result.module.expansions if row.compiler_annotation]
        assert len(declarations)==2
        assert all(row.compiler_annotation.mode is (AM.FUTURE_STRING if future else AM.LAZY_SET)
                   for row in declarations)
        assert declarations[0].compiler_annotation.rhs_empty_dict_offset is not None
        assert declarations[1].compiler_annotation.rhs_empty_dict_offset is None
        values={row.id:row for row in result.graph.values}
        operations={row.id:row for row in result.graph.operations}
        blocks={row.id:row for region in result.graph.regions for row in region.blocks}
        markers=[row for row in result.module.protocols if row.source in {s.source for s in declarations}
                 and row.kind is (P.STORE_SUBSCRIPT if future else MK.SET_ADD_314)]
        assert len(markers)==2
        if not future:
            assert [values[operations[row.operation].uses[1].value].origin.value for row in markers]==[1,2]
        for marker in markers:
            update=operations[marker.operation]
            lookup,=[operations[row.operation] for row in result.module.protocols
                     if row.kind is MK.LOAD_NAME_314 and row.source==marker.source]
            landing=blocks[next(edge.block for edge in lookup.terminator.successors if edge.kind is ExitKind.NORMAL)]
            assert update.uses[0].value==landing.arguments[0]
            assert update.uses[0].value not in result.module.compiler_prologue.cell_values
            assert not update.effects_complete
        marker=markers[0];update=operations[marker.operation]
        for index,replacement in ((0,result.module.compiler_prologue.cell_values[0]),
                                  (-1,result.graph.frame_roots[0].entry.world)):
            selected=update.uses[index].id
            changed_op=replace(update,uses=tuple(replace(use,value=replacement) if use.id==selected else use
                                                for use in update.uses))
            changed=replace(result,graph=replace(result.graph,operations=tuple(
                changed_op if op.id==update.id else op for op in result.graph.operations)))
            with pytest.raises(ValueError):
                SourceProgram.read_structure(changed.to_dict(),source_texts={str(prepared.path):text})
        changed=deepcopy(wire)
        receipt=next(row['compiler_annotation'] for row in changed['module']['expansions']
                     if row.get('compiler_annotation'))
        receipt['statement_instruction_offsets']=[999999]
        with pytest.raises(ValueError):
            SourceProgram.read_structure(changed,source_texts={str(prepared.path):text})

    # Adding this capability must not reinterpret an older annotation suffix.
    text='before = 1\nvalue: NotEvaluated = {}\nafter = 2\n'
    with monkeypatch.context() as patch:
        patch.setattr(lowering,'mapping_prefix_selection',old_selection)
        prepared,_,_,wire=construct(text,'legacy_annotation')
    reread=SourceProgram.read_structure(wire,source_texts={str(prepared.path):text})
    assert reread.module.remaining.subject.statements[0].start_line==2
    assert all('compiler_annotation' not in row for row in wire['module']['expansions'])
    for index,text in enumerate(('value: T = {1: 2}\n','(value): T = rhs()\n')):
        _,_,result,_=construct(text,'unsupported_annotation_'+str(index))
        assert result.module.prefix is None and result.module.remaining is not None


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

    # In 3.14 generated annotation setup shares the first import's source
    # position. Its already modeled compiler prefix must run before the real
    # import, without making that import or the subsequent definitions residual.
    for first_import in ('import never_execute_target',
                         'from never_execute_target import exported',
                         'from __future__ import annotations'):
        first_import_source = (first_import + '\nclass C: pass\n'
                               'def f(): return 1\ncache: int = 1\n')
        first_import_path = tmp_path / 'first_import_application.py'
        first_import_prepared = prepare_source_text(first_import_path, first_import_source,
            project_root=tmp_path, root_is_package=False)
        first_import_unit = module_unit(first_import_prepared)
        first_import_evidence = compile_source_unit(first_import_prepared).for_module(first_import_unit)
        first_import_module = lower_module_entry(first_import_prepared, first_import_unit,
            code_evidence=first_import_evidence, profile=FrameBodyProfile.STRUCTURED_MAPPING_CLASS_314_V1)
        assert first_import_module.module.compiler_prologue is not None
        assert [row.source.start_line for row in first_import_module.module.expansions] == [1, 2, 3, 4]
        assert first_import_module.module.remaining is None
        assert first_import_module.module.expansions[-1].compiler_annotation is not None
        assert SourceProgram.read_structure(first_import_module.to_dict(),
            source_texts={str(first_import_path): first_import_source}).graph == first_import_module.graph
        assert not first_import_path.exists()

    global_source = 'global value\nvalue = 1\nvalue = 11\ndef read(): return value\n'
    global_path = tmp_path / 'global_application.py'
    global_prepared = prepare_source_text(global_path, global_source,
        project_root=tmp_path, root_is_package=False)
    global_unit = module_unit(global_prepared)
    global_evidence = compile_source_unit(global_prepared).for_module(global_unit)
    global_module = lower_module_entry(global_prepared, global_unit, code_evidence=global_evidence,
        profile=FrameBodyProfile.STRUCTURED_MAPPING_CLASS_314_V1)
    assert global_module.module.remaining is None
    declaration = next(row for row in global_module.module.expansions if row.source.start_line == 1)
    assert declaration.operations == () and declaration.entry == declaration.normal
    stores = [row for row in global_module.module.protocols if row.kind.value == 'STORE_GLOBAL']
    assert {row.source.start_line for row in stores} == {2, 3}
    assert SourceProgram.read_structure(global_module.to_dict(),
        source_texts={str(global_path): global_source}).graph == global_module.graph
    assert not global_path.exists()

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
