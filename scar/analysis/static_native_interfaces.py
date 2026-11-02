"""Lower receipt-bound native declarations into the existing canonical IR.

This represents a schema interface, not a selected Python binding, dispatcher
branch or kernel body.  No execution/evidence graph or runtime identity exists
here.  Alias, mutation, defaults and dispatch declarations stay in the original
material record referenced by the NativeBoundary, without stronger claims.
"""
from __future__ import annotations

from dataclasses import asdict
from hashlib import sha256
import json
from pathlib import Path

from scar.analysis.static_native_materials import StaticNativeMaterials
from scar.ir.program.ids import (
    BlockID, LocationID, NativeBoundaryID, OperationID, ProviderID, RegionID, UseID, ValueID,
)
from scar.ir.program.model import (
    Behavior, Block, BlockArgument, CompletionResult, CompletionSignature,
    CompletionSuccessor, DataValue, ExitKind, ExitPort, Operation, ProgramGraph,
    ReferenceValue, Region, StateLocation, StateVersionValue, Terminator,
    TerminatorKind, Use, UseRole, value_type,
)
from scar.ir.program.native import (
    CoreInputPort, CoreOutputPort, EntryPortRef, ExitPortRef,
    NativeBoundary, NativeInputSlot, NativeOutputSlot,
)
from scar.ir.program.providers import (
    ProviderArtifact, ProviderArtifactKind, ProviderBinding, ProviderCaptureMode,
    ProviderCollectionDomain, ProviderCollectionObservation, ProviderCoverage,
    ProviderCoverageDomain, ProviderElement, ProviderElementKind, ProviderEnvelope,
    ProviderFactReference, ProviderPathIndex, ProviderPathKey, ProviderRegion,
    ProviderRegionRelation, ProviderStage,
)
from scar.ir.program.validation import require_valid
from scar.ir.v2.common import Completeness


SCHEMA = 'scar.static-native-materials'


def native_material_document(materials):
    if type(materials) is not StaticNativeMaterials:
        raise TypeError('expected receipt-bound static native materials')
    # Material records use immutable tuples; a JSON document uses arrays.
    # Normalize once so fresh artifact comparison is structural and exact.
    return json.loads(json.dumps({'schema': SCHEMA, 'schema_version': 1,
        **asdict(materials)}, allow_nan=False))


def _reference_type(type_):
    # A container port is one composite reference, never flattened Tensor
    # element ports.  Optional reference types include their absent variant.
    if type_.kind == 'OptionalType':
        return _reference_type(type_.element)
    return type_.kind in ('ListType', 'CustomClassType') or (
        type_.kind == 'BaseType' and type_.name == 'Tensor')


def lower_static_native_materials(materials, artifact):
    """Build one independent canonical interface per original overload.

    The supplied JSON artifact is freshly matched to the exact parser output.
    Caller-selected schema families do not establish whole-program coverage.
    The artifact is a provider input; publication into a program is separate.
    """
    document = native_material_document(materials)
    if type(artifact) is not ProviderArtifact or artifact.schema != SCHEMA:
        raise TypeError('native interfaces require the original typed material artifact')
    artifact.__post_init__()
    path = Path(artifact.uri)
    if not path.is_absolute() or path.resolve() != path or not path.is_file():
        raise ValueError('native material artifact must be a canonical existing file')
    if path.stat().st_size != artifact.size_bytes or artifact.size_bytes > 16_000_000:
        raise ValueError('native material artifact size differs or exceeds the limit')
    raw = path.read_bytes()
    if len(raw) != artifact.size_bytes or sha256(raw).hexdigest() != artifact.sha256:
        raise ValueError('native material artifact receipt differs')
    if json.loads(raw) != document:
        raise ValueError('native material artifact is not this parser output')
    if (not materials.parser.isolated or not materials.parser.no_site
            or materials.parser.torch_imported):
        raise ValueError('native materials require an isolated non-runtime parser')
    graphs = []
    for ordinal, declaration in enumerate(materials.declarations):
        identity = sha256((artifact.sha256 + '\0' + declaration.selector + '\0'
            + declaration.schema).encode()).hexdigest()[:32]
        prefix = 'static-native:' + identity
        region = RegionID(prefix)
        provider = ProviderID(prefix + ':provider')
        entry, normal, failed = (BlockID(prefix + ':' + name) for name in ('entry', 'normal', 'raised'))
        invoke, returned, raised = (OperationID(prefix + ':' + name) for name in ('invoke', 'return', 'raise'))
        location = LocationID(prefix + ':world')
        fact_path = '#/declarations/' + str(ordinal)

        def fact(suffix=''):
            return ProviderFactReference(artifact, fact_path + suffix)

        def port_value(block, position, port, label):
            identity = ValueID(prefix + ':' + label + ':' + str(position))
            origin = BlockArgument(block, position)
            if _reference_type(port.type):
                return ReferenceValue(identity, region, origin)
            # SymInt, Scalar, Device, etc. remain native schema types.  Their
            # spelling is not proof of a Python builtin value or constant.
            return DataValue(identity, region, origin, 'aten.schema:' + port.type.text)

        before = [port_value(entry, i, p, 'input') for i, p in enumerate(declaration.inputs)]
        after = [port_value(normal, i, p, 'output') for i, p in enumerate(declaration.outputs)]
        before.append(StateVersionValue(ValueID(prefix + ':world.before'), region,
            BlockArgument(entry, len(before)), location))
        after.append(StateVersionValue(ValueID(prefix + ':world.normal'), region,
            BlockArgument(normal, len(after)), location))
        error = [ReferenceValue(ValueID(prefix + ':exception'), region, BlockArgument(failed, 0)),
            StateVersionValue(ValueID(prefix + ':world.raised'), region, BlockArgument(failed, 1), location)]

        def uses(operation, values):
            return tuple(Use(UseID(operation.value + ':use:' + str(i)), value.id,
                UseRole.REFERENCE if type(value) is ReferenceValue else
                UseRole.STATE_CONTENT if type(value) is StateVersionValue else UseRole.DATA)
                for i, value in enumerate(values))

        inputs, outputs, errors = uses(invoke, before), uses(returned, after), uses(raised, error)
        normal_types, error_types = tuple(map(value_type, after)), tuple(map(value_type, error))
        operations = (
            Operation(invoke, declaration.schema, (Behavior.CONTROL,), inputs, effects_complete=False,
                terminator=Terminator(TerminatorKind.INVOKE, (
                    CompletionSuccessor(ExitKind.NORMAL, normal, tuple(CompletionResult(i) for i in range(len(after)))),
                    CompletionSuccessor(ExitKind.RAISE, failed, tuple(CompletionResult(i) for i in range(len(error)))))),
                completions=(CompletionSignature(ExitKind.NORMAL, normal_types),
                    CompletionSignature(ExitKind.RAISE, error_types)), invoke_arguments=tuple(u.id for u in inputs)),
            Operation(returned, 'declared native normal completion', (Behavior.CONTROL,), outputs,
                terminator=Terminator(TerminatorKind.RETURN, exit='normal', values=tuple(u.id for u in outputs))),
            Operation(raised, 'possible native exceptional completion', (Behavior.CONTROL,), errors,
                terminator=Terminator(TerminatorKind.RAISE, exit='raised', values=tuple(u.id for u in errors))))
        envelope = ProviderEnvelope(provider, 'installed ATen static declarations', materials.package_version,
            materials.source_revision, artifact, ProviderArtifactKind.DEFINITION_GRAPH,
            ProviderCaptureMode.STATIC_ANALYSIS, None, (), (ProviderStage('schema/header declaration', fact()),), (),
            tuple(ProviderCoverage(domain, Completeness.PARTIAL if domain in (
                ProviderCoverageDomain.SOURCE, ProviderCoverageDomain.STRUCTURE,
                ProviderCoverageDomain.DATAFLOW) else Completeness.UNKNOWN,
                fact() if domain in (ProviderCoverageDomain.SOURCE, ProviderCoverageDomain.STRUCTURE,
                    ProviderCoverageDomain.DATAFLOW) else None,
                'Static ordered interface only; implementation, binding and effects remain open.')
                for domain in ProviderCoverageDomain),
            tuple(ProviderCollectionObservation(domain, None,
                'No target execution or capture measurement.') for domain in ProviderCollectionDomain))
        bindings = [ProviderBinding(provider, region, ProviderElement(
            ProviderElementKind.OPERATION, declaration.selector), invoke)]
        for direction, values, ports in (('inputs', before[:-1], inputs[:-1]), ('outputs', after[:-1], ())):
            for position, value in enumerate(values):
                coordinate = (ProviderPathKey(direction), ProviderPathIndex(position))
                kind = ProviderElementKind.REFERENCE_VALUE if type(value) is ReferenceValue else ProviderElementKind.DATA_VALUE
                bindings.append(ProviderBinding(provider, region, ProviderElement(kind, declaration.selector, coordinate), value.id))
                if direction == 'inputs':
                    bindings.append(ProviderBinding(provider, region, ProviderElement(
                        ProviderElementKind.USE, declaration.selector, coordinate), ports[position].id))
        boundary = NativeBoundary(NativeBoundaryID(prefix + ':boundary'), provider, region,
            fact('/schema'), None, None,
            tuple(NativeInputSlot(i, p.kind, fact('/inputs/' + str(i)), EntryPortRef(region, before[i].id))
                for i, p in enumerate(declaration.inputs)),
            tuple(NativeOutputSlot(i, p.kind, fact('/outputs/' + str(i)), ExitPortRef(region, 'normal', i))
                for i, p in enumerate(declaration.outputs)),
            (CoreInputPort(EntryPortRef(region, before[-1].id), 'Open native state/effects domain.'),),
            (CoreOutputPort(ExitPortRef(region, 'normal', len(after) - 1), 'Open state after normal completion.'),
                CoreOutputPort(ExitPortRef(region, 'raised', 0), 'Possible exception, outside schema returns.'),
                CoreOutputPort(ExitPortRef(region, 'raised', 1), 'Open state after exceptional completion.')))
        graph = ProgramGraph(region, (Region(region, declaration.schema, entry,
            (Block(entry, tuple(v.id for v in before), (invoke,)),
                Block(normal, tuple(v.id for v in after), (returned,)),
                Block(failed, tuple(v.id for v in error), (raised,))),
            (ExitPort('normal', ExitKind.NORMAL, normal_types), ExitPort('raised', ExitKind.RAISE, error_types))),),
            operations, tuple((*before, *after, *error)), (StateLocation(location,
                'Open native state domain; schema aliases are not physical storage identities.'),),
            provider_envelopes=(envelope,), provider_regions=(ProviderRegion(provider, declaration.selector,
                region, ProviderRegionRelation.DEFINES_REPRESENTATION),), provider_bindings=tuple(bindings),
            native_boundaries=(boundary,))
        require_valid(graph)
        graphs.append(graph)
    return tuple(graphs)


__all__ = ['SCHEMA', 'native_material_document', 'lower_static_native_materials']
