"""Independent checks of local entry snapshots against original formal ports.

These checks do not authorize caller actual-expression routes or object/content
identities. A live binder supplies original typed observations and body readers.
"""
from __future__ import annotations

import json

from scar.ir.program.call_edges import ReferenceOccurrence, ReferenceRole
from scar.ir.program.functions import ParameterKind, FunctionKind
from scar.ir.program.providers import ProviderFactReference
from scar.ir.record_codec import encode


class EntryRoutingError(ValueError):
    pass


def _same(actual, expected):
    # Transport equality is exact JSON equality, including bool versus int;
    # Python container equality alone would erase that distinction.
    try:
        options = dict(sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(',', ':'))
        return json.dumps(actual, **options) == json.dumps(expected, **options)
    except (ValueError, TypeError):
        return False


def require_code_layout(descriptor, signature):
    """CPython code layout differs from the source signature's canonical order."""
    ranks = {ParameterKind.POSITIONAL_ONLY: 0, ParameterKind.POSITIONAL: 0,
             ParameterKind.KEYWORD_ONLY: 1, ParameterKind.VAR_POSITIONAL: 2,
             ParameterKind.VAR_KEYWORD: 3}
    expected = tuple(p.name for p in sorted(signature.parameters, key=lambda p: ranks[p.kind]))
    if descriptor.parameters != expected:
        raise EntryRoutingError('entry_code_layout: captured names differ from exact source kinds/order')
    for kind, flag in ((ParameterKind.VAR_POSITIONAL, 4), (ParameterKind.VAR_KEYWORD, 8)):
        if bool(descriptor.flags & flag) != any(p.kind is kind for p in signature.parameters):
            raise EntryRoutingError('entry_code_layout: captured variadic flags differ from source signature')
    kind = (FunctionKind.ASYNC_GENERATOR if descriptor.flags & 0x200 else
            FunctionKind.ASYNC if descriptor.flags & 0x80 else
            FunctionKind.GENERATOR if descriptor.flags & 0x20 else FunctionKind.SYNC)
    if kind is not signature.kind:
        raise EntryRoutingError('entry_code_layout: captured function kind differs from source signature')


def parameter_source(fact, ordinal):
    return ProviderFactReference(fact.artifact, fact.locator + '/parameters/' + str(ordinal))


def entry_routing_errors(rows, *, entries, captures, bindings, contexts, members):
    """Check the entire actual denominator, without accepting a scope/hash seal.

    contexts originate in the ordinary qualified body reader. No serialized
    result or caller boolean reconstructs the binder's live session.
    """
    errors = []

    def check(condition, code, path, message):
        if not condition: errors.append((code, path, message))
        return condition

    if type(rows) not in (tuple, list):
        return [('entry_inventory', '#', 'entry projection must be an ordered row vector')]
    ordered = sorted(entries.values(), key=lambda e: (e.invocation.process_id, e.anchor.index))
    if len(rows) != len(ordered):
        return [('entry_inventory', '#', 'projection omits or adds original invocations')]
    top_fields = {'kind', 'invocation', 'anchor', 'code', 'source_binding_index', 'point',
                  'source', 'qualified_body', 'namespace', 'status', 'frontiers', 'parameters'}
    fields = {'ordinal', 'formal_position', 'formal_slot', 'formal_kind', 'occurrence', 'source'}
    for number, (row, entry) in enumerate(zip(rows, ordered, strict=True)):
        path = '#/' + str(number)
        if not check(type(row) is dict and set(row) == top_fields, 'entry_fields', path,
                     'entry projection has missing/extra fields'): continue
        binding_index, binding = bindings[entry.invocation.process_id, entry.code]
        context = contexts.get(binding_index)
        descriptor = captures[entry.invocation.process_id, entry.code].code
        fact = members.fact(entry.anchor, entry.invocation.process_id)
        point = members.point(entry.anchor, entry.invocation.process_id)
        check(_same(row['kind'], 'CALLEE_ENTRY_PARAMETERS') and _same(row['invocation'], encode(entry.invocation))
              and _same(row['anchor'], encode(entry.anchor)) and _same(row['code'], entry.code)
              and type(row['source_binding_index']) is int and row['source_binding_index'] == binding_index,
              'entry_identity', path, 'projection lost its exact original invocation/row/code')
        check(_same(row['source'], encode(fact)) and _same(row['point'], encode(point)),
              'entry_source', path, 'entry point is not the exact coordinate-bound raw fact')
        reasons = []
        if not entry.parameters_complete: reasons.append('ENTRY_PARAMETERS_INCOMPLETE')
        if entry.suspended: reasons.append('SUSPENDED_ENTRY_UNSUPPORTED')
        if point is None: reasons.append('ENTRY_PROCESS_MEMBERSHIP_UNRESOLVED')
        if not binding['complete_descriptor_match']: reasons.append('COMPLETE_CODE_SOURCE_WITNESS_UNAVAILABLE')
        if context is None: reasons.append('QUALIFIED_CANONICAL_BODY_UNAVAILABLE')
        eligible = not reasons
        check(_same(row['frontiers'], reasons) and _same(row['status'], 'QUALIFIED_CALLEE_ENTRY_SNAPSHOT' if eligible else 'FRONTIER'),
              'entry_qualification', path, 'entry qualification/frontier differs from original evidence')
        check(_same(row['qualified_body'], None if context is None else context['reference'])
              and _same(row['namespace'], None if context is None else context['namespace']),
              'entry_namespace', path, 'formal port lost its original qualified body/namespace')
        if entry.parameters_complete:
            check(tuple(p.name for p in entry.parameters) == descriptor.parameters,
                  'entry_parameter_names', path, 'complete entry names differ from captured descriptor')
        if context is not None: require_code_layout(descriptor, context['signature'])
        if not check(type(row['parameters']) is list and len(row['parameters']) == len(entry.parameters),
                     'entry_parameter_inventory', path, 'entry parameter vector was omitted/expanded'): continue
        for ordinal, (projected, observed) in enumerate(zip(row['parameters'], entry.parameters, strict=True)):
            slot_path = path + '/parameters/' + str(ordinal)
            if not check(type(projected) is dict and set(projected) == fields,
                         'entry_parameter_fields', slot_path, 'parameter has missing/extra fields'): continue
            parameter = None if not eligible else context['by_name'].get(observed.name)
            if eligible and not check(parameter is not None, 'entry_parameter_name', slot_path,
                                      'captured formal is absent from exact source signature'): continue
            position = None if parameter is None else context['positions'][parameter.slot]
            port = None if parameter is None else context['ports'][parameter.slot]
            expected = ReferenceOccurrence(entry.anchor, entry.invocation, entry.invocation,
                ReferenceRole.PARAMETER, observed.name, observed.ref,
                None if parameter is None else parameter.source, core_value=None if port is None else port.value)
            check(type(projected['ordinal']) is int and projected['ordinal'] == ordinal
                  and _same(projected['occurrence'], encode(expected)),
                  'entry_parameter_occurrence', slot_path, 'parameter reference/name/owner/core value differs from original entry')
            check(_same(projected['formal_position'], position)
                  and _same(projected['formal_slot'], None if parameter is None else encode(parameter.slot))
                  and _same(projected['formal_kind'], None if parameter is None else parameter.kind.value),
                  'entry_parameter_port', slot_path, 'parameter selected another formal slot/kind/order')
            check(_same(projected['source'], encode(parameter_source(fact, ordinal))),
                  'entry_parameter_source', slot_path, 'parameter source selects another original ordered observation')
    return errors


def require_entry_routing(rows, **original):
    errors = entry_routing_errors(rows, **original)
    if errors:
        raise EntryRoutingError('; '.join(code + ' at ' + path + ': ' + message for code, path, message in errors))
