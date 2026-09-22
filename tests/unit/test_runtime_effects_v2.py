"""Runtime ingestion cannot manufacture purity, identity, or independent cost."""
import scar.ir.v2 as ir
from scar.analysis.effects_v2 import ClosureState, EffectClosureEngine, EffectDimension, ScopeMode
from scar.analysis.runtime_effects_v2 import ingest_runtime_effects
from scar.trace.normalize_v2 import normalize_records


def event(kind, index, invocation=None, *, effect=None, inputs=(), outputs=(),
          resource=None, code=None, **metadata):
    return {"kind": kind, "index": index, "ts_ns": index * 100,
            "duration_ns": 10, "invocation_id": invocation, "code_id": code or f"function:{invocation}",
            "inputs": list(inputs), "outputs": list(outputs), "effect": effect or {},
            "resource": resource or {}, "labels": [],
            "metadata": {"process_id": 1, "thread_id": 2, "clock_domain": "perf_counter", **metadata}}


def normalized(records):
    return normalize_records(records, source="fixture.jsonl").bundle


def boundary(result, definition=None):
    engine = result.engine
    if definition is None:
        definition = next(iter(engine.semantic.definitions))
    scope = next(scope for owner, scope in engine.operations if owner == definition)
    return engine.boundary((definition,), scope)


def test_entry_reads_and_return_escapes_keep_separate_evidence_with_unknown_scalars():
    bundle = normalized([
        event("python_call", 0, 1, effect={"reads": ["same-token"]}),
        event("python_return", 1, 1, effect={"escapes": ["same-token"],
              "collection_knowledge": {"escapes": "KNOWN"}}, outcome="return"),
    ])
    result = ingest_runtime_effects(bundle)
    facts = list(result.engine.occurrences.values())
    read = next(item for item in facts if item.dimension is EffectDimension.READS)
    escaped = next(item for item in facts if item.dimension is EffectDimension.ESCAPES)
    assert read.raw_references == ("fixture.jsonl#L1",)
    assert escaped.raw_references == ("fixture.jsonl#L2",)
    assert read.target != escaped.target  # identical legacy strings are not an identity proof
    assert read.target.kind is escaped.target.kind is ir.EffectTargetKind.OPAQUE
    assert read.evidence.kind is ir.EvidenceKind.INFERRED
    assert escaped.evidence.kind is ir.EvidenceKind.OBSERVED
    summary = boundary(result)
    assert summary.effects.reads.completeness is ir.Completeness.PARTIAL
    assert summary.effects.escapes.completeness is ir.Completeness.PARTIAL
    assert summary.effects.may_raise is ir.EffectPresence.UNKNOWN
    assert summary.effects.rng is ir.EffectPresence.UNKNOWN
    assert not summary.ready_for_region_construction
    assert all(scope.mode is ScopeMode.DYNAMIC_PATH and not scope.closed for scope in result.engine.scopes.values())


def test_dispatch_write_members_are_inferred_may_writes_regardless_of_operation_name():
    bundle = normalized([
        event("torch_dispatch", 1, 1, code="custom.uninformative", effect={"writes": ["arg-a", "arg-b"]}),
        event("torch_dispatch", 2, 2, code="custom.mutating_name_", effect={}),
    ])
    result = ingest_runtime_effects(bundle)
    writes = [item for item in result.engine.occurrences.values() if item.dimension is EffectDimension.WRITES]
    assert len(writes) == 2
    assert all(item.evidence.kind is ir.EvidenceKind.INFERRED for item in writes)
    assert all(any("may-write" in text for text in item.evidence.assumptions) for item in writes)
    assert all(item.raw_references == ("fixture.jsonl#L1",) for item in writes)
    assert result.coverage["counts"]["may_write_occurrences"] == 2


def test_input_capture_without_legacy_reads_still_has_only_a_possible_consumer():
    snapshot = {"object_id": "object:legacy-address", "type": "Tensor"}
    bundle = normalized([event("python_call", 0, 1, inputs=[snapshot])])
    result = ingest_runtime_effects(bundle)
    fact = next(iter(result.engine.occurrences.values()))
    observation = next(iter(bundle.evidence.observations.values()))
    assert fact.dimension is EffectDimension.READS
    assert fact.target.kind is ir.EffectTargetKind.VALUE_VERSION
    assert fact.target.reference == observation.version.wire
    assert fact.evidence.kind is ir.EvidenceKind.INFERRED
    assert boundary(result).effects.reads.completeness is ir.Completeness.PARTIAL


def test_same_device_transfer_expand_and_aggregate_memory_do_not_fabricate_effects():
    bundle = normalized([
        event("transfer", 0, 1, same_object=True, physical=False,
              resource={"operation": "to", "source_device": "cuda:0", "destination_device": "cuda:0"}),
        event("torch_dispatch", 1, 2, code="aten.expand.default"),
        event("torch_op", 2, aggregate=True, code="aten::empty",
              resource={"count": 100, "device_memory_usage": 4096}),
    ])
    result = ingest_runtime_effects(bundle)
    assert len(bundle.evidence.instances) == 2
    assert not result.engine.occurrences
    assert result.coverage["cost_measurements_ingested"] == 0
    assert all(not item.coverage[0].closed for item in result.engine.operations.values())


def test_legacy_pure_flag_and_none_effects_are_not_complete_proofs():
    effect = {field: "NONE" for field in ("rng_effect", "may_raise", "external_effect", "ordering_effect")}
    effect["collection_knowledge"] = {name: "KNOWN" for name in ("reads", "writes", "allocates", "frees", "aliases", "escapes")}
    bundle = normalized([event("module_call", 1, 1, effect=effect,
                               pure_contract=True, contract_read_capture="complete", contract_state_stable=True)])
    result = ingest_runtime_effects(bundle)
    summary = boundary(result)
    assert not summary.effects.is_complete
    assert summary.effects.rng is ir.EffectPresence.UNKNOWN
    assert summary.effects.external is ir.EffectPresence.UNKNOWN
    assert result.coverage["completed_effect_contracts"] == 0
    assert any("declaration" in gap for gap in summary.open_boundaries)


def test_physical_copy_and_barrier_preserve_presence_without_logical_endpoint_join():
    bundle = normalized([
        event("cuda_memcpy", 0, physical=True, clock_domain="kineto", logical_tensor_mapping="inferred_unique_signature",
              resource={"device": 0, "stream": 7, "context": 1, "bytes": 16, "direction": "HtoD"}),
        event("cuda_barrier", 1, clock_domain="kineto", host_tid=3),
    ])
    result = ingest_runtime_effects(bundle)
    facts = list(result.engine.occurrences.values())
    assert {item.dimension for item in facts} == {EffectDimension.READS, EffectDimension.WRITES, EffectDimension.ORDERING}
    assert all(item.evidence.kind is ir.EvidenceKind.OBSERVED for item in facts)
    assert all(item.target.kind is ir.EffectTargetKind.OPAQUE for item in facts if item.dimension is not EffectDimension.ORDERING)
    assert all(item.position is None and not item.ordered_after for item in facts)
    assert len(result.engine.scopes) == 2


def test_explicit_memory_events_are_not_paired_into_an_unobserved_allocation_lifetime():
    bundle = normalized([
        event("allocation", 0, resource={"device": "cpu", "bytes": 64, "storage_id": "same-pointer"}),
        event("free", 1, resource={"device": "cpu", "bytes": 64, "storage_id": "same-pointer"}),
    ])
    result = ingest_runtime_effects(bundle)
    facts = list(result.engine.occurrences.values())
    assert {item.dimension for item in facts} == {EffectDimension.ALLOCATES, EffectDimension.FREES}
    assert len({item.target for item in facts}) == 2
    assert all(any("lifetime pairing unproven" in text for text in item.evidence.assumptions) for item in facts)


def test_returned_callback_is_an_escape_and_consumer_closure_stays_open():
    callback = {"object_id": "callback:address", "callable_code_id": "code:callback", "callable_capture": "UNKNOWN"}
    bundle = normalized([
        event("python_call", 0, 1, callable_inputs=[callback]),
        event("python_return", 1, 1, returned_callables=[callback], return_escape_evidence="UNKNOWN"),
    ])
    result = ingest_runtime_effects(bundle)
    escaped = next(item for item in result.engine.occurrences.values() if item.dimension is EffectDimension.ESCAPES)
    assert escaped.evidence.kind is ir.EvidenceKind.OBSERVED
    closure = result.engine.consumer_closure(escaped.target, escaped.scope)
    assert closure.state in (ClosureState.LIVE, ClosureState.OPEN)
    assert any("callback" in gap for gap in closure.open_boundaries)
    assert not boundary(result).ready_for_region_construction


def test_unmatched_return_is_ingested_once_and_parent_child_cost_is_not_summed():
    orphan = normalized([event("python_return", 0, 4, effect={"escapes": ["returned"]})])
    assert len(ingest_runtime_effects(orphan).engine.occurrences) == 1
    bundle = normalized([
        event("python_call", 0, 1, effect={"reads": ["outer"]}),
        event("python_call", 1, 2, parent_invocation_id=1, effect={"reads": ["inner"]}),
        event("python_return", 2, 2), event("python_return", 3, 1),
    ])
    result = ingest_runtime_effects(bundle)
    parent = next(item for item in bundle.evidence.instances.values() if item.parent is None)
    summary = boundary(result, parent.definition)
    assert len(summary.occurrences) == len(result.engine.occurrences) == 2
    assert len({item.id for item in summary.occurrences}) == 2
    assert result.coverage["cost_measurements_ingested"] == 0
    assert any("independent cost units" in gap for gap in summary.open_boundaries)


def test_malformed_callback_descriptor_remains_a_gap_not_an_observed_escape():
    bundle = normalized([event("python_return", 0, 9, returned_callables=["not-a-descriptor"])])
    result = ingest_runtime_effects(bundle)
    assert not result.engine.occurrences
    assert result.coverage["counts"]["invalid_callback_descriptors"] == 1
    assert any("descriptor is invalid" in gap for gap in boundary(result).open_boundaries)


def test_runtime_ingestion_round_trips_deterministically_without_a_transform():
    bundle = normalized([event("python_call", 0, 1, effect={"reads": ["x"]}), event("python_return", 1, 1)])
    first = ingest_runtime_effects(bundle)
    second = ingest_runtime_effects(bundle)
    assert first.engine.to_json() == second.engine.to_json()
    restored = EffectClosureEngine.from_json(first.engine.to_json(), bundle.semantic, bundle.evidence)
    assert restored.to_json() == first.engine.to_json()
    assert first.coverage == second.coverage
    assert bundle.optimization is None
