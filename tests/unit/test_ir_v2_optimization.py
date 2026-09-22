import pytest

from scar.ir.v2 import (
    Completeness,
    ControlRegionID,
    CorrespondenceGraph,
    CorrespondenceID,
    CorrespondenceKind,
    CorrespondenceRecord,
    ContractDefinition,
    ContractFacet,
    ContractID,
    EffectPresence,
    EffectSet,
    EffectSummary,
    EffectSummaryID,
    EvidenceClaim,
    EvidenceEdge,
    EvidenceEndpoint,
    EvidenceGraph,
    EvidenceKind,
    EvidenceNodeKind,
    EvidenceRelation,
    FacetRequirement,
    IRBundle,
    InstructionKind,
    LiteralValue,
    LogicalValue,
    LogicalValueID,
    Materialization,
    MaterializationID,
    MeasurementMode,
    ModuleDefinition,
    ModuleID,
    OperationDefinition,
    OperationDefinitionID,
    OperationInstance,
    OperationInstanceID,
    OperationKind,
    OptimizationGraph,
    OptimizationContext,
    OptimizationRegion,
    OptimizationRegionID,
    PackageDefinition,
    PackageID,
    PlanAlternative,
    PlanAlternativeID,
    PlanDisposition,
    PlanID,
    PlanInstruction,
    PlanSelection,
    ProofClaim,
    ProofStatus,
    RegionGranularity,
    RegionMove,
    RegionPort,
    RegionPortKind,
    ResourceID,
    ResourceKind,
    ResourceRequirement,
    ResidualEffect,
    SemanticEdge,
    SemanticEndpoint,
    SemanticGraph,
    SemanticNodeKind,
    SemanticRelation,
    SourceAtom,
    SourceAtomID,
    SourceReference,
    TransformDelta,
    TransformKind,
    ValidationRequest,
    ValueGraph,
    ValueObservation,
    ValuePattern,
    ValueSlot,
    ValueSlotID,
    ValueSubstitution,
    ValueVersion,
    ValueVersionID,
    canonical_json,
    optimization_context,
)


def _foundation():
    source_id = SourceAtomID("program.py:1:0:literal")
    source = SourceReference(source_id, "/project/program.py", "sha256:source", 1, 1)
    package_id = PackageID("project")
    module_id = ModuleID("project.program")
    operation_id = OperationDefinitionID("program.literal_path")
    input_slot = ValueSlotID("program.input")
    output_slot = ValueSlotID("program.output")
    contract_id = ContractID("exact-output")
    effect_id = EffectSummaryID("literal-path-effects")
    resource_id = ResourceID("cpu")

    semantic = SemanticGraph()
    semantic.add_package(PackageDefinition(package_id, "project", "/project", "git:1"))
    semantic.add_source_atom(SourceAtom(source_id, source, "expression", "sha256:text"))
    semantic.add_effect(EffectSummary(
        effect_id,
        reads=EffectSet(completeness=Completeness.COMPLETE),
        writes=EffectSet(completeness=Completeness.COMPLETE),
        allocates=EffectSet(completeness=Completeness.COMPLETE),
        frees=EffectSet(completeness=Completeness.COMPLETE),
        aliases=EffectSet(completeness=Completeness.COMPLETE),
        escapes=EffectSet(completeness=Completeness.COMPLETE),
        rng=EffectPresence.NONE,
        may_raise=EffectPresence.NONE,
        external=EffectPresence.NONE,
        ordering=EffectPresence.NONE,
    ))
    semantic.add_resource(ResourceRequirement(resource_id, ResourceKind.CPU, "process"))
    semantic.add_contract(ContractDefinition(
        contract_id, "exact output", required_outputs=(output_slot,),
        facets=(FacetRequirement(ContractFacet.OUTPUT, True),)))
    operation = OperationDefinition(
        operation_id, OperationKind.ATTRIBUTE, "constant path",
        code_id="code:literal", input_slots=(input_slot,), output_slots=(output_slot,),
        source_atoms=(source_id,), contract=contract_id, effect_summary=effect_id,
        resource_requirements=(resource_id,))
    semantic.add_definition(operation)
    semantic.add_slot(ValueSlot(input_slot, "module", "input", owner=operation_id))
    semantic.add_slot(ValueSlot(output_slot, "constant", "output", owner=operation_id))
    semantic.add_module(ModuleDefinition(
        module_id, "project.program", package_id, "/project/program.py",
        "sha256:source", operation_id))
    semantic.add_edge(SemanticEdge(
        "edge:has-source", SemanticRelation.HAS_SOURCE,
        SemanticEndpoint(SemanticNodeKind.OPERATION, operation_id),
        SemanticEndpoint(SemanticNodeKind.SOURCE_ATOM, source_id),
        EvidenceClaim(EvidenceKind.OBSERVED, ("ast:1",), confidence=1.0)))

    logical_id = LogicalValueID("literal-value")
    version_id = ValueVersionID(logical_id, 0)
    materialization_id = MaterializationID("python-literal")
    values = ValueGraph()
    values.add_logical_value(LogicalValue(logical_id, "tuple"))
    values.add_version(ValueVersion(version_id, semantic_type="tuple"))
    values.add_materialization(Materialization(
        materialization_id, version_id, "python_literal", "cpu"))

    evidence = EvidenceGraph()
    instance_id = OperationInstanceID("process:1/call:1")
    evidence.add_instance(OperationInstance(instance_id, operation_id, 1, 1))
    evidence.add_observation(ValueObservation(
        "observation:literal", version_id, instance_id, materialization_id, "output"))
    evidence.add_edge(EvidenceEdge(
        "edge:produces", EvidenceRelation.PRODUCES,
        EvidenceEndpoint(EvidenceNodeKind.OPERATION_INSTANCE, instance_id),
        EvidenceEndpoint(EvidenceNodeKind.VALUE_OBSERVATION, "observation:literal"),
        EvidenceClaim(EvidenceKind.OBSERVED, ("trace:event:1",), confidence=1.0)))
    return semantic, evidence, values, source, operation_id, instance_id, version_id


def test_typed_ids_cannot_be_interchanged():
    assert PackageID("same") != ModuleID("same")
    with pytest.raises(TypeError, match="slot_id"):
        ValueSlot("plain-string", "value", "input")
    with pytest.raises(TypeError, match="requires ModuleID"):
        SemanticEndpoint(SemanticNodeKind.MODULE, PackageID("same"))


def test_bundle_validates_cross_graph_references_and_is_deterministic():
    semantic, evidence, values, *_ = _foundation()
    operation_id = next(iter(semantic.definitions))
    instance_id = next(iter(evidence.instances))
    correspondence = CorrespondenceGraph()
    correspondence.add(CorrespondenceRecord(
        CorrespondenceID("operation-call"),
        CorrespondenceKind.DEFINITION_INSTANCE,
        definition=operation_id,
        instance=instance_id,
        evidence=EvidenceClaim(EvidenceKind.OBSERVED, ("trace:event:1",),
                               confidence=1.0)))
    bundle = IRBundle(semantic, evidence, values, correspondence=correspondence)
    assert bundle.assert_valid()["valid"]
    assert canonical_json(bundle) == canonical_json(bundle)

    evidence.instances[OperationInstanceID("process:1/call:1")].definition = (
        OperationDefinitionID("missing"))
    report = bundle.validate()
    assert not report["valid"]
    assert any("unknown definition" in item for item in report["errors"])


def test_report_only_constant_substitution_plan_has_original_and_fallback():
    (semantic, evidence, values, source, operation_id, instance_id,
     version_id) = _foundation()
    context = optimization_context(semantic, evidence, values)
    graph = OptimizationGraph(context)
    graph.add_port(RegionPort(
        "port:output", RegionPortKind.OUTPUT, "constant output",
        value=ValuePattern(versions=(version_id,), semantic_type="tuple")))
    region_id = OptimizationRegionID("literal-path")
    graph.add_region(OptimizationRegion(
        region_id, RegionGranularity.DATAFLOW_SUBGRAPH, "literal import path",
        definitions=(operation_id,), instances=(instance_id,),
        ports=("port:output",), source_atoms=(source.atom_id,)))

    original_id = PlanAlternativeID("literal-path:original")
    graph.add_alternative(PlanAlternative(
        original_id, region_id, "original execution", TransformKind.NO_OP,
        original=True))

    rewrite_id = PlanAlternativeID("literal-path:substitute")
    proof = ProofClaim(
        "literal_value_equivalent", ProofStatus.PROVEN,
        evidence=(EvidenceClaim(EvidenceKind.INFERRED, ("ast:literal",),
                                confidence=1.0),),
        reason="the literal producer and consumer value are identical")
    graph.add_alternative(PlanAlternative(
        rewrite_id, region_id, "substitute literal", TransformKind.SUBSTITUTE,
        delta=TransformDelta(
            removed_definitions=(operation_id,),
            substitutions=(ValueSubstitution(
                version_id, literal=LiteralValue([1, 2, 3])),)),
        proofs=(proof,), fallback=original_id,
        validation_request=ValidationRequest(
            ContractID("exact-output"), (1,), ("outputs",)),
        instructions=(PlanInstruction(
            "instruction:replace", InstructionKind.REPLACE_VALUE_PATH,
            target=version_id.wire, source=source, replacement=[1, 2, 3],
            rationale="contract-preserving literal substitution"),)))
    graph.add_plan(PlanSelection(
        PlanID("literal-path:selected"), region_id, PlanDisposition.REWRITE,
        selected=rewrite_id, reason="all obligations proven"))

    assert graph.assert_valid()["valid"]
    document = graph.to_dict()
    assert document["plans"][0]["disposition"] == "REWRITE"
    assert document["alternatives"][1]["fallback"]["wire"] == original_id.wire
    assert canonical_json(graph) == canonical_json(graph)


def test_rewrite_plan_rejects_unknown_proof_and_dangling_region_members():
    semantic, evidence, values, _source, operation_id, instance_id, _version = _foundation()
    graph = OptimizationGraph(optimization_context(semantic, evidence, values))
    region_id = OptimizationRegionID("region")
    graph.add_region(OptimizationRegion(
        region_id, RegionGranularity.FUNCTION, "region",
        definitions=(operation_id,), instances=(instance_id,)))
    original_id = PlanAlternativeID("region:original")
    graph.add_alternative(PlanAlternative(
        original_id, region_id, "original", TransformKind.NO_OP, original=True))
    unknown_id = PlanAlternativeID("region:unknown")
    graph.add_alternative(PlanAlternative(
        unknown_id, region_id, "unproven deletion", TransformKind.DELETE,
        delta=TransformDelta(removed_definitions=(operation_id,)),
        proofs=(ProofClaim("effects_dead", ProofStatus.UNKNOWN,
                           reason="consumer scope is open",
                           required_next="trace all external consumers"),),
        fallback=original_id))
    with pytest.raises(ValueError, match="unproven"):
        graph.add_plan(PlanSelection(
            PlanID("bad-rewrite"), region_id, PlanDisposition.REWRITE,
            selected=unknown_id, reason="incorrect attempt"))
    with pytest.raises(ValueError, match="unknown definition"):
        graph.add_region(OptimizationRegion(
            OptimizationRegionID("dangling"), RegionGranularity.FUNCTION,
            "dangling", definitions=(OperationDefinitionID("missing"),)))


def test_measurement_mode_keeps_clean_and_instrumented_distinct():
    assert MeasurementMode.CLEAN.value != MeasurementMode.INSTRUMENTED.value


def test_oir_represents_import_residual_loop_move_and_residency_without_backend():
    import_def = OperationDefinitionID("import.path")
    loop_def = OperationDefinitionID("loop.body")
    copy_def = OperationDefinitionID("copy.to_device")
    source_id = SourceAtomID("program.py:1")
    effect_id = EffectSummaryID("module-init")
    contract_id = ContractID("exact")
    outer_control = ControlRegionID("function")
    loop_control = ControlRegionID("loop")
    logical = LogicalValueID("input")
    version = ValueVersionID(logical, 0)
    materialization = MaterializationID("gpu-copy")
    context = OptimizationContext(
        definitions=frozenset((import_def, loop_def, copy_def)),
        value_versions=frozenset((version,)),
        materializations=frozenset((materialization,)),
        controls=frozenset((outer_control, loop_control)),
        effects=frozenset((effect_id,)),
        contracts=frozenset((contract_id,)),
        source_atoms=frozenset((source_id,)),
    )
    graph = OptimizationGraph(context)
    graph.add_port(RegionPort(
        "resident:value", RegionPortKind.INPUT, "resident value",
        value=ValuePattern(versions=(version,),
                           materializations=(materialization,))))

    import_region = OptimizationRegionID("import-region")
    loop_region = OptimizationRegionID("loop-region")
    copy_region = OptimizationRegionID("copy-region")
    graph.add_region(OptimizationRegion(
        import_region, RegionGranularity.DATAFLOW_SUBGRAPH, "import path",
        definitions=(import_def,), effect_summary=effect_id,
        contract=contract_id, source_atoms=(source_id,)))
    graph.add_region(OptimizationRegion(
        loop_region, RegionGranularity.LOOP_BODY, "loop invariant body",
        definitions=(loop_def,), contract=contract_id))
    graph.add_region(OptimizationRegion(
        copy_region, RegionGranularity.DATAFLOW_SUBGRAPH, "materialization",
        definitions=(copy_def,), ports=("resident:value",), contract=contract_id))

    original_ids = {}
    for region in (import_region, loop_region, copy_region):
        original = PlanAlternativeID(f"{region.value}:original")
        original_ids[region] = original
        graph.add_alternative(PlanAlternative(
            original, region, "original", TransformKind.NO_OP, original=True))

    proven = (ProofClaim("legality", ProofStatus.PROVEN,
                         reason="fixture contract"),)
    graph.add_alternative(PlanAlternative(
        PlanAlternativeID("import:residualized"), import_region,
        "replace value and preserve module effect", TransformKind.SUBSTITUTE,
        delta=TransformDelta(removed_definitions=(import_def,),
                             substitutions=(ValueSubstitution(
                                 version, literal=LiteralValue(None)),)),
        proofs=proven,
        residual_effects=(ResidualEffect(effect_id, "required by Q", "module entry"),),
        instructions=(PlanInstruction(
            "preserve:init", InstructionKind.PRESERVE_EFFECT,
            effect_id.wire, rationale="value path is dead but effect is live"),),
        fallback=original_ids[import_region]))
    graph.add_alternative(PlanAlternative(
        PlanAlternativeID("loop:hoist"), loop_region,
        "move invariant slice", TransformKind.MOVE,
        delta=TransformDelta(moves=(RegionMove(
            loop_region, loop_control, outer_control),)),
        proofs=proven, fallback=original_ids[loop_region]))
    graph.add_alternative(PlanAlternative(
        PlanAlternativeID("copy:resident"), copy_region,
        "retain physical materialization", TransformKind.RESIDENCY,
        delta=TransformDelta(removed_definitions=(copy_def,),
                             added_operations=("lifetime_guard",)),
        proofs=proven,
        instructions=(PlanInstruction(
            "retain:gpu", InstructionKind.RETAIN_MATERIALIZATION,
            materialization.wire, rationale="reuse the same logical version"),),
        fallback=original_ids[copy_region]))

    assert graph.assert_valid()["valid"]
    kinds = {item["transform"] for item in graph.to_dict()["alternatives"]}
    assert {"no_op", "substitute", "move", "residency"} <= kinds
