"""A module assertion connects both worlds without executing its source."""
from dataclasses import replace
import sys

import pytest


@pytest.mark.skipif(sys.implementation.name != 'cpython' or sys.version_info[:3] != (3, 14, 7),
    reason='the assertion compiler mapping uses the pinned CPython3.14.7 layout')
def test_module_assertion_message_pair_and_legacy_prefix(tmp_path, monkeypatch):
    from scar.analysis.program_lowering import prepare_source_text
    from scar.analysis.static_compilation import compile_source_unit
    import scar.analysis.source_module_lowering as lowering
    from scar.analysis.source_module_validation import require_valid_structured_module_program
    from scar.ir.program.model import ExitKind, TerminatorKind
    from scar.ir.program.module_entries import FrameBodyProfile
    from scar.ir.program.structured import PythonProtocolKind as K

    marker = tmp_path / 'target-was-executed'
    path = tmp_path / 'program.py'
    text = (f'open({str(marker)!r}, "x").close()\n'
        'before = initial()\nassert check(), message()\nafter = finish()\n')
    prepared = prepare_source_text(str(path), text, project_root=str(tmp_path), root_is_package=False)
    unit = lowering.module_unit(prepared)
    evidence = compile_source_unit(prepared).for_module(unit)
    profile = FrameBodyProfile.STRUCTURED_MAPPING_CLASS_314_V1
    result = lowering.lower_module_entry(prepared, unit, code_evidence=evidence, profile=profile)
    assert result.module.remaining is None and not marker.exists()
    operations = {operation.id: operation for operation in result.graph.operations}
    blocks = {block.id: block for region in result.graph.regions for block in region.blocks}
    marked = {record.kind: operations[record.operation] for record in result.module.protocols
        if record.kind in (K.TRUTH, K.MAKE_ASSERTION_ERROR, K.FUNCTION_START_PROPAGATION)}
    assert set(marked) == {K.TRUTH, K.MAKE_ASSERTION_ERROR, K.FUNCTION_START_PROPAGATION}
    truth = marked[K.TRUTH]
    normal = blocks[next(edge.block for edge in truth.terminator.successors if edge.kind is ExitKind.NORMAL)]
    branch = operations[normal.operations[-1]]
    assert branch.terminator.kind is TerminatorKind.BRANCH
    assertion = next(row for row in result.module.expansions if row.source.start_line == 3)
    following = next(row for row in result.module.expansions if row.source.start_line == 4)
    assert branch.terminator.successors[0].block == assertion.normal == following.entry
    constructor = marked[K.MAKE_ASSERTION_ERROR]
    created = blocks[next(edge.block for edge in constructor.terminator.successors if edge.kind is ExitKind.NORMAL)]
    propagation = marked[K.FUNCTION_START_PROPAGATION]
    assert propagation.uses[0].value == created.arguments[0]
    propagated = blocks[next(edge.block for edge in propagation.terminator.successors if edge.kind is ExitKind.NORMAL)]
    assert len(propagated.arguments) == 3  # Exception, traceback, post-world.
    assert any('message' == value.origin.value for value in result.graph.values
        if hasattr(value.origin, 'value'))

    # A reference with the right type cannot substitute for the newly
    # constructed exception merely because propagation expects a reference.
    changed = replace(propagation, uses=(replace(propagation.uses[0], value=truth.uses[0].value),
        *propagation.uses[1:]))
    bad_graph = replace(result.graph, operations=tuple(changed if row.id == changed.id else row
        for row in result.graph.operations))
    with pytest.raises(ValueError, match='newly constructed assertion exception'):
        require_valid_structured_module_program(replace(result, graph=bad_graph),
            source_texts={str(path): text}, code_evidence=evidence)

    # Old finite-prefix products keep the exact unexpanded Assert/suffix;
    # newer admission is a capability, never a reinterpretation of old bytes.
    original = lowering.mapping_prefix_selection
    def legacy_selection(*args, **kwargs):
        return original(*args, **{**kwargs, 'module_assertions': False})
    with monkeypatch.context() as patch:
        patch.setattr(lowering, 'mapping_prefix_selection', legacy_selection)
        legacy = lowering.lower_module_entry(prepared, unit, code_evidence=evidence, profile=profile)
    require_valid_structured_module_program(legacy, source_texts={str(path): text}, code_evidence=evidence)
    assert legacy.module.remaining is not None
    assert not any(record.kind is K.MAKE_ASSERTION_ERROR for record in legacy.module.protocols)
    assert not marker.exists()
