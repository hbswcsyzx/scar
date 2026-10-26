"""Owned local projections of original entry snapshots onto existing ports.

No caller actual route, FunctionObject, ObjectIdentity, logical version or full
ExecutionModel is created. Saved rows cannot reconstruct this live session.
"""
from __future__ import annotations

from collections import Counter
import json

from scar.analysis.function_interfaces import validate_body_interface
from scar.analysis.program_composition import QualifiedSourceBodyReference
from scar.ir.program.call_edges import ReferenceOccurrence, ReferenceRole
from scar.ir.program.functions import FunctionSignature
from scar.ir.record_codec import decode, encode
from .source_entry_routing_validation import require_code_layout, parameter_source, require_entry_routing

ENTRY_ROUTING_PROFILE = 'CALLEE_ENTRY_PARAMETER_ROUTING_V1'
_OWNER = object()


def _canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode()


class EntryRoutingSession:
    """Actual source-bound query/check session, not a serialized authority."""

    def __init__(self, key, composition, entries, captures, binding_rows, members):
        if key is not _OWNER: raise TypeError('entry routing needs the actual fresh source binder')
        self._composition, self._members = composition, members
        self._entries, self._captures = dict(entries), dict(captures)
        self._bindings = {(r['process_id'], r['code']): (i, json.loads(_canonical(r)))
                          for i, r in enumerate(binding_rows)}
        self._contexts = {}
        # One normal reader/static-layout lookup per code/body, never per event.
        for index, row in enumerate(binding_rows):
            body = row.get('body')
            if body is None: continue
            if body.get('kind') != 'QUALIFIED_SOURCE_BODY':
                continue  # Other body protocols remain in the explicit frontier denominator.
            reference = decode(QualifiedSourceBodyReference, body['reference'])
            typed = composition.typed_qualified_body(reference)
            item = composition._qualified_entry_item(reference)
            original = item['record']
            if (original['entry_key'] != item['entry'].key
                    or original['definition'] != encode(reference.definition)):
                raise ValueError('entry routing cached signature differs from original checked publication')
            signature = decode(FunctionSignature, original['signature'])
            validate_body_interface(typed.body, typed.interface, signature)
            if (encode(reference.definition) != row['definition'] or body != composition.qualified_body_record(reference)
                    or typed.interface.definition != reference.definition.definition):
                raise ValueError('entry routing changes original code/source/body/definition')
            descriptor = captures[row['process_id'], row['code']].code
            require_code_layout(descriptor, signature)
            self._contexts[index] = {'reference': encode(reference), 'namespace': typed.namespace,
                'signature': signature, 'by_name': {p.name: p for p in signature.parameters},
                'ports': {p.slot: p for p in typed.interface.parameters},
                'positions': {p.slot: i for i, p in enumerate(signature.parameters)}}
        rows = []
        for entry in sorted(entries.values(), key=lambda e: (e.invocation.process_id, e.anchor.index)):
            index, binding = self._bindings[entry.invocation.process_id, entry.code]
            context = self._contexts.get(index)
            fact = members.fact(entry.anchor, entry.invocation.process_id)
            point = members.point(entry.anchor, entry.invocation.process_id)
            reasons = []
            if not entry.parameters_complete: reasons.append('ENTRY_PARAMETERS_INCOMPLETE')
            if entry.suspended: reasons.append('SUSPENDED_ENTRY_UNSUPPORTED')
            if point is None: reasons.append('ENTRY_PROCESS_MEMBERSHIP_UNRESOLVED')
            if not binding['complete_descriptor_match']: reasons.append('COMPLETE_CODE_SOURCE_WITNESS_UNAVAILABLE')
            if context is None: reasons.append('QUALIFIED_CANONICAL_BODY_UNAVAILABLE')
            parameters = []
            for ordinal, observed in enumerate(entry.parameters):
                parameter = None if reasons else context['by_name'][observed.name]
                port = None if parameter is None else context['ports'][parameter.slot]
                occurrence = ReferenceOccurrence(entry.anchor, entry.invocation, entry.invocation,
                    ReferenceRole.PARAMETER, observed.name, observed.ref,
                    None if parameter is None else parameter.source, core_value=None if port is None else port.value)
                parameters.append({'ordinal': ordinal,
                    'formal_position': None if parameter is None else context['positions'][parameter.slot],
                    'formal_slot': None if parameter is None else encode(parameter.slot),
                    'formal_kind': None if parameter is None else parameter.kind.value,
                    'occurrence': encode(occurrence), 'source': encode(parameter_source(fact, ordinal))})
            rows.append({'kind': 'CALLEE_ENTRY_PARAMETERS', 'invocation': encode(entry.invocation),
                'anchor': encode(entry.anchor), 'code': entry.code, 'source_binding_index': index,
                'point': encode(point), 'source': encode(fact),
                'qualified_body': None if context is None else context['reference'],
                'namespace': None if context is None else context['namespace'],
                'status': 'FRONTIER' if reasons else 'QUALIFIED_CALLEE_ENTRY_SNAPSHOT',
                'frontiers': reasons, 'parameters': parameters})
        self.check_rows(rows)
        self._rows = _canonical(rows)

    def rows(self):
        return tuple(json.loads(self._rows))

    def check_rows(self, rows):
        # Guard the real body reader, then use independent original-row/port
        # predicates. Changed candidates receive semantic errors, not seal errors.
        for context in self._contexts.values():
            self._composition._qualified_entry_item(decode(QualifiedSourceBodyReference, context['reference']))
        require_entry_routing(rows, entries=self._entries, captures=self._captures,
            bindings=self._bindings, contexts=self._contexts, members=self._members)

    def summary(self):
        rows = self.rows()
        qualified = [r for r in rows if r['status'] == 'QUALIFIED_CALLEE_ENTRY_SNAPSHOT']
        return {'profile': ENTRY_ROUTING_PROFILE, 'invocations': len(rows),
            'observed_parameter_occurrences': sum(len(r['parameters']) for r in rows),
            'qualified_entry_invocations': len(qualified),
            'qualified_formal_ports': sum(len(r['parameters']) for r in qualified),
            'frontier_invocations': len(rows) - len(qualified),
            'frontiers': dict(Counter(g for r in rows for g in r['frontiers'])),
            'caller_actual_expression_routing_established': False, 'object_identity_established': False,
            'logical_contents_established': False, 'full_execution_model_established': False,
            'function_environment_state_ready_established': False,
            'reference_tokens_are_occurrence_carriers_not_object_count': True}


def _make_entry_routing(composition, entries, captures, bindings, members):
    return EntryRoutingSession(_OWNER, composition, entries, captures, bindings, members)
