"""Two internal producer/core fixtures. No target execution or public witness claim.

The fixture compiler input is deliberately not SourceCodeEvidence: public
SourceLanguageOptions must reject it. A real qualified replay remains Root's gate.
"""
import ast
from dataclasses import replace
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import traceback

BASE = Path(__file__).resolve().parent

def main():
    from scar.analysis.program_lowering import prepare_source, _Unsupported
    from scar.analysis.environment_lowering import StructuredEnvironmentBuilder
    from scar.analysis.source_language import SourceLanguageOptions
    from scar.ir.program.source_language import SourceLanguageCapability as C
    from scar.ir.program.structured import StructuredBodyModel, PythonProtocolKind as K
    from scar.ir.program.source import LoweringMetadata
    from scar.ir.program.model import TerminatorKind, StateVersionValue
    from scar.ir.program.validation import require_valid
    from scar.analysis.source_generator_validation import validate_generator_regions
    from scar.trace.code_snapshot import describe_code
    context = prepare_source(BASE / 'fixture.py', project_root=BASE)
    module = compile(context.text, str(context.path), 'exec', dont_inherit=True)
    code = next(c for c in module.co_consts if getattr(c, 'co_name', None) == 'construct')
    caps = (C.FIXED_UNPACK, C.LEXICAL_LOCALS, C.GENEXPR_314_V1)
    compiler_input = SimpleNamespace(code=code, captured=SimpleNamespace(key=describe_code(code)['key']))
    try:
        SourceLanguageOptions(caps, compiler_input)
    except ValueError:
        pass
    else:
        raise AssertionError('public API accepted a fixture compiler input as witness')
    # Internal-only helper fixture. No fake SourceCodeEvidence is constructed.
    def fixture_definition(snapshot, definition, source):
        assert snapshot == context.semantics.sources[str(context.path)]
        original = context.semantic.definitions[definition]
        assert source.atom_id in original.source_atoms and original.metadata.get('phase') == 'call_time'
    compiler_input.require_definition = fixture_definition
    builder = StructuredEnvironmentBuilder(context, 'construct', language_options=SourceLanguageOptions(caps))
    builder.language_options = SimpleNamespace(capabilities=caps, code_evidence=compiler_input)
    try:
        node = builder.build_function()
    except _Unsupported as e:
        raise AssertionError((e.kind, e.detail, ast.dump(e.node))) from e
    graph = builder.make_graph()
    require_valid(graph)
    model = StructuredBodyModel(builder.function_definition.id, builder.function_context, builder.source(node),
                                tuple(builder.protocols), tuple(builder.loops))
    metadata = LoweringMetadata(builder.entry, builder.snapshot, tuple(builder.operation_links), tuple(builder.value_links),
        (), tuple(builder.gaps), builder.assumptions(), tuple(builder.use_links))
    from scar.ir.program.source_language import SourceLanguageOverlay
    language = SourceLanguageOverlay(builder.snapshot, caps, tuple(builder.language_unpackings), (),
                                    tuple(builder.language_constants), tuple(builder.language_compiler_locals), None, namespace_root=str(BASE))
    delegated = validate_generator_regions(model, graph, builder.interface, metadata, context.semantic, language, structural_only=True)
    from scar.analysis.structured_lowering import require_valid_structured_body
    require_valid_structured_body(model,graph,builder.interface,metadata,semantic=context.semantic,
        control=context.control,language=language,structural_only=True)
    from scar.ir.program.codec import dumps, loads
    payload=dumps(graph)
    restored=loads(payload)
    require_valid(restored)
    from scar.analysis.program_lowering import SourceProgram
    from scar.ir.program.functions import BodyLoweringProfile
    program=SourceProgram(graph,metadata,context.semantic,context.semantics,context.control,
        BodyLoweringProfile.STRUCTURED_ENV,builder.interface,None,model,language)
    document=program.to_dict()
    SourceProgram.from_dict(document,verification='STRUCTURE',source_texts={str(context.path):context.text})
    owners = {key:r.id for r in graph.regions for b in r.blocks for key in b.operations}
    ops={o.id:o for o in graph.operations}
    body=graph.resumable_bodies[0].region
    gen=next(n for n in ast.walk(context.tree) if isinstance(n,ast.GeneratorExp))
    refs={l.operation:l.source for l in metadata.operation_links}
    attrs=[k for k,ref in refs.items() if ref.start_line==gen.elt.keywords[0].value.lineno
           and ref.start_column==gen.elt.keywords[0].value.col_offset]
    assert attrs and all(owners[k]==body for k in attrs)
    create=graph.resumable_creates[0]
    assert ops[create.operation].callee is None
    assert all(ops[o.operation].callee!=body for o in graph.resumable_creates)
    unpack=language.unpackings[0]
    u=ops[unpack.operation].callee
    calls=[o for o in graph.operations if owners[o.id]==u and o.callee is not None]
    assert len(calls)==3
    assert len({d.body for d in graph.driver_interfaces})==1
    assert not graph.created_close_tests and not graph.no_body_finishes
    escapes=[p for p in model.protocols if p.kind is K.GENERATOR_ESCAPE_STOPITER_TO_RUNTIME_ERROR]
    assert escapes and all(owners[p.operation]==body for p in escapes)
    assert any('CLOSE/THROW' in gap.detail for gap in metadata.gaps)
    rejected=[]
    orphan=replace(graph.regions[-1],id=type(graph.root)('fixture-orphan-region'))
    try:
        validate_generator_regions(model,replace(graph,regions=(*graph.regions,orphan)),builder.interface,metadata,context.semantic,language,structural_only=True)
    except ValueError as e:
        rejected.append(str(e))
    else:raise AssertionError('orphan region accepted')
    arity_op=next(ops[p.operation] for p in model.protocols if p.kind is K.MAKE_UNPACK_ARITY_ERROR)
    arity_id=arity_op.uses[1].value
    altered=tuple(replace(v,origin=type(v.origin)(99)) if v.id==arity_id else v for v in graph.values)
    try:
        validate_generator_regions(model,replace(graph,values=altered),builder.interface,metadata,context.semantic,language,structural_only=True)
    except ValueError as e:
        assert 'actual probe ordinal' in str(e),str(e);rejected.append(str(e))
    else:raise AssertionError('incorrect unpack probe accepted')
    return dict(status='PASSED',operations=len(graph.operations),regions=len(graph.regions),checks={
        'creation_does_not_execute_elt_and_captures_cell':True,
        'fixed_unpack_N_plus_one_and_exception_close_boundary':True},
        rejected=rejected,public_code_witness_check=False,fixture_module_compiles=1,
        target_executions=0,real_body_lowerings=0,raw_reads=0,core_wire_version=json.loads(payload)['schema_version'],
        source_program_wire_version=document['schema_version'],
        still_open=['CLOSE/THROW adapter','callee/effects/RNG/runtime','intermediate child consumption and outer lifetime'])

if __name__=='__main__':
    import sys
    try:r=main()
    except BaseException as e:r=dict(status='FAILED',error=type(e).__name__,message=str(e),traceback=traceback.format_exc())
    path=BASE/sys.argv[1]
    with path.open('x') as f:json.dump(r,f,indent=2,sort_keys=True);f.write('\n')
    print(json.dumps(r,sort_keys=True))
    raise SystemExit(r['status']!='PASSED')
