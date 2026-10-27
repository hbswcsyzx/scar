"""One actual archived route/index query gate; no source or target replay."""
import argparse
import ast
from copy import deepcopy
import gzip
import hashlib
import json
from pathlib import Path
import resource
import sys
import time


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
EXPS = HERE.parent


def receipt(path):
    path = Path(path).resolve()
    hasher, size = hashlib.sha256(), 0
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1_048_576), b""):
            hasher.update(block); size += len(block)
    return {"path": str(path), "bytes": size, "sha256": hasher.hexdigest()}


def write(out, name, data):
    with (out / name).open("x") as stream:
        json.dump(data, stream, sort_keys=True, indent=2)
        stream.write("\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--coordinates", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    out = args.out.resolve(); out.mkdir(exist_ok=False)
    started = time.perf_counter()
    frozen = json.loads((EXPS / "first_stage_current_source_gate_20261023/frozen/producer.json").read_text())
    expected = {row["path"]: row for row in frozen["modules"]}
    new_source = REPO / "scar/analysis/call_endpoint_queries.py"
    ast.parse(new_source.read_bytes(), filename=str(new_source))
    expected[str(new_source)] = receipt(new_source)
    for name, declaration in expected.items():
        assert receipt(name) == declaration, name
    manifest = json.loads(args.report.read_bytes())
    header_path = Path(manifest["header"]["path"])
    assert receipt(header_path)["sha256"] == manifest["header"]["sha256"]
    with gzip.open(header_path, "rt") as stream:
        header = json.load(stream)
    scope = header["source_body_access"]
    inventory = Path(scope["inventory"]["path"])
    source_report = Path(scope["source_report"]["path"])
    source_bindings = Path(scope["source_bindings"]["path"])
    database = EXPS / "first_stage_graph_index_20261023/graph.attempt01.sqlite"
    db_receipt = receipt(database)
    assert db_receipt["sha256"] == "5e9a7461b68268a630cf926d59ecfb1e7e498549d8500534f7d309fa81a32fbe"
    coordinates = json.loads(args.coordinates.read_bytes())
    assert coordinates["run"] == scope["run"]
    write(out, "producer.json", {"script": receipt(Path(__file__)), "new_source": receipt(new_source),
        "expected_existing_producer": receipt(EXPS / "first_stage_current_source_gate_20261023/frozen/producer.json"),
        "inputs": [receipt(path) for path in (args.report, args.coordinates, inventory, source_report, source_bindings)]
                  + [db_receipt], "target_executed": False, "source_prepared": False, "code_compiled": False})

    from scar.analysis.call_endpoint_queries import CallEndpointQueries
    from scar.analysis.inventory_partitions import InventoryPartitions
    from scar.ir.execution.coordinates import ExecutionRun
    from scar.ir.record_codec import decode
    from scar.store.graph_index import GraphIndex

    run = decode(ExecutionRun, coordinates["run"])
    index = InventoryPartitions(inventory)
    examples, counts = {}, {}
    with GraphIndex(database) as graph:
        query = CallEndpointQueries(graph, index, args.report, expected_run=run,
            source_report=source_report, source_bindings=source_bindings)
        first = None
        for table, method in (("routing.argument_routes", query.argument),
                              ("routing.completion_routes", query.completion)):
            number = manifest["tables"][table]["rows"]
            for ordinal in range(number):
                answer = method(ordinal)
                assert answer["run"] == coordinates["run"]
                assert answer["conditions"] == answer["route"]["conditions"]
                assert answer["source_conditions"] == scope["source_producer_conditions"]
                assert answer["original_endpoint_membership_verified"] is True
                assert answer["world_equivalence_established"] is False
                assert answer["contents_or_alias_equivalence_established"] is False
                assert answer["transformation_authorized"] is False
                assert all(entity["qualified_reference"]["namespace"] in
                           [scope["namespaces"][answer["route"][name]["wire"]]["namespace"]
                            for name in ("caller_definition", "callee_definition")]
                           for entity in answer["endpoints"].values())
                if table not in examples:
                    examples[table] = answer
                if first is None:
                    first = answer
            counts[table] = number
        assert first is not None
        use = first["endpoints"]["caller_actual_use"]["qualified_reference"]
        assert graph.entity(use) == first["endpoints"]["caller_actual_use"]
        negatives = []

        def rejects(label, callback):
            try:
                callback()
            except (ValueError, TypeError) as error:
                negatives.append({"case": label, "error": str(error)})
            else:
                raise AssertionError("invalid endpoint accepted: " + label)

        rejects("bare_local_id", lambda: query.endpoint({"kind": "Use", "local_id": use["local_id"]}))
        wrong = deepcopy(use); wrong["namespace"]["artifact"]["decoded_sha256"] = "0" * 64
        rejects("foreign_namespace", lambda: query.endpoint(wrong))
        wrong_kind = deepcopy(use); wrong_kind["kind"] = "Value"
        rejects("wrong_endpoint_kind", lambda: query.endpoint(wrong_kind))
        foreign_run = deepcopy(coordinates["run"])
        foreign_run["id"]["value"] += ":foreign"
        foreign_run["id"]["wire"] += ":foreign"
        rejects("different_Run", lambda: CallEndpointQueries(graph, index, args.report,
            expected_run=decode(ExecutionRun, foreign_run), source_report=source_report, source_bindings=source_bindings))
        write(out, "queries.json", examples)
        write(out, "rejections.json", negatives)
    imported = []
    for module in tuple(sys.modules.values()):
        name = getattr(module, "__file__", None)
        if name is None:
            continue
        path = Path(name).resolve()
        if path.is_relative_to(REPO / "scar") and path.suffix == ".py":
            actual = receipt(path)
            assert str(path) in expected and actual == expected[str(path)], str(path)
            imported.append(actual)
    write(out, "imported-producer.json", imported)
    summary = {"status": "QUALIFIED_ENDPOINT_QUERY_PASS", "run": coordinates["run"], "checked_routes": counts,
        "negative_queries": len(negatives), "elapsed_s": time.perf_counter() - started,
        "maxrss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "target_executed": False, "source_prepared": False, "code_compiled": False,
        "source_and_runtime_proofs_replayed": False, "world_equivalence_established": False,
        "original_producers_rewritten": False, "whole_program_established": False,
        "transformation_authorized": False}
    write(out, "summary.json", summary)
    print(json.dumps(summary, sort_keys=True))


if __name__ == "__main__":
    main()
