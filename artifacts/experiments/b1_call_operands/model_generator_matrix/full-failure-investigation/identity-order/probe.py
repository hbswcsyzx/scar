"""Read-only fresh-process query probe; no pytest or test functions executed."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time


WATCHED = (
    "scar/ir/literals.py", "scar/ir/program/model.py",
    "scar/ir/program/created_close.py", "scar/ir/program/protocol_flow.py",
    "scar/ir/program/protocol_query.py", "scar/ir/program/protocol_validation.py",
    "tests/fixtures/program_generator_admission_graphs.py",
)


def source_hashes():
    return {name: hashlib.sha256(Path(name).read_bytes()).hexdigest() for name in WATCHED}


def child():
    import scar.ir.literals as literals
    import scar.ir.program.created_close as created
    from scar.ir.program.drivers import RawRequestKind
    from scar.ir.program.model import OperationResult
    from scar.ir.program.protocols import ProtocolProfile
    from scar.ir.program.queries import ProgramIndex
    from tests.fixtures.program_generator_admission_graphs import generator_admission_program

    graph, details = generator_admission_program(stage="created", kind=RawRequestKind.CLOSE)
    scope = next(row for row in graph.protocol_scopes if row.profile is ProtocolProfile.CREATED_CLOSE_V1)
    annotation = next(row for row in graph.literal_evaluations
        if type(row.site) is OperationResult and any(value.id == details["none"]
            and value.origin == row.site for value in graph.values))
    identity = {
        "created_literal_class_is_current": created.PythonLiteral is literals.PythonLiteral,
        "created_literal_enum_is_current": created.LiteralKind is literals.LiteralKind,
        "annotation_exact_current_literal_class": type(annotation.literal) is literals.PythonLiteral,
        "annotation_none_kind_is_current": annotation.literal.kind is literals.LiteralKind.NONE,
        "annotation_none_python_content": annotation.literal.to_python() is None,
        "literal_module_file": str(Path(literals.__file__).resolve()),
    }
    index = ProgramIndex(graph)
    queries = []
    for budget in (4096, 65536):
        started = time.monotonic()
        view = index.protocol_obligations(scope.id, budget=budget)
        clause, = view["scopes"][0]["obligations"]
        original, = clause["original"]
        queries.append({
            "limit": budget, "duration_seconds": time.monotonic() - started,
            "declared_none_results": [row["declared_none_result"] for row in original["routes"]],
            "clause_status": clause["status"], "clause_gaps": clause["gaps"],
            "original_gaps": original["gaps"], "budget": view["budget"],
            "cursor": repr(view["cursor"]),
        })
    return {"seed": os.environ.get("PYTHONHASHSEED"), "identity": identity, "queries": queries}


if __name__ == "__main__":
    if sys.argv[1:] == ["--child"]:
        print(json.dumps(child(), sort_keys=True))
    elif not sys.argv[1:]:
        before = source_hashes()
        results = []
        for seed in range(8):
            environment = dict(os.environ, PYTHONHASHSEED=str(seed))
            command = [sys.executable, str(Path(__file__).resolve()), "--child"]
            started = time.monotonic()
            result = subprocess.run(command, env=environment, capture_output=True, text=True, timeout=20)
            results.append({"seed": seed, "command": command,
                "returncode": result.returncode, "duration_seconds": time.monotonic() - started,
                "stdout": result.stdout, "stderr": result.stderr,
                "parsed": json.loads(result.stdout) if result.returncode == 0 else None})
        after = source_hashes()
        print(json.dumps({"scope": "8 fresh processes; readonly canonical subquery, no pytest",
            "python": sys.version, "executable": sys.executable,
            "source_before": before, "source_after": after,
            "source_unchanged": before == after, "results": results}, indent=2, sort_keys=True))
    else:
        raise SystemExit("only --child or no arguments allowed")
