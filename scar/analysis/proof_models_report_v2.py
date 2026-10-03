"""Public, nonexecuting source proof models; no legality or rewrite selection."""
from pathlib import Path
import time
import tokenize

from scar.ir.frontend_v2 import build_semantic
from scar.ir.control_flow_v2 import ControlFlowBudget
from .constants_v2 import EvaluationBudget
from .control_flow_v2 import build_source_control_flow
from .primitive_semantics_v2 import derive_primitive_semantics
from .source_semantics_v2 import extract_source_semantics


def report_source_proof_models(source, *, project_root=None,
                               control_budget=ControlFlowBudget(),
                               primitive_budget=EvaluationBudget()):
    started = time.perf_counter()
    if type(control_budget) is not ControlFlowBudget or type(primitive_budget) is not EvaluationBudget:
        raise TypeError("control and primitive budgets must use their typed records")
    control_budget.__post_init__()
    primitive_budget.__post_init__()
    frontend = build_semantic(source, project_root=project_root)
    # Share decoded snapshots across independent fixed-rule derivations. Each
    # model checks their fingerprints; no target namespace is loaded.
    sources = {}
    for module in frontend.graph.modules.values():
        if module.path is not None and module.path not in sources:
            with tokenize.open(module.path) as stream:
                sources[module.path] = stream.read()
    semantics = extract_source_semantics(frontend.graph, sources=sources)
    control = build_source_control_flow(frontend.graph, semantics, sources=sources,
                                       budget=control_budget)
    primitive = derive_primitive_semantics(frontend.graph, semantics, source_texts=sources,
                                         budget=primitive_budget)
    return {
        "schema": "scar.source-proof-models-report", "schema_version": 1,
        "status": "Inferred", "input": str(Path(source).resolve()),
        "scope": "Selected source snapshots and fixed primitive/control models; no target execution, import or optimization legality follows.",
        "file_selection": {"mode": "PROJECT_TREE" if project_root is not None else "SOURCE_INPUT",
                           "paths": sorted(sources), "import_reachability_proven": False},
        "semantic": frontend.graph.to_dict(), "source_semantics": semantics.to_dict(),
        "control_flow": control.to_dict(),
        "primitive_semantics": primitive.to_dict(source_texts=sources,
                                                  verification_budget=primitive_budget),
        "summary": {"files": len(sources), "control_flow": control.summary(),
                    "primitive_semantics": primitive.summary()},
        "decision": {"selection_status": "NOT_SELECTED", "cost_status": "PENDING",
                     "legality_status": "NOT_EVALUATED", "applied": False},
        "measurement": {"analysis_seconds": time.perf_counter() - started,
                        "scope": "SCAR source analysis only, not workload execution or speedup"},
    }


__all__ = ["report_source_proof_models"]
