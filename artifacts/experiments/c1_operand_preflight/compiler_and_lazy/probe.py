"""Offline compile-context audit; only an embedded tiny fixture executes."""
import __future__
import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tokenize
from types import CodeType

from scar.ir.program.call_edges import CapturedCode
from scar.ir.record_codec import decode, encode, loads
from scar.trace.code_snapshot import describe_code


def require(condition, detail):
    if not condition:
        raise ValueError(detail)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def positive(value):
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("limit must be positive")
    return number


def nested(code, *, max_nodes, max_depth):
    pending, count = [(code, 0)], 0
    while pending:
        item, depth = pending.pop()
        count += 1
        require(count <= max_nodes and depth <= max_depth, "nested code traversal budget exceeded")
        yield item
        pending.extend((value, depth + 1) for value in reversed(item.co_consts) if type(value) is CodeType)


def fixture(mask):
    """Observe a fixed child exec inheriting its parent's future annotations."""
    text = "def identity(value: object) -> object:\n    return value\n"
    filename = str(Path(__file__).with_name("embedded-child.py"))
    parent = compile("from __future__ import annotations\n"
                     "child_code = compile(child_source, child_filename, 'exec')\n"
                     "exec(child_code, child_globals)\n",
                     str(Path(__file__).with_name("embedded-parent.py")), "exec", dont_inherit=True)
    observed = []
    def profile(frame, event, argument):
        if event == "call" and frame.f_code.co_filename == filename:
            observed.append(frame.f_code)
    previous = sys.getprofile()
    sys.setprofile(profile)
    try:
        exec(parent, {"child_source": text, "child_filename": filename, "child_globals": {}})
    finally:
        sys.setprofile(previous)
    require(len(observed) == 1, "fixture needs exactly one real child module entry")
    captured = describe_code(observed[0])
    inherited_flags = captured["flags"] & mask
    ordinary = compile(text, filename, "exec", flags=0, dont_inherit=True, optimize=0)
    reconstructed = compile(text, filename, "exec", flags=inherited_flags, dont_inherit=True, optimize=0)
    ordinary_description, reconstructed_description = describe_code(ordinary), describe_code(reconstructed)
    require(captured != ordinary_description and captured == reconstructed_description,
            "future inheritance fixture did not reproduce exact code")
    inherited_children = [describe_code(code) for code in nested(observed[0], max_nodes=32, max_depth=16)]
    reproduced_children = [describe_code(code) for code in nested(reconstructed, max_nodes=32, max_depth=16)]
    require(inherited_children == reproduced_children, "fixture nested complete descriptors differ")
    return {"fixed_fixture_only_executed": True, "application_executed": False,
            "source_sha256": sha(text.encode()), "parent_flags": parent.co_flags,
            "captured": captured, "ordinary": ordinary_description,
            "reconstructed": reconstructed_description,
            "inferred_future_flags": inherited_flags, "nested_complete_descriptors": inherited_children,
            "ordinary_full_match": False, "inferred_full_match": True,
            "inferred_nested_full_matches": len(inherited_children)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--max-report-bytes", type=positive, default=16_000_000)
    parser.add_argument("--max-source-bytes", type=positive, default=4_000_000)
    parser.add_argument("--max-source-files", type=positive, default=16)
    parser.add_argument("--max-compile-attempts", type=positive, default=32)
    parser.add_argument("--max-nested-codes", type=positive, default=10_000)
    parser.add_argument("--max-code-depth", type=positive, default=128)
    args = parser.parse_args()
    limits = {key: value for key, value in vars(args).items() if key.startswith("max_")}
    opener = gzip.open if args.report.suffix == ".gz" else open
    with opener(args.report, "rb") as stream:
        raw = stream.read(args.max_report_bytes + 1)
    require(len(raw) <= args.max_report_bytes, "report decompressed byte budget exceeded")
    report = loads(raw)
    require(report["schema"] == "scar.call-source-seeds" and report["schema_version"] == 1,
            "expected frozen D0 source-seed report v1")
    model = report["model"]
    root = Path(model["project_root"])
    captures = {(capture["process_id"], capture["code"]["key"]):
                encode(decode(CapturedCode, capture["code"])) for capture in model["codes"]}
    mismatches = {link["code"]: link for link in model["code_links"] if link["status"] == "MISMATCH"}
    groups = [group for group in model["groups"] if group["code"] in mismatches]
    features = {name: getattr(__future__, name).compiler_flag for name in __future__.all_feature_names}
    mask = 0
    for value in features.values():
        mask |= value
    sources, cache, rows = {}, {}, []
    source_bytes, attempts, hits, described = 0, 0, 0, 0
    for group in groups:
        key = group["process_id"], group["code"]
        require(key in captures, "MISMATCH group has no descriptor in its own process")
        captured = captures[key]
        path = Path(captured["filename"])
        require(path.is_absolute() and path == path.resolve() and path.is_relative_to(root),
                "mismatch source is noncanonical or outside frozen project boundary")
        link = mismatches[group["code"]]
        if str(path) not in sources:
            require(len(sources) < args.max_source_files, "source file budget exceeded")
            remaining = args.max_source_bytes - source_bytes
            with path.open("rb") as stream:
                source_raw = stream.read(remaining + 1)
            require(len(source_raw) <= remaining, "source byte budget exceeded")
            source_bytes += len(source_raw)
            encoding, _ = tokenize.detect_encoding(io.BytesIO(source_raw).readline)
            text = io.TextIOWrapper(io.BytesIO(source_raw), encoding=encoding).read()
            fingerprint = "sha256:" + sha(text.encode())
            sources[str(path)] = {"path": str(path), "raw_sha256": sha(source_raw),
                                  "fingerprint": fingerprint, "raw_bytes": len(source_raw),
                                  "encoding": encoding, "text": text}
        source = sources[str(path)]
        require(link["snapshot"]["path"] == str(path)
                and link["snapshot"]["fingerprint"] == source["fingerprint"],
                "current source drifted from frozen mismatch snapshot")
        inferred = captured["flags"] & mask
        trials = []
        for strategy, flags in (("legacy_zero_flags", 0), ("inferred_future_flags", inferred)):
            for optimize in (0, 1, 2):
                cache_key = (str(path), source["fingerprint"], flags, optimize, sys.version)
                cached = cache_key in cache
                if cached:
                    hits += 1
                else:
                    require(attempts < args.max_compile_attempts, "compile attempt budget exceeded")
                    attempts += 1
                    compiled = compile(source["text"], captured["filename"], "exec", flags=flags,
                                       dont_inherit=True, optimize=optimize)
                    descriptions = [describe_code(code) for code in nested(
                        compiled, max_nodes=args.max_nested_codes, max_depth=args.max_code_depth)]
                    described += len(descriptions)
                    cache[cache_key] = descriptions
                descriptions = cache[cache_key]
                exact = [description for description in descriptions if description == captured]
                trials.append({"strategy": strategy, "flags": flags, "flags_hex": hex(flags),
                               "optimize": optimize, "cache_hit": cached,
                               "nested_descriptors": len(descriptions),
                               "full_match_count": len(exact), "full_matches": exact})
        rows.append({"group": group, "captured": captured, "inferred_future_flags": inferred,
                     "enabled_future_features": [name for name, flag in features.items() if flag and inferred & flag],
                     "snapshot_current_hash_equal": True, "trials": trials})
    checks = {strategy: sum(any(trial["strategy"] == strategy and trial["full_match_count"]
                               for trial in row["trials"]) for row in rows)
              for strategy in ("legacy_zero_flags", "inferred_future_flags")}
    result = {"schema": "scar.experiment.compile-context-audit", "schema_version": 1,
              "python": sys.version, "python_executable": sys.executable,
              "frozen_worktree_head": subprocess.run(["git", "rev-parse", "HEAD"], check=True,
                                                      text=True, capture_output=True).stdout.strip(),
              "input_report": {"path": str(args.report), "file_sha256": sha(args.report.read_bytes()),
                               "decompressed_sha256": sha(raw), "decompressed_bytes": len(raw)},
              "probe_sha256": sha(Path(__file__).read_bytes()), "limits": limits,
              "future_features": features, "future_mask": mask, "future_mask_hex": hex(mask),
              "source_files": [{key: value for key, value in source.items() if key != "text"}
                               for source in sources.values()],
              "measurements": {"mismatch_groups": len(rows), "unique_source_files": len(sources),
                               "source_bytes": source_bytes, "compile_attempts": attempts,
                               "compile_cache_hits": hits, "described_codes": described,
                               "groups_with_full_match": checks},
              "groups": rows, "fixture": fixture(mask),
              "matching_rule": "Every six-field describe_code dict is compared for complete equality, including structural pycode-v2 key; qualname/line do not select or repair a match.",
              "application_executed": False, "current_resolver_or_report_modified": False,
              "inference_boundary": "Recovered future flags reproduce code. This does not prove which historical loader/parent supplied them, nor establish function environment or execution/effects."}
    args.out.write_text(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"out": str(args.out), "measurements": result["measurements"],
                      "fixture_full_match": result["fixture"]["inferred_full_match"]}))


if __name__ == "__main__":
    main()
