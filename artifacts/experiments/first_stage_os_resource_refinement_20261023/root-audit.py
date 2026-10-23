"""Independent stdlib check of the real sparse delta and selected original rows."""
from collections import defaultdict
import gzip
import hashlib
import io
import json
from pathlib import Path
import resource
import time


HERE = Path(__file__).resolve().parent
R1 = HERE.parent / "first_stage_os_interface_work_20261023/result/interfaces/manifest.json"
DELTA = HERE / "gate-attempt01/result/manifest.json"
START = time.perf_counter()


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def key(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


base_raw, delta_raw = R1.read_bytes(), DELTA.read_bytes()
assert digest(base_raw) == "cbc6dcfd78ccca0961bdabecce94bc747b7b281fdbc3f49228c8b52b9b3aec14"
assert digest(delta_raw) == "6b5e1ae12e2c05364c76364cf1b1cf7859d2f6ddb09380c8940a3980381bde5c"
base, delta = json.loads(base_raw), json.loads(delta_raw)
assert delta["base"] == {"uri": str(R1), "sha256": digest(base_raw),
                         "size_bytes": len(base_raw), "schema": base["schema"]}
assert delta["run"] == base["run"]
for name in ("complete_execution_model", "program_snapshot_created", "whole_model_established",
             "first_stage_complete", "transformation_authorized"):
    assert delta[name] is False
selectors, preimages = {}, []
for rows in delta["base_references"].values():
    preimages.extend(rows)
preimages.extend(row["preimage"] for row in delta["handle_refinements"])
preimages.extend(row["preimage"] for row in delta["executor_refinements"])
for reference in preimages:
    selectors[key(reference["selector"])] = reference["selector"]
for access in delta["provider_accesses"]:
    selectors[key(access["selector"])] = access["selector"]
for change in delta["handle_refinements"]:
    selector = change["replacement"]["handle"]["selector"]
    selectors[key(selector)] = selector
demands = defaultdict(lambda: defaultdict(list))
for identity, selector in selectors.items():
    assert selector["chunk"]["artifact"] == delta["base"]
    table = selector["table"]
    prefix = "#/tables/" + table + "/chunks/"
    locator = selector["chunk"]["locator"]
    assert locator.startswith(prefix)
    number = int(locator[len(prefix):])
    chunk = base["tables"][table]["chunks"][number]
    assert selector["ordinal"] == chunk["first_ordinal"] + selector["line"] - 1
    assert chunk["first_ordinal"] <= selector["ordinal"] <= chunk["last_ordinal"]
    demands[table, number][selector["line"]].append((identity, selector))
resolved, receipts = {}, []
for (table, number), wanted in demands.items():
    chunk = base["tables"][table]["chunks"][number]
    path = (R1.parent / chunk["uri"]).resolve()
    assert path.is_relative_to(R1.parent) and not path.is_symlink()
    physical = path.read_bytes()
    assert len(physical) == chunk["physical_bytes"] and digest(physical) == chunk["physical_sha256"]
    raw = gzip.decompress(physical)
    assert len(raw) == chunk["decoded_bytes"] and digest(raw) == chunk["decoded_sha256"]
    assert raw.count(b"\n") == chunk["lines"]
    for line, payload in enumerate(io.BytesIO(raw), 1):
        if line not in wanted:
            continue
        envelope = json.loads(payload)
        for identity, selector in wanted[line]:
            assert envelope["ordinal"] == selector["ordinal"]
            selected = envelope
            for token in selector["pointer_within_line"].split("/")[1:]:
                token = token.replace("~1", "/").replace("~0", "~")
                selected = selected[int(token)] if type(selected) is list else selected[token]
            resolved[identity] = {"value": selected, "record": envelope["record"],
                                  "row_sha256": digest(payload)}
    receipts.append({"table": table, "number": number, "physical_sha256": digest(physical),
                     "decoded_sha256": digest(raw), "selected_lines": len(wanted)})
assert len(resolved) == len(selectors)
for reference in preimages:
    row = resolved[key(reference["selector"])]
    assert row["value"]["id"] == reference["id"] and row["row_sha256"] == reference["row_sha256"]


def originals(table):
    return {row["id"]["wire"]: resolved[key(row["selector"])]["record"]
            for row in delta["base_references"][table]}


work, targets, threads = originals("submissions"), originals("resources"), originals("threads")
handles, lifetimes, pipes = {}, set(), defaultdict(list)
for change in delta["handle_refinements"]:
    previous = resolved[key(change["preimage"]["selector"])]["record"]
    replacement = change["replacement"]
    assert {k: v for k, v in previous.items() if k != "handle"} == {k: v for k, v in replacement.items() if k != "handle"}
    endpoint = replacement["handle"]
    assert endpoint["lifetime"]["wire"] not in lifetimes
    lifetimes.add(endpoint["lifetime"]["wire"])
    assert set(endpoint["container"]) == {"reason", "point"}
    assert endpoint["container"]["point"] == previous["start"]
    selected = resolved[key(endpoint["selector"])]
    assert type(selected["value"]) is int and selected["value"] >= 0
    port_index = int(endpoint["selector"]["pointer_within_line"].split("/")[-2])
    port = selected["record"]["created_handles"][port_index]
    assert port["binding"] == previous["id"]["wire"] and port["target"] == previous["target"]["instance"]["wire"]
    assert port["fd"] == selected["value"] and port["target"] in targets
    handles[previous["id"]["wire"]] = replacement
    if selected["record"]["syscall"] == "pipe2":
        pipes[selected["record"]["work_ticket"]].append((port["fd"], port["target"], endpoint["lifetime"]["wire"]))
outputs, executors, producers = set(), {}, set()
for access in delta["provider_accesses"]:
    origin = work[access["work"]["wire"]]["origin"]
    row = resolved[key(access["selector"])]["record"]
    assert row["work_ticket"] == access["work"]["value"]
    assert access["point"]["run"] == delta["run"]["id"]
    assert access["point"]["process"] == origin["point"]["process"]
    if access["purpose"] == "OUTPUT_SELECTOR":
        handle = handles[access["handle"]["binding"]["wire"]]
        assert access["target"] == handle["target"] and access["point"] == handle["start"]
        assert access["source"] == handle["source"] and access["selector"] == handle["handle"]["selector"]
        outputs.add(handle["id"]["wire"])
        producers.add(access["work"]["wire"])
    else:
        assert access["purpose"] == "EXECUTOR"
        ticket = work[access["work"]["wire"]]
        thread = threads[access["target"]["thread"]["wire"]]
        assert ticket["scheduling"]["thread"] == thread["id"] and thread["tid"] == row["tid"]
        assert thread["process"] == access["point"]["process"]
        executors[access["id"]["wire"]] = access
for change in delta["executor_refinements"]:
    previous = resolved[key(change["preimage"]["selector"])]["record"]
    assert executors[change["executor"]["wire"]]["work"] == previous["id"]
assert len(handles) == len(outputs) == len(lifetimes) == 35 and len(producers) == 22
assert len(executors) == len(delta["executor_refinements"]) == 3 and len(pipes) == 13
assert all(len(pair) == 2 and all(left != right for left, right in zip(pair[0], pair[1])) for pair in pipes.values())
report = {"status": "SELECTED_ORIGINAL_ENDPOINT_AUDIT_PASS", "ports": 35, "producer_work": 22,
    "pipe_pairs": 13, "executors": 3, "selectors": len(selectors), "chunk_receipts": receipts,
    "base_manifest_sha256": digest(base_raw), "delta_sha256": digest(delta_raw),
    "elapsed_s": time.perf_counter() - START, "maxrss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
    "scar_imported": False, "whole_observation_table_rescanned": False, "full_model_semantics_checked": False,
    "whole_model_established": False, "target_executed": False, "transformation_authorized": False}
with (HERE / "root-endpoint-audit.json").open("x") as out:
    json.dump(report, out, sort_keys=True, indent=2)
    out.write("\n")
print(json.dumps({name: value for name, value in report.items() if name != "chunk_receipts"}, sort_keys=True))
