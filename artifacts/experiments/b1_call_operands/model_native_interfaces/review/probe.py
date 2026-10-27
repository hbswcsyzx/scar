"""One bounded IR-only integration review; no Torch, workload or test suite."""
from dataclasses import replace
import json
from pathlib import Path
import sys

from scar.ir.program.codec import dumps, loads
from scar.ir.program.ids import ValueID
from scar.ir.program.native import CoreInputPort, ExitPortRef
from scar.ir.program.providers import ProviderArtifact, ProviderFactReference
from scar.ir.program.queries import ProgramIndex
from scar.ir.program.validation import validate
from tests.fixtures.program_graphs import shared_body_calls_program
from tests.fixtures.program_native_graphs import native_boundary_graph


results = {"python": sys.version, "runs": 1, "cases": []}


def run(name, function):
    row = {"case": name}
    try:
        row.update(function())
    except Exception as error:
        row.update(status="UNEXPECTED_FAILURE", error_type=type(error).__name__, error=str(error))
    results["cases"].append(row)


def legacy_exact_control():
    graph = shared_body_calls_program()
    assert not validate(graph)
    index = ProgramIndex(graph)
    return {"status": "PASS", "schema": json.loads(dumps(graph))["schema_version"],
            "native_count": len(graph.native_boundaries),
            "callee_exit_uses": len(index.exit_port_uses(ExitPortRef(graph.regions[-1].id, "normal", 0)))}


def valid_legacy_identifier_subclass():
    class DerivedValueID(ValueID):
        pass

    graph = shared_body_calls_program()
    old, new = ValueID("caller.input"), DerivedValueID("caller.input")
    graph = replace(graph, values=tuple(replace(value, id=new) if value.id == old else value
                                        for value in graph.values),
                    regions=tuple(replace(region, blocks=tuple(replace(
                        block, arguments=tuple(new if value == old else value for value in block.arguments))
                        for block in region.blocks)) for region in graph.regions),
                    operations=tuple(replace(operation, uses=tuple(
                        replace(use, value=new) if use.value == old else use for use in operation.uses))
                        for operation in graph.operations))
    issues = validate(graph)
    assert not issues, issues
    row = {"validation_codes": [issue.code for issue in issues],
           "schema": json.loads(dumps(graph))["schema_version"],
           "native_count": len(graph.native_boundaries)}
    try:
        ProgramIndex(graph)
    except Exception as error:
        row.update(status="REGRESSION", error_type=type(error).__name__, error=str(error))
    else:
        row["status"] = "PASS"
    return row


def native_multi_return_and_auxiliary_artifact():
    graph = native_boundary_graph()
    native = graph.native_boundaries[-1]
    auxiliary = ProviderFactReference(ProviderArtifact(
        "unopened://auxiliary-signature", "c" * 64, 0, "auxiliary-test"), "/declaration")
    changed = replace(native, signature=auxiliary, input_tree=auxiliary)
    graph = replace(graph, native_boundaries=(*graph.native_boundaries[:-1], changed))
    assert not validate(graph)
    assert loads(dumps(graph)) == graph
    outputs = ProgramIndex(graph).native_output_uses(changed.id)
    assert [len(row) for row in outputs] == [2, 2, 1]
    assert all(left.use.id != right.use.id and left.use.value == right.use.value
               for left, right in zip(outputs[0], outputs[1]))
    return {"status": "PASS", "output_site_counts": [len(row) for row in outputs],
            "auxiliary_artifact_accepted_without_open": True}


def overlapping_native_core_partition():
    graph = native_boundary_graph()
    native = graph.native_boundaries[-1]
    changed = replace(native, core_inputs=(CoreInputPort(native.inputs[0].port, "deliberate overlap"),))
    graph = replace(graph, native_boundaries=(*graph.native_boundaries[:-1], changed))
    codes = [issue.code for issue in validate(graph)]
    assert "native_port_duplicate" in codes and "native_port_partition" in codes
    try:
        dumps(graph)
    except ValueError:
        pass
    else:
        raise AssertionError("codec accepted overlapping partition")
    return {"status": "PASS", "rejected_codes": codes}


def tampered_nested_record_hits_integration_validation():
    graph = native_boundary_graph()
    object.__setattr__(graph.native_boundaries[-1].outputs[0].port, "index", False)
    codes = [issue.code for issue in validate(graph)]
    assert codes and set(codes) == {"schema"}
    try:
        dumps(graph)
    except ValueError:
        pass
    else:
        raise AssertionError("codec accepted tampered nested record")
    return {"status": "PASS", "rejected_codes": codes}


run("exact-ID legacy control", legacy_exact_control)
run("validator-valid legacy ID subtype", valid_legacy_identifier_subclass)
run("multi-return/repeated-value outputs plus auxiliary artifact", native_multi_return_and_auxiliary_artifact)
run("overlapping native/core partition", overlapping_native_core_partition)
run("private nested bool-index tampering", tampered_nested_record_hits_integration_validation)
results["torch_imported"] = "torch" in sys.modules
Path(__file__).with_name("results.json").write_text(json.dumps(results, indent=2) + "\n")
print(json.dumps(results, indent=2))
