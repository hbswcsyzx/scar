"""Compare unchanged real source construction; not target performance or coverage."""
import argparse
import ast
import cProfile
import hashlib
import json
from pathlib import Path
import pstats
import resource
import time

from scar.analysis.program_lowering import prepare_source
from scar.ir.program.codec import dumps
from scar.ir.program.functions import BodyLoweringProfile
from scar.ir.record_codec import encode


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--sealed", action="store_true")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    profile = cProfile.Profile()
    started = time.perf_counter()
    context = profile.runcall(prepare_source, args.source, project_root=args.root)
    prepared_s = time.perf_counter() - started
    prepared_peak_rss_kib = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    seal_s = 0.0
    lowerer = context
    if args.sealed:
        started = time.perf_counter()
        lowerer = profile.runcall(context.seal_for_lowering)
        seal_s = time.perf_counter() - started
    sealed_peak_rss_kib = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    names = []

    def collect(statements, prefix=""):
        for node in statements:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                names.append(prefix + node.name)
            elif isinstance(node, ast.ClassDef):
                collect(node.body, prefix + node.name + ".")

    collect(context.tree.body)
    # Deterministic source-order cohort, fixed between variants.
    rows = []
    for entry in names[:6]:
        started = time.perf_counter()
        body = profile.runcall(lowerer.lower, entry, max_operations=100000,
                              expand_candidates=False, profile=BodyLoweringProfile.STRUCTURED_ENV)
        elapsed = time.perf_counter() - started
        document = dict(graph=json.loads(dumps(body.graph)) if body.graph else None,
                        metadata=encode(body.metadata), interface=encode(body.interface),
                        frame=encode(body.frame), structured=encode(body.structured),
                        operations_emitted=body.operations_emitted)
        canonical = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        row = dict(entry=entry, wall_s=elapsed,
                   status="LOWERED_WITH_GAPS" if body.graph else "UNSUPPORTED",
                   operations=body.operations_emitted,
                   canonical_sha256=hashlib.sha256(canonical.encode()).hexdigest())
        rows.append(row)
        print(json.dumps(row), flush=True)
    profile.dump_stats(args.out / "construction.pstats")
    with (args.out / "construction.txt").open("w") as stream:
        pstats.Stats(profile, stream=stream).sort_stats("cumulative").print_stats(45)
    result = dict(scope="Six real source bodies; instrumented SCAR construction only, not LeWM runtime or whole coverage",
                  source=str(args.source), source_sha256=hashlib.sha256(context.text.encode()).hexdigest(),
                  prepare_s=prepared_s, seal_s=seal_s, sealed=args.sealed,
                  prepared_peak_rss_kib=prepared_peak_rss_kib,
                  sealed_peak_rss_kib=sealed_peak_rss_kib,
                  lower_s=sum(row["wall_s"] for row in rows), bodies=rows,
                  max_operations_per_body=100000, target_executed=False,
                  validation_disabled=False, whole_program_graph_established=False)
    (args.out / "summary.json").write_text(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    main()
