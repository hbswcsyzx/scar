"""Shared declared CPython CALL interfaces, without invoking a callable.

Templates own Python-side ports and an open dispatch boundary. C layouts are
conditional contracts, not observed C entry, arguments, allocations or returns.
"""
from __future__ import annotations

from dataclasses import dataclass
import gzip
from hashlib import sha256
import json
from pathlib import Path

from scar.ir.program.codec import dumps as dump_graph
from scar.ir.program.functions import ArgumentKind
from scar.ir.program.ids import (
    BlockID, LocationID, NativeBoundaryID, OperationID, ProviderID, RegionID, UseID, ValueID,
)
from scar.ir.program.model import (
    Behavior, Block, BlockArgument, CompletionResult, CompletionSignature, CompletionSuccessor,
    ExitKind, ExitPort, Operation, ProgramGraph, ReferenceValue, Region, StateLocation,
    StateVersionValue, Terminator, TerminatorKind, Use, UseRole, value_type,
)
from scar.ir.program.native import (
    CoreInputPort, CoreOutputPort, EntryPortRef, ExitPortRef, NativeBoundary,
    NativeInputSlot, NativeOutputSlot,
)
from scar.ir.program.providers import (
    ProviderArtifact, ProviderArtifactKind, ProviderBinding, ProviderCaptureMode,
    ProviderCollectionDomain, ProviderCollectionObservation, ProviderCoverage,
    ProviderCoverageDomain, ProviderElement, ProviderElementKind, ProviderEnvelope,
    ProviderFactReference, ProviderRegion, ProviderRegionRelation, ProviderStage,
)
from scar.ir.program.source_references import SourceArtifactLocator
from scar.ir.program.validation import require_valid
from scar.ir.v2.common import Completeness


SCHEMA = 'scar.cpython-native-protocol'
PROTOCOL_VERSION = 1


@dataclass(frozen=True, slots=True)
class NativeProtocolShape:
    carrier: str
    flags: int
    arguments: tuple[tuple[str, str | None], ...]

    def __post_init__(self):
        if (type(self.carrier) is not str or self.carrier not in ('METHOD_DEF', 'WRAPPER_SLOT')
                or type(self.flags) is not int or not 0 <= self.flags <= 0xffffffff
                or type(self.arguments) is not tuple):
            raise ValueError('native protocol shape requires a recognized carrier and exact flags/arguments')
        for row in self.arguments:
            if type(row) is not tuple or len(row) != 2 or type(row[0]) is not str:
                raise TypeError('native source argument shape must be a typed kind/keyword tuple')
            kind, keyword = row
            if kind not in tuple(item.value for item in ArgumentKind):
                raise ValueError('native protocol argument kind is unsupported')
            if (kind == ArgumentKind.KEYWORD.value and
                    (type(keyword) is not str or not keyword or '\0' in keyword)
                    or kind != ArgumentKind.KEYWORD.value and keyword is not None):
                raise ValueError('only original explicit keyword arguments have a keyword selector')


def _json(document):
    return (json.dumps(document, sort_keys=True, separators=(',', ':'),
                       ensure_ascii=True, allow_nan=False) + '\n').encode('ascii')


def _shape(shape):
    if type(shape) is not NativeProtocolShape:
        raise TypeError('expected exact NativeProtocolShape')
    shape.__post_init__()
    return {'carrier': shape.carrier, 'flags': shape.flags,
            'arguments': [[kind, keyword] for kind, keyword in shape.arguments]}


def native_protocol_key(shape):
    """Only the versioned protocol and source-port shape select a template."""
    return sha256(_json({'protocol_version': PROTOCOL_VERSION, 'shape': _shape(shape)})).hexdigest()


def _cabi_contract(shape):
    if shape.carrier == 'WRAPPER_SLOT':
        convention = 'WRAPPER_KEYWORDS' if shape.flags & 1 else 'WRAPPER_POSITIONAL'
        if shape.flags & ~1:
            convention = 'UNSUPPORTED_WRAPPER_FLAGS'
        formals = ['SELF', 'POSITIONAL_TUPLE', 'WRAPPED_SLOT']
        if shape.flags & 1:
            formals.append('KEYWORD_DICT')
        roles = ['EXACT_WRAPPER_DESCRIPTOR_ROLE_REQUIRED']
    else:
        # These are the exact CPython dispatch mask/alternatives; binding and
        # coexistence flags are preserved in the shape, not mistaken for ABI.
        conventions = {
            0x04: ('NOARGS', ['SELF', 'C_NULL']),
            0x08: ('O', ['SELF', 'OBJECT']),
            0x01: ('VARARGS', ['SELF', 'POSITIONAL_TUPLE']),
            0x03: ('VARARGS_KEYWORDS', ['SELF', 'POSITIONAL_TUPLE', 'KEYWORD_DICT']),
            0x80: ('FASTCALL', ['SELF', 'POSITIONAL_ARRAY', 'POSITIONAL_COUNT']),
            0x82: ('FASTCALL_KEYWORDS', ['SELF', 'POSITIONAL_AND_KEYWORD_ARRAY',
                                      'POSITIONAL_COUNT', 'KEYWORD_NAMES']),
            0x282: ('METHOD_FASTCALL_KEYWORDS', ['SELF', 'DEFINING_CLASS',
                'POSITIONAL_AND_KEYWORD_ARRAY', 'POSITIONAL_COUNT', 'KEYWORD_NAMES']),
        }
        convention, formals = conventions.get(shape.flags & 0x28f,
                                               ('UNSUPPORTED_METHOD_FLAGS', []))
        roles = ['EXACT_PYC_FUNCTION_OR_PYC_METHOD_ROLE_REQUIRED',
                 'EXACT_METHOD_DESCRIPTOR_ROLE_REQUIRED',
                 'EXACT_CLASSMETHOD_DESCRIPTOR_ROLE_REQUIRED']
    return {'qualification': 'CONDITIONAL_LAYOUT_NOT_OBSERVED_C_ARGUMENTS',
        'abi_profile': 'CPYTHON_3_14_7_GIL_LINUX_X86_64',
        'flags_domain': 'PyMethodDef.ml_flags' if shape.carrier == 'METHOD_DEF' else 'wrapperbase.flags',
        'calling_convention': convention, 'implementation_formal_roles': formals,
        'alternative_carrier_role_conditions': roles,
        'source_call_prefix': 'UNRESOLVED_UNLESS_SEPARATELY_ESTABLISHED',
        'argument_expansions': 'OPEN' if any(kind in ('STARRED', 'DOUBLE_STARRED')
                                          for kind, _ in shape.arguments) else 'EXPLICIT_SOURCE_PORTS',
        'applicability_conditions': ['ORIGINAL_CALLABLE_CARRIER_AND_FLAGS_STILL_MATCH',
            'SOURCE_TO_DISPATCHER_ARGUMENT_LAYOUT_VALID', 'ADAPTER_REACHES_IMPLEMENTATION'],
        'possible_preimplementation_failures': ['RECEIVER_OR_ARGUMENT_CHECK',
            'KEYWORD_OR_ARITY_CHECK', 'RECURSION_CHECK', 'ARGUMENT_EXPANSION_OR_PACKING'],
        'arity_used_to_prune_paths': False, 'implementation_entry_observed': False,
        'physical_packing_observed': False, 'effects_complete': False,
        'normal_return_observed': False}


def build_native_protocol(shape):
    """Build a validated shared graph from a shape; perform no I/O or target call."""
    shape_document = _shape(shape)
    key = native_protocol_key(shape)
    prefix = 'cpython-native-protocol-v1:' + key
    region, provider = RegionID(prefix), ProviderID(prefix + ':provider')
    entry, normal, failed = (BlockID(prefix + ':' + name) for name in ('entry', 'normal', 'raised'))
    invoke, returned, raised = (OperationID(prefix + ':' + name) for name in ('dispatch', 'return', 'raise'))
    location = LocationID(prefix + ':world')
    labels = ('callable', *(f'explicit{i}' for i in range(len(shape.arguments))))
    before = [ReferenceValue(ValueID(prefix + ':' + label), region, BlockArgument(entry, i))
              for i, label in enumerate(labels)]
    before.append(StateVersionValue(ValueID(prefix + ':world.before'), region,
        BlockArgument(entry, len(before)), location))
    after = (ReferenceValue(ValueID(prefix + ':result'), region, BlockArgument(normal, 0)),
        StateVersionValue(ValueID(prefix + ':world.normal'), region, BlockArgument(normal, 1), location))
    error = (ReferenceValue(ValueID(prefix + ':exception'), region, BlockArgument(failed, 0)),
        StateVersionValue(ValueID(prefix + ':world.raised'), region, BlockArgument(failed, 1), location))

    def uses(operation, values):
        return tuple(Use(UseID(operation.value + ':use:' + str(i)), value.id,
            UseRole.STATE_CONTENT if type(value) is StateVersionValue else UseRole.REFERENCE)
            for i, value in enumerate(values))

    inputs, outputs, errors = uses(invoke, before), uses(returned, after), uses(raised, error)
    normal_types, error_types = tuple(map(value_type, after)), tuple(map(value_type, error))
    operations = (
        Operation(invoke, 'CPython callable adapter and open implementation dispatch',
            (Behavior.CONTROL, Behavior.READ, Behavior.WRITE), inputs, effects_complete=False,
            terminator=Terminator(TerminatorKind.INVOKE, (
                CompletionSuccessor(ExitKind.NORMAL, normal, (CompletionResult(0), CompletionResult(1))),
                CompletionSuccessor(ExitKind.RAISE, failed, (CompletionResult(0), CompletionResult(1))))),
            completions=(CompletionSignature(ExitKind.NORMAL, normal_types),
                         CompletionSignature(ExitKind.RAISE, error_types)),
            invoke_arguments=tuple(use.id for use in inputs)),
        Operation(returned, 'possible Python object normal completion', (Behavior.CONTROL,), outputs,
            terminator=Terminator(TerminatorKind.RETURN, exit='normal', values=tuple(use.id for use in outputs))),
        Operation(raised, 'possible adapter or implementation exception', (Behavior.CONTROL,), errors,
            terminator=Terminator(TerminatorKind.RAISE, exit='raised', values=tuple(use.id for use in errors))))
    declaration = {'schema': SCHEMA + '.definition', 'schema_version': PROTOCOL_VERSION,
                   'shape': shape_document, 'cabi_contract': _cabi_contract(shape)}
    declared = _json(declaration)
    # This is an inline declaration identity, not a fabricated disk/source
    # receipt. The same shape/contract is retained in the stored wrapper.
    artifact = ProviderArtifact('urn:scar:cpython-native-protocol:' + sha256(declared).hexdigest(),
        sha256(declared).hexdigest(), len(declared), declaration['schema'])
    fact = lambda suffix='': ProviderFactReference(artifact, '#' + suffix)
    envelope = ProviderEnvelope(provider, 'SCAR declared CPython callable protocol', '1',
        'CPython-3.14.7-interface-contract', artifact, ProviderArtifactKind.DEFINITION_GRAPH,
        ProviderCaptureMode.STATIC_ANALYSIS, None, (),
        (ProviderStage('declared Python-side interface', fact('/shape')),), (),
        tuple(ProviderCoverage(domain, Completeness.PARTIAL if domain in (
            ProviderCoverageDomain.STRUCTURE, ProviderCoverageDomain.DATAFLOW) else Completeness.UNKNOWN,
            fact() if domain in (ProviderCoverageDomain.STRUCTURE, ProviderCoverageDomain.DATAFLOW) else None,
            'Declared adapter boundary; runtime selection, implementation and effects remain open.')
            for domain in ProviderCoverageDomain),
        tuple(ProviderCollectionObservation(domain, None, 'No target execution or measurement.')
              for domain in ProviderCollectionDomain))
    boundary = NativeBoundary(NativeBoundaryID(prefix + ':boundary'), provider, region,
        fact('/shape'), None, None,
        tuple(NativeInputSlot(i, 'PYTHON_CALLABLE' if i == 0 else f'PYTHON_EXPLICIT_ARGUMENT:{i-1}',
            fact('/shape' if i == 0 else '/shape/arguments/' + str(i - 1)), EntryPortRef(region, value.id))
            for i, value in enumerate(before[:-1])),
        (NativeOutputSlot(0, 'POSSIBLE_PYTHON_OBJECT_RESULT', fact('/cabi_contract'),
                         ExitPortRef(region, 'normal', 0)),),
        (CoreInputPort(EntryPortRef(region, before[-1].id), 'Open world before adapter dispatch.'),),
        (CoreOutputPort(ExitPortRef(region, 'normal', 1), 'Open normal post-world.'),
         CoreOutputPort(ExitPortRef(region, 'raised', 0), 'Possible exception including preimplementation failure.'),
         CoreOutputPort(ExitPortRef(region, 'raised', 1), 'Open exceptional post-world.')))
    graph = ProgramGraph(region, (Region(region, 'shared CPython callable protocol', entry,
        (Block(entry, tuple(value.id for value in before), (invoke,)),
         Block(normal, tuple(value.id for value in after), (returned,)),
         Block(failed, tuple(value.id for value in error), (raised,))),
        (ExitPort('normal', ExitKind.NORMAL, normal_types), ExitPort('raised', ExitKind.RAISE, error_types))),),
        operations, tuple((*before, *after, *error)), (StateLocation(location, 'Open callable adapter state.'),),
        provider_envelopes=(envelope,),
        provider_regions=(ProviderRegion(provider, key, region, ProviderRegionRelation.DEFINES_REPRESENTATION),),
        provider_bindings=(ProviderBinding(provider, region,
            ProviderElement(ProviderElementKind.OPERATION, key), invoke),), native_boundaries=(boundary,))
    require_valid(graph)
    return graph


def _document(shape, graph):
    core = json.loads(dump_graph(graph))
    return {'schema': SCHEMA, 'schema_version': PROTOCOL_VERSION, 'shape': _shape(shape),
        'cabi_contract': _cabi_contract(shape), 'graph': core,
        'target_executed': False, 'transformation_authorized': False}


def native_protocol_document(shape):
    """Freshly derive the whole wrapper, including its unobserved contracts."""
    return _document(shape, build_native_protocol(shape))


def write_native_protocol(shape, fresh_path):
    """Store one deterministic gzip wrapper; never overwrite an existing file."""
    graph = build_native_protocol(shape)
    document = _document(shape, graph)
    path = Path(fresh_path).absolute()
    if path.resolve() != path or path.is_symlink() or path.exists() or path.suffix != '.gz':
        raise FileExistsError('native protocol output must be a fresh canonical gzip file')
    raw = _json(document)
    stored = gzip.compress(raw, compresslevel=3, mtime=0)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as stream:
        stream.write(stored)
    artifact = ProviderArtifact(str(path), sha256(stored).hexdigest(), len(stored), SCHEMA + '/1')
    locator = SourceArtifactLocator(artifact, sha256(raw).hexdigest(), len(raw),
                                    'gzip-canonical-json', '#/graph')
    core = document['graph']
    return locator, core['schema'] + '/' + str(core['schema_version']), graph


__all__ = ['NativeProtocolShape', 'build_native_protocol', 'write_native_protocol',
           'native_protocol_key', 'native_protocol_document', 'SCHEMA', 'PROTOCOL_VERSION']
