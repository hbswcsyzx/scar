"""Provider/source declarations attached to canonical hand-written core graphs.

These fixtures model provider records only. They do not load artifacts, prove
that a provider is correct, or grant optimization authority.
"""
from dataclasses import replace

from scar.ir.program.ids import OperationID, ProviderID, RegionID, UseID, ValueID
from scar.ir.program.model import ProgramGraph
from scar.ir.program.providers import (
    ProviderArtifact,
    ProviderArtifactKind,
    ProviderBinding,
    ProviderCaptureMode,
    ProviderCollectionDomain,
    ProviderCollectionObservation,
    ProviderCondition,
    ProviderConditionDomain,
    ProviderCoverage,
    ProviderCoverageDomain,
    ProviderElement,
    ProviderElementKind,
    ProviderEnvelope,
    ProviderFactReference,
    ProviderPathIndex,
    ProviderPathKey,
    ProviderRegion,
    ProviderRegionRelation,
    ProviderRunScope,
    ProviderStage,
)
from scar.ir.v2.common import Completeness, SourceVersion

from tests.fixtures.program_graphs import shared_body_calls_program


def _artifact(provider="static-graph"):
    return ProviderArtifact(
        f"memory://fixtures/{provider}.json",
        "a" * 64,
        0,
        "fixture-provider-schema-v1",
    )


def _fact(artifact, locator):
    return ProviderFactReference(artifact, locator)


def _envelope(provider_id, *, kind=ProviderArtifactKind.DEFINITION_GRAPH,
              capture_mode=ProviderCaptureMode.STATIC_ANALYSIS, capture_scope=None,
              artifact=None, complete=False):
    artifact = artifact or _artifact(str(provider_id))
    fact = _fact(artifact, "#/fixture")
    coverage = tuple(
        ProviderCoverage(
            domain,
            Completeness.COMPLETE if complete else Completeness.UNKNOWN,
            fact if complete else None,
            "fixture provider declaration; independently unverified",
        )
        for domain in ProviderCoverageDomain
    )
    collection = tuple(
        ProviderCollectionObservation(
            domain,
            None,
            "capture effect or collection cost was not measured",
        )
        for domain in ProviderCollectionDomain
    )
    return ProviderEnvelope(
        ProviderID(provider_id),
        "fixture-provider",
        "1.0",
        None,
        artifact,
        kind,
        capture_mode,
        capture_scope,
        (SourceVersion("fixture.py", "sha256:" + "b" * 64),),
        (ProviderStage("parse", fact),),
        () if complete else (ProviderCondition(ProviderConditionDomain.SHAPE, fact),),
        coverage,
        collection,
    )


def _static_bindings(provider, region):
    """Bind one external operation and its ordered duplicate-Value operands."""
    return (
        ProviderBinding(
            provider,
            region,
            ProviderElement(ProviderElementKind.OPERATION, "twice"),
            OperationID("twice"),
        ),
        ProviderBinding(
            provider,
            region,
            ProviderElement(ProviderElementKind.DATA_VALUE, "argument", (ProviderPathKey("x"),)),
            ValueID("body.input"),
        ),
        ProviderBinding(
            provider,
            region,
            ProviderElement(ProviderElementKind.USE, "twice", (ProviderPathIndex(0),)),
            UseID("twice.left"),
        ),
        ProviderBinding(
            provider,
            region,
            ProviderElement(ProviderElementKind.USE, "twice", (ProviderPathIndex(1),)),
            UseID("twice.right"),
        ),
        ProviderBinding(
            provider,
            region,
            ProviderElement(ProviderElementKind.DATA_VALUE, "twice", (ProviderPathKey("result"),)),
            ValueID("body.result"),
        ),
        ProviderBinding(
            provider,
            region,
            ProviderElement(ProviderElementKind.OPERATION, "count"),
            OperationID("count.call"),
        ),
        ProviderBinding(
            provider,
            region,
            ProviderElement(ProviderElementKind.STATE_VALUE, "entry", (ProviderPathKey("world"),)),
            ValueID("body.initial"),
        ),
        ProviderBinding(
            provider,
            region,
            ProviderElement(ProviderElementKind.STATE_VALUE, "count", (ProviderPathKey("world"),)),
            ValueID("body.updated"),
        ),
    )


def definition_provider_graph(*, complete_claims=False):
    """A definition graph with distinct Use occurrences over one shared Value."""
    graph = shared_body_calls_program()
    envelope = _envelope("definition-provider", complete=complete_claims)
    association = ProviderRegion(
        envelope.id,
        "external.body",
        RegionID("callee"),
        ProviderRegionRelation.DEFINES_REPRESENTATION,
    )
    return replace(
        graph,
        provider_envelopes=(envelope,),
        provider_regions=(association,),
        provider_bindings=_static_bindings(envelope.id, association.region),
    )


def execution_observation_graph(*, with_static_binding=False):
    """One run can scope several Regions without owning their representation."""
    graph = shared_body_calls_program()
    envelope = _envelope(
        "execution-provider",
        kind=ProviderArtifactKind.EXECUTION_EVIDENCE,
        capture_mode=ProviderCaptureMode.REAL_EXECUTION,
        capture_scope=ProviderRunScope("run-1", 17, "window-1", "monotonic-ns", 3),
    )
    associations = (
        ProviderRegion(
            envelope.id,
            "observed.project",
            RegionID("callee"),
            ProviderRegionRelation.OBSERVATION_SCOPE,
        ),
        ProviderRegion(
            envelope.id,
            "observed.project",
            RegionID("caller"),
            ProviderRegionRelation.OBSERVATION_SCOPE,
        ),
    )
    bindings = ()
    if with_static_binding:
        # This is intentionally invalid: observed scope cannot mint a mapping
        # between runtime evidence and a declared operation.
        bindings = (
            ProviderBinding(
                envelope.id,
                RegionID("callee"),
                ProviderElement(ProviderElementKind.OPERATION, "twice"),
                OperationID("twice"),
            ),
        )
    return replace(
        graph,
        provider_envelopes=(envelope,),
        provider_regions=associations,
        provider_bindings=bindings,
    )


def execution_multirun_observation_graph():
    """The same external scope key is separated by provider/run identity."""
    graph = shared_body_calls_program()
    first = _envelope(
        "execution-provider-run-1",
        kind=ProviderArtifactKind.EXECUTION_EVIDENCE,
        capture_mode=ProviderCaptureMode.REAL_EXECUTION,
        capture_scope=ProviderRunScope("run-1", 17, "window-1", "monotonic-ns", 3),
    )
    second = _envelope(
        "execution-provider-run-2",
        kind=ProviderArtifactKind.EXECUTION_EVIDENCE,
        capture_mode=ProviderCaptureMode.REAL_EXECUTION,
        capture_scope=ProviderRunScope("run-2", 17, "window-2", "monotonic-ns", 3),
    )
    associations = tuple(
        ProviderRegion(envelope.id, "same.external.scope", region, ProviderRegionRelation.OBSERVATION_SCOPE)
        for envelope in (first, second)
        for region in (RegionID("caller"), RegionID("callee"))
    )
    return replace(graph, provider_envelopes=(first, second), provider_regions=associations)


def definition_parent_owner_graph():
    """An owner on a parent is not implicitly inherited by its child Region."""
    graph = shared_body_calls_program()
    envelope = _envelope("parent-definition-provider")
    association = ProviderRegion(
        envelope.id,
        "external.parent",
        RegionID("caller"),
        ProviderRegionRelation.DEFINES_REPRESENTATION,
    )
    return replace(graph, provider_envelopes=(envelope,), provider_regions=(association,))


def provider_owner_conflict_graph():
    """Two definition envelopes cannot both own one canonical Region."""
    graph = definition_provider_graph()
    second = _envelope("second-definition-provider")
    return replace(
        graph,
        provider_envelopes=(*graph.provider_envelopes, second),
        provider_regions=(*graph.provider_regions, ProviderRegion(
            second.id,
            "another.external.body",
            RegionID("callee"),
            ProviderRegionRelation.DEFINES_REPRESENTATION,
        )),
    )

