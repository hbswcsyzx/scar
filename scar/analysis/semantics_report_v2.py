"""Source semantics and bounded constant facts, without a rewrite decision."""
from collections import Counter
import time

from scar.ir.frontend_v2 import build_semantic
from .constants_v2 import ConstantStatus, EvaluationBudget, evaluate_constants
from .source_semantics_v2 import extract_source_semantics


def report_semantics(source, *, project_root=None, budget=EvaluationBudget()):
    started = time.perf_counter()
    frontend = build_semantic(source, project_root=project_root)
    model = extract_source_semantics(frontend.graph)
    constants = evaluate_constants(model, budget=budget)
    constant_operations = [model.values[item.value].producer for item in constants.facts.values()
                           if item.status is ConstantStatus.CONSTANT]
    return {
        "schema": "scar.source-semantics-report", "schema_version": 1,
        "input": str(source), "status": "Inferred",
        "scope": "Exact source extraction and bounded builtin type/content reasoning; no runtime identity, effect-removal or profitability proof.",
        "source_witness": "Constructed by the fixed AST extractor from matching source fingerprints; serialized overlays require source replay before planning.",
        "model": model.to_dict(), "constants": constants.to_dict(verification_budget=budget),
        "summary": {
            "files": len(model.sources), "sg_operations": len(frontend.graph.definitions),
            "modeled_operations": len(model.operations), "unmodeled_operations": len(model.unmodeled_operations),
            "static_values": len(model.values), "binding_definitions": len(model.bindings),
            "binding_uses": dict(sorted(Counter(use.status.value for use in model.uses.values()).items())),
            "constant_statuses": dict(sorted(Counter(item.status.value for item in constants.facts.values()).items())),
            "derived_constant_operations": sum(model.operations[identity].opcode.value != "literal"
                                               for identity in constant_operations),
            "source_gaps": len(model.gaps), "selected_transformations": 0, "applied": False,
        },
        "measurement": {"analysis_seconds": time.perf_counter() - started,
                        "scope": "SCAR source analysis, not workload execution or speedup"},
    }


__all__ = ["report_semantics"]
