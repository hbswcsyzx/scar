"""One real frontend fixture and the two approved release mutations only."""
import ast
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import time
import traceback
import sys

BASE = Path(__file__).resolve().parent
ROOT = BASE.parents[3]


def main():
    from scar.analysis.program_lowering import prepare_source
    from scar.analysis.source_language import SourceLanguageOptions
    from scar.ir.program.source_language import SourceLanguageCapability
    from scar.analysis.source_string_validation import validate_string_source
    from scar.ir.program.functions import BodyLoweringProfile
    from scar.ir.program.structured import PythonProtocolKind as Kind
    started = time.monotonic()
    context = prepare_source(BASE / "fixture.py", project_root=BASE)
    options = SourceLanguageOptions((SourceLanguageCapability.LEXICAL_LOCALS,))
    result = context.seal_for_lowering().lower("construct", max_operations=4000,
        expand_candidates=False, profile=BodyLoweringProfile.STRUCTURED_ENV, language_options=options)
    assert result.graph is not None, result.metadata.gaps
    string = next(n for n in ast.walk(context.tree) if isinstance(n, ast.JoinedStr))
    atoms = [a for a in context.semantic.source_atoms.values() if a.kind == "JoinedStr"
        and a.reference.start_line == string.lineno and a.reference.start_column == string.col_offset]
    assert len(atoms) == 1
    assert not [r for r in context.semantics.operations.values() if r.source.atom_id == atoms[0].id]
    def validate(graph):
        return validate_string_source(result.structured, graph, result.interface, result.metadata,
            context.semantic, source_tree=context.tree, options=options)
    checks = {"real_frontend_missing_overlay": validate(result.graph)}
    assert checks["real_frontend_missing_overlay"]["records"][0]["pending"]["ordered_local_pending_checked"]
    protocol = next(p for p in result.structured.protocols if p.kind is Kind.BUILD_STRING)
    operation = next(o for o in result.graph.operations if o.id == protocol.operation)
    for name, edge, mutate in (("missing_raise_release", operation.terminator.successors[1], lambda ids: ids[1:]),
                               ("reordered_normal_release", operation.terminator.successors[0], lambda ids: (ids[1], ids[0]) + ids[2:])):
        regions = tuple(replace(r, blocks=tuple(replace(b, operations=mutate(b.operations)) if b.id == edge.block else b
            for b in r.blocks)) for r in result.graph.regions)
        try:
            validate(replace(result.graph, regions=regions))
        except ValueError as error:
            assert "consumed input release" in str(error), error
            checks[name] = {"rejected": True, "message": str(error)}
        else:
            raise AssertionError(name + " was accepted")
    sources=[]
    for relative in ("scar/analysis/source_heap_lowering.py", "scar/analysis/source_string_lowering.py",
                     "scar/analysis/source_string_validation.py", "scar/analysis/source_language_validation.py"):
        data=(ROOT/relative).read_bytes(); sources.append({"path":relative,"bytes":len(data),"sha256":hashlib.sha256(data).hexdigest()})
    return {"status":"PASSED", "checks":checks, "elapsed_s":time.monotonic()-started,
        "operations":len(result.graph.operations), "original_target_body_lowerings":0, "target_executions":0,
        "source_prepares":1, "small_fixture_lowerings":1, "fixture_layout_compilation_performed":True,
        "code_witness_compiler_check_performed":False, "production_sources":sources}


if __name__ == "__main__":
    try:
        receipt=main()
    except BaseException as error:
        receipt={"status":"FAILED", "error":type(error).__name__, "message":str(error), "traceback":traceback.format_exc()}
    with (BASE/("candidate.json" if "--candidate" in sys.argv else "baseline.json")).open("x") as stream:json.dump(receipt,stream,ensure_ascii=False,indent=2,sort_keys=True);stream.write("\n")
    print(json.dumps(receipt,ensure_ascii=False,sort_keys=True))
    raise SystemExit(0 if receipt["status"]=="PASSED" else 1)
