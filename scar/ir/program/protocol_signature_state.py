"""Check original state wires against an explicitly selected protocol policy.

The caller first validates/instantiates the finite port signature. This query
checks its correspondence to existing values and accesses; it does not select
a rule, establish parameter provenance, or authorize effects or a rewrite.
UNKNOWN footprints are retained for world transitions, rather than promoted
to WHOLE. Cleanup domain transitions have their separate WHOLE requirement.
"""
from collections.abc import Mapping

from scar.ir.record_codec import encode

from .ids import LocationID, OperationID, UseID, ValueID
from .model import (
    AccessMode, CompletionSignature, DataValue, ExitKind, Footprint, FootprintKind, LocalBindingValue,
    Operation, OperationResult, ProtocolValue, ReferenceValue, StateAccess,
    StateVersionValue, Terminator, TerminatorKind, Use, Value, ValueKind,
    ValueType, value_type,
)
from .protocol_signatures import ProtocolStatePolicy
from .signature_patterns import (
    ResolvedCompletion, ResolvedSignature, SignatureError, SignatureForm,
)


def _require(condition, code, path, detail):
    if not condition:
        raise SignatureError(code, path, detail)


def _states(types, path):
    """Return an ordered, trailing state suffix, with no hidden earlier state."""
    positions = tuple(i for i, item in enumerate(types)
                      if type(item) is ValueType and item.kind is ValueKind.STATE)
    _require(not positions or positions == tuple(range(positions[0], len(types))),
             'STATE_SUFFIX', path, 'state ports must form the trailing suffix')
    return positions


def validate_protocol_state(
    operation: Operation,
    values: Mapping[ValueID, Value],
    signature: ResolvedSignature,
    policy: ProtocolStatePolicy,
) -> dict:
    """Validate state relations without interpreting labels or use roles.

    ``signature`` must already pass ``validate_resolved_signature``. The
    selected policy and its parameters come from the caller's declaration,
    never from the observed arity. All receipts retain original accesses and
    the original ``effects_complete`` fact without extending proof scope.
    """
    path = 'operation'
    try:
        _require(type(operation) is Operation, 'OPERATION_TYPE', path,
                 'expected exact Operation')
        _require(type(operation.id) is OperationID, 'OPERATION_ID', path + '.id',
                 'expected exact OperationID')
        path = operation.id.wire
        _require(isinstance(values, Mapping), 'VALUE_MAP', path,
                 'expected a mapping of original values')
        _require(type(signature) is ResolvedSignature, 'SIGNATURE_TYPE', path,
                 'expected a validated ResolvedSignature')
        _require(type(policy) is ProtocolStatePolicy, 'STATE_POLICY', path,
                 'expected exact ProtocolStatePolicy')
        _require(policy is not ProtocolStatePolicy.UNIMPLEMENTED,
                 'UNIMPLEMENTED_STATE_POLICY', path, 'this rule has no state policy')
        _require(type(operation.effects_complete) is bool, 'EFFECT_FACT', path,
                 'effects_complete must retain an exact boolean fact')
        for field in ('uses', 'results', 'accesses', 'invoke_arguments', 'completions'):
            _require(type(getattr(operation, field)) is tuple, 'OPERATION_FIELD',
                     path + '.' + field, 'expected the original tuple field')

        uses = {}
        for i, use in enumerate(operation.uses):
            at = path + f'.uses[{i}]'
            _require(type(use) is Use and type(use.id) is UseID
                     and type(use.value) is ValueID, 'USE_RECORD', at,
                     'expected an exact original Use and value ID')
            _require(use.id not in uses, 'DUPLICATE_USE', at, 'use ID repeats')
            uses[use.id] = use

        def original_value(identity, at):
            _require(type(identity) is ValueID, 'VALUE_ID', at,
                     'expected exact ValueID')
            try:
                value = values[identity]
            except KeyError as error:
                raise SignatureError('MISSING_VALUE', at, identity.wire) from error
            _require(type(value) in (DataValue, ReferenceValue, StateVersionValue,
                                    LocalBindingValue, ProtocolValue)
                     and type(value.id) is ValueID and value.id == identity,
                     'VALUE_RECORD', at, 'mapping must retain the original typed value')
            return value

        def match_types(expected, records, at):
            _require(type(expected) is tuple and len(expected) == len(records),
                     'PORT_ARITY', at, 'original and declared port counts differ')
            for i, (wanted, value) in enumerate(zip(expected, records)):
                actual = value_type(value)
                _require(type(actual) is type(wanted) and actual == wanted,
                         'PORT_TYPE', at + f'[{i}]', 'original and declared types differ')

        is_invoke = (type(operation.terminator) is Terminator
                     and operation.terminator.kind is TerminatorKind.INVOKE)
        _require((signature.form is SignatureForm.INVOKE) == is_invoke,
                 'INTERFACE_FORM', path, 'declared and original forms differ')
        if signature.form is SignatureForm.INVOKE:
            _require(policy is ProtocolStatePolicy.INVOKE_WORLD,
                     'STATE_POLICY_FORM', path, 'INVOKE needs its explicit world policy')
            _require(not operation.results and not operation.accesses,
                     'INVOKE_ORDINARY_STATE', path,
                     'INVOKE cannot define ordinary results or state accesses')
            ordered_uses = []
            for i, identity in enumerate(operation.invoke_arguments):
                _require(type(identity) is UseID, 'USE_ID',
                         path + f'.invoke_arguments[{i}]', 'expected exact UseID')
                try:
                    ordered_uses.append(uses[identity])
                except KeyError as error:
                    raise SignatureError('MISSING_USE', path + '.invoke_arguments',
                                         identity.wire) from error
            _require(len(set(operation.invoke_arguments)) == len(operation.invoke_arguments),
                     'DUPLICATE_USE', path + '.invoke_arguments', 'argument use repeats')
        else:
            _require(signature.form is SignatureForm.ORDINARY
                     and operation.terminator is None and operation.callee is None,
                     'INTERFACE_FORM', path, 'expected a local ordinary operation')
            _require(policy is not ProtocolStatePolicy.INVOKE_WORLD
                     and not operation.completions and not operation.invoke_arguments,
                     'STATE_POLICY_FORM', path, 'ordinary form cannot carry INVOKE ports')
            ordered_uses = operation.uses

        arguments = tuple(original_value(use.value, path + f'.arguments[{i}]')
                          for i, use in enumerate(ordered_uses))
        match_types(signature.arguments, arguments, path + '.arguments')
        input_states = _states(signature.arguments, path + '.arguments')
        for i in input_states:
            _require(type(arguments[i]) is StateVersionValue
                     and type(arguments[i].location) is LocationID,
                     'STATE_VALUE', path + f'.arguments[{i}]',
                     'state input must be an original StateVersionValue')
        results = tuple(original_value(identity, path + f'.results[{i}]')
                        for i, identity in enumerate(operation.results))
        output_states, completion_flow = (), []
        if not is_invoke:
            match_types(signature.results, results, path + '.results')
            output_states = _states(signature.results, path + '.results')
            _require(len(set(operation.results)) == len(operation.results),
                     'DUPLICATE_RESULT', path + '.results', 'result ID repeats')
            for i in output_states:
                value = results[i]
                _require(type(value) is StateVersionValue
                         and type(value.location) is LocationID
                         and type(value.origin) is OperationResult
                         and value.origin == OperationResult(operation.id, i),
                         'STATE_RESULT', path + f'.results[{i}]',
                         'state result must retain its original producer ordinal')

        for i, access in enumerate(operation.accesses):
            at = path + f'.accesses[{i}]'
            _require(type(access) is StateAccess
                     and type(access.location) is LocationID
                     and type(access.before) is UseID
                     and (access.after is None or type(access.after) is ValueID)
                     and (access.reference is None or type(access.reference) is UseID)
                     and type(access.mode) is AccessMode
                     and type(access.full_overwrite) is bool
                     and type(access.footprint) is Footprint
                     and type(access.footprint.kind) is FootprintKind,
                     'STATE_ACCESS', at, 'expected an exact original state access')
            # Validate footprint syntax without strengthening UNKNOWN to WHOLE.
            access.footprint.__post_init__()

        if policy is ProtocolStatePolicy.NO_STATE:
            _require(not input_states and not output_states and not operation.accesses,
                     'UNEXPECTED_STATE', path, 'NO_STATE forbids state ports and accesses')
        elif policy is ProtocolStatePolicy.INVOKE_WORLD:
            _require(len(input_states) == 1, 'WORLD_INPUT', path,
                     'INVOKE needs exactly one trailing state input')
            _require(signature.results is None, 'INVOKE_RESULTS', path,
                     'INVOKE has completion results only')
            _require(type(signature.completions) is tuple
                     and all(type(row) is ResolvedCompletion and type(row.kind) is ExitKind
                             for row in signature.completions)
                     and all(type(row) is CompletionSignature and type(row.kind) is ExitKind
                             for row in operation.completions),
                     'COMPLETION_RECORD', path + '.completions',
                     'expected original and resolved typed completion records')
            declared = {row.kind: row.types for row in signature.completions}
            actual = {row.kind: row.types for row in operation.completions}
            _require(len(declared) == len(signature.completions) == 2
                     and len(actual) == len(operation.completions) == 2
                     and set(declared) == set(actual) == {ExitKind.NORMAL, ExitKind.RAISE},
                     'COMPLETION_KINDS', path + '.completions',
                     'world policy requires unique NORMAL and RAISE completions')
            world = signature.arguments[input_states[0]]
            for kind in (ExitKind.NORMAL, ExitKind.RAISE):
                wanted, found = declared[kind], actual[kind]
                at = path + '.completions.' + kind.value
                _require(type(found) is tuple and len(wanted) == len(found)
                         and all(type(a) is type(b) and a == b for a, b in zip(wanted, found)),
                         'COMPLETION_TYPE', at, 'original completion types differ')
                positions = _states(wanted, at)
                _require(len(positions) == 1 and wanted[positions[0]] == world,
                         'COMPLETION_WORLD', at,
                         'completion must return the same trailing state domain')
                completion_flow.append(dict(kind=kind.value, index=positions[0],
                                            location=world.location.wire))
        else:
            multiple = policy is ProtocolStatePolicy.WRITE_DOMAINS
            _require(len(input_states) > 0 if multiple else len(input_states) == 1,
                     'STATE_INPUT_COUNT', path, 'policy state input count differs')
            locations = tuple(arguments[i].location for i in input_states)
            _require(len(set(locations)) == len(locations), 'DUPLICATE_STATE_DOMAIN', path,
                     'state domain inputs must be unique')
            if policy is ProtocolStatePolicy.READ_WORLD:
                _require(not output_states, 'READ_RESULT', path,
                         'READ_WORLD cannot produce a state result')
            else:
                _require(policy in (ProtocolStatePolicy.WRITE_WORLD,
                                    ProtocolStatePolicy.WRITE_DOMAINS),
                         'STATE_POLICY', path, 'unsupported explicit state policy')
                _require(tuple(results[i].location for i in output_states) == locations,
                         'STATE_OUTPUT_DOMAINS', path,
                         'state results must preserve the input domain order')
            _require(len(operation.accesses) == len(locations), 'STATE_ACCESS_COUNT', path,
                     'each declared state domain needs exactly one access')
            by_location = {access.location: access for access in operation.accesses}
            _require(len(by_location) == len(locations) and set(by_location) == set(locations),
                     'STATE_ACCESS_DOMAINS', path, 'access domains differ or repeat')
            for ordinal, (position, location) in enumerate(zip(input_states, locations)):
                access = by_location[location]
                at = path + '.accesses.' + location.wire
                _require(access.before == ordered_uses[position].id, 'STATE_BEFORE', at,
                         'access must read the original input Use')
                if policy is ProtocolStatePolicy.READ_WORLD:
                    _require(access.mode is AccessMode.READ and access.after is None
                             and access.full_overwrite is False, 'STATE_READ', at,
                             'world read must not define or overwrite a new state')
                else:
                    _require(access.mode is AccessMode.READ_WRITE
                             and access.after == results[output_states[ordinal]].id
                             and access.full_overwrite is False and access.reference is None,
                             'STATE_WRITE', at,
                             'transition must preserve the original before/after state wires')
                    if multiple:
                        _require(access.footprint.kind is FootprintKind.WHOLE,
                                 'CLEANUP_FOOTPRINT', at,
                                 'cleanup domain transitions require the original WHOLE footprint')

        return dict(
            operation=operation.id.wire, policy=policy.value,
            state_flow=dict(
                inputs=[dict(index=i, use=ordered_uses[i].id.wire,
                             value=arguments[i].id.wire, location=arguments[i].location.wire)
                        for i in input_states],
                results=[dict(index=i, value=results[i].id.wire,
                              location=results[i].location.wire) for i in output_states],
                completions=completion_flow),
            accesses=[encode(access) for access in operation.accesses],
            effects_complete=operation.effects_complete,
            state_relations_checked=True, source_effects_checked=False,
            use_roles_checked=False, transformation_authorized=False)
    except SignatureError:
        raise
    except (KeyError, AttributeError, TypeError, ValueError, IndexError) as error:
        raise SignatureError('MALFORMED_STATE_RECORD', path,
                             f'invalid or missing state record: {type(error).__name__}') from error


__all__ = ['validate_protocol_state']
