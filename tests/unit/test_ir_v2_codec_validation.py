"""Malformed persisted IR must fail before information is lost or trusted."""
from copy import deepcopy
import json
import subprocess
import sys

import pytest

import scar.ir.v2 as ir
from scar.ir.v2.codec import (
    correspondence_from_dict,
    evidence_from_dict,
    semantic_from_dict,
    values_from_dict,
)


def _document():
    semantic, evidence, values = ir.SemanticGraph(), ir.EvidenceGraph(), ir.ValueGraph()
    package, module = ir.PackageID("project"), ir.ModuleID("program")
    source = ir.SourceAtomID("source")
    operation, instance = ir.OperationDefinitionID("step"), ir.OperationInstanceID("call")
    slot, control = ir.ValueSlotID("output"), ir.ControlRegionID("scope")
    effect, contract, resource = ir.EffectSummaryID("effects"), ir.ContractID("exact"), ir.ResourceID("cpu")
    semantic.packages[package] = ir.PackageDefinition(package, "project")
    semantic.modules[module] = ir.ModuleDefinition(module, "program", package)
    semantic.source_atoms[source] = ir.SourceAtom(source, ir.SourceReference(
        source, "/project/program.py", "sha256:source", 1, 1), "call")
    semantic.controls[control] = ir.ControlRegion(control, "function")
    semantic.effects[effect] = ir.EffectSummary(effect)
    semantic.contracts[contract] = ir.ContractDefinition(contract, "exact")
    semantic.resources[resource] = ir.ResourceRequirement(resource, ir.ResourceKind.CPU, "process")
    semantic.definitions[operation] = ir.OperationDefinition(
        operation, ir.OperationKind.FUNCTION, "step", output_slots=(slot,))
    semantic.slots[slot] = ir.ValueSlot(slot, "output", "output", owner=operation)
    claim = ir.EvidenceClaim(ir.EvidenceKind.OBSERVED, ("trace:1",))
    semantic.edges["source"] = ir.SemanticEdge(
        "source", ir.SemanticRelation.HAS_SOURCE,
        ir.SemanticEndpoint(ir.SemanticNodeKind.OPERATION, operation),
        ir.SemanticEndpoint(ir.SemanticNodeKind.SOURCE_ATOM, source), claim)

    logical = ir.LogicalValueID("value")
    version = ir.ValueVersionID(logical, 0)
    allocation, region = ir.StorageAllocationID("allocation"), ir.StorageRegionID("view")
    materialization, provenance = ir.MaterializationID("cpu"), ir.ProvenanceID("origin")
    values.logical_values[logical] = ir.LogicalValue(logical, "tensor")
    values.versions[version] = ir.ValueVersion(version, provenance_id=provenance)
    values.provenance[provenance] = ir.ProvenanceRecord(
        provenance, ir.ProvenanceRelation.ORIGIN, (), (version,), producer=instance)
    values.allocations[allocation] = ir.StorageAllocation(allocation, "cpu", nbytes=4)
    values.regions[region] = ir.StorageRegion(region, allocation, 0, (1,), (1,), "float32", "cpu")
    values.materializations[materialization] = ir.Materialization(
        materialization, version, "tensor", "cpu", region=region, producer=instance)
    values.bindings.append(ir.ObjectBinding(ir.ObjectID("tensor"), version))

    evidence.instances[instance] = ir.OperationInstance(instance, operation, 1, 1)
    evidence.observations["output"] = ir.ValueObservation(
        "output", version, instance, materialization, "output")
    measurement = ir.MeasurementID("latency")
    evidence.measurements[measurement] = ir.MeasurementRecord(
        measurement, "wall_clock", 10.0, "ns", instance.wire)
    evidence.control_events.add("entry")
    evidence.external_references.add((ir.EvidenceNodeKind.VALUE_VERSION, version.wire))
    evidence.edges["produces"] = ir.EvidenceEdge(
        "produces", ir.EvidenceRelation.PRODUCES,
        ir.EvidenceEndpoint(ir.EvidenceNodeKind.OPERATION_INSTANCE, instance),
        ir.EvidenceEndpoint(ir.EvidenceNodeKind.VALUE_OBSERVATION, "output"), claim)

    correspondence = ir.CorrespondenceGraph()
    correspondence.add(ir.CorrespondenceRecord(
        ir.CorrespondenceID("call"), ir.CorrespondenceKind.DEFINITION_INSTANCE,
        definition=operation, instance=instance, evidence=claim))
    optimization = ir.OptimizationGraph(ir.optimization_context(semantic, evidence, values))
    optimization.add_port(ir.RegionPort(
        "output", ir.RegionPortKind.OUTPUT, "output", value=ir.ValuePattern(versions=(version,))))
    optimization_region = ir.OptimizationRegionID("region")
    optimization.add_region(ir.OptimizationRegion(
        optimization_region, ir.RegionGranularity.FUNCTION, "step",
        definitions=(operation,), ports=("output",)))
    original = ir.PlanAlternativeID("original")
    optimization.add_alternative(ir.PlanAlternative(
        original, optimization_region, "original", ir.TransformKind.NO_OP, original=True))
    optimization.add_plan(ir.PlanSelection(
        ir.PlanID("keep"), optimization_region, ir.PlanDisposition.KEEP,
        selected=original, reason="original execution"))
    return ir.IRBundle(semantic, evidence, values, correspondence, optimization).to_dict()


def test_complete_bundle_round_trip_preserves_all_graph_collections():
    document = _document()
    encoded = ir.canonical_json(document)
    assert ir.canonical_json(ir.IRBundle.from_json(encoded)) == encoded


@pytest.mark.parametrize("graph", (None, "semantic", "evidence", "values", "correspondence", "optimization"))
@pytest.mark.parametrize("version", (None, True, "1", 99))
def test_unsupported_or_missing_schema_version_is_rejected(graph, version):
    document = _document()
    target = document if graph is None else document[graph]
    if version is None:
        del target["schema_version"]
    else:
        target["schema_version"] = version
    with pytest.raises(ValueError, match="schema_version"):
        ir.IRBundle.from_dict(document)


@pytest.mark.parametrize(("graph", "collection"), [
    (graph, collection)
    for graph, collections in {
        "semantic": ("packages", "modules", "source_atoms", "controls", "effects",
                     "resources", "contracts", "definitions", "slots", "edges"),
        "evidence": ("instances", "observations", "measurements", "edges"),
        "values": ("logical_values", "versions", "provenance", "allocations",
                   "regions", "materializations"),
        "correspondence": ("records",),
        "optimization": ("ports", "regions", "alternatives", "plans"),
    }.items()
    for collection in collections
])
def test_duplicate_record_ids_are_not_silently_overwritten(graph, collection):
    document = _document()
    records = document[graph][collection]
    records.append(deepcopy(records[0]))
    with pytest.raises(ValueError, match="duplicate"):
        ir.IRBundle.from_dict(document)


@pytest.mark.parametrize("replacement", (None, {}, [], "opdef:step", {"kind": "opdef"}))
def test_malformed_required_identifier_is_rejected(replacement):
    document = _document()
    document["semantic"]["definitions"][0]["id"] = replacement
    with pytest.raises(ValueError):
        ir.IRBundle.from_dict(document)


@pytest.mark.parametrize("field,replacement", (("kind", "lv"), ("wire", "opdef:other"), ("value", 3)))
def test_identifier_namespace_and_wire_are_checked(field, replacement):
    document = _document()
    document["semantic"]["definitions"][0]["id"][field] = replacement
    with pytest.raises(ValueError):
        ir.IRBundle.from_dict(document)


@pytest.mark.parametrize("version", (True, 0.0, "0"))
def test_version_is_an_integer_not_a_coercible_value(version):
    document = _document()
    document["values"]["versions"][0]["id"].update(version=version, wire=f"lv:value@v{version}")
    with pytest.raises(ValueError):
        ir.IRBundle.from_dict(document)


@pytest.mark.parametrize("replacement", (None, {}, "output"))
def test_collection_requires_an_array(replacement):
    document = _document()
    document["evidence"]["observations"] = replacement
    with pytest.raises(ValueError, match="expected array"):
        ir.IRBundle.from_dict(document)


@pytest.mark.parametrize("field,replacement", (
    ("instrumented", "false"), ("samples", True), ("value", "10.0"),
))
def test_measurement_field_types_are_not_coerced(field, replacement):
    document = _document()
    document["evidence"]["measurements"][0][field] = replacement
    with pytest.raises(ValueError):
        ir.IRBundle.from_dict(document)


def test_string_evidence_references_are_not_split_into_characters():
    document = _document()
    document["semantic"]["edges"][0]["evidence"]["references"] = "trace:1"
    with pytest.raises(ValueError, match="expected array"):
        ir.IRBundle.from_dict(document)


@pytest.mark.parametrize("field", ("cost_request", "validation_request"))
def test_empty_optional_record_is_not_silently_removed(field):
    document = _document()
    document["optimization"]["alternatives"][0][field] = {}
    with pytest.raises(ValueError):
        ir.IRBundle.from_dict(document)


def test_unknown_stable_fields_are_not_silently_dropped():
    document = _document()
    document["semantic"]["definitions"][0]["effect_summmary"] = "misspelled"
    with pytest.raises(ValueError, match="unknown fields"):
        ir.IRBundle.from_dict(document)


@pytest.mark.parametrize("value", (float("nan"), float("inf"), float("-inf")))
def test_nonfinite_numbers_are_rejected_from_dict_and_json(value):
    document = _document()
    document["semantic"]["definitions"][0]["metadata"] = {"measurement": value}
    with pytest.raises(ValueError, match="non-finite"):
        ir.IRBundle.from_dict(document)
    with pytest.raises(ValueError, match="non-finite"):
        ir.IRBundle.from_json(json.dumps(document))


def test_numeric_overflow_in_json_is_rejected():
    encoded = json.dumps(_document()).replace('"value": 10.0', '"value": 1e999')
    with pytest.raises(ValueError, match="non-finite"):
        ir.IRBundle.from_json(encoded)


def test_duplicate_json_object_keys_are_rejected_at_any_depth():
    encoded = ir.canonical_json(_document())
    for malformed in (
        '{"schema":"ignored",' + encoded[1:],
        encoded.replace('"label":"step"', '"label":"ignored","label":"step"', 1),
    ):
        with pytest.raises(ValueError, match="duplicate JSON object key"):
            ir.IRBundle.from_json(malformed)


@pytest.mark.parametrize("collection", ("control_events", "external_references"))
def test_duplicate_set_members_are_not_silently_collapsed(collection):
    document = _document()
    document["evidence"][collection].append(deepcopy(document["evidence"][collection][0]))
    with pytest.raises(ValueError, match="duplicate|unique"):
        ir.IRBundle.from_dict(document)


@pytest.mark.parametrize("decoder", (semantic_from_dict, evidence_from_dict,
                                     values_from_dict, correspondence_from_dict))
def test_standalone_decoders_reject_nonobjects_with_valueerror(decoder):
    with pytest.raises(ValueError):
        decoder([])


def test_cached_validation_cannot_bypass_reference_validation():
    document = _document()
    document["evidence"]["instances"][0]["definition"] = ir.OperationDefinitionID("missing").as_dict()
    document["validation"] = {"valid": True, "errors": []}
    with pytest.raises(ValueError, match="unknown definition"):
        ir.IRBundle.from_dict(document)


def test_required_identifier_checks_survive_python_optimization():
    document = _document()
    document["values"]["versions"][0]["id"] = None
    script = (
        "import sys\nfrom scar.ir.v2 import IRBundle\n"
        "try:\n IRBundle.from_json(sys.stdin.read())\n"
        "except ValueError:\n sys.exit(0)\n"
        "sys.exit(1)\n"
    )
    result = subprocess.run([sys.executable, "-O", "-c", script],
                            input=json.dumps(document), text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
