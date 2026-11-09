"""Connect derived call inputs to original receipt-bound source interfaces.

The parent supplies a syntactic may-dependency from its root formal. That
dependency never becomes an alias between the root and a derived actual.
Function bodies remain shared and are not entered by this adapter.
"""
from collections import defaultdict

from scar.analysis.source_reference_consumers import argument_points, bind_consumer_interface
from scar.analysis.source_reference_slice import ReferenceSlicer, source_port
from scar.analysis.source_template_links import _json
from scar.ir.program import normal_targets as T, reference_consumers as R, source_value_interfaces as V
from scar.ir.record_codec import encode


_CONDITIONS = (
    'PARENT_SOURCE_VALUE_REACH_MAY_DEPENDENCY_SELECTED',
    'ROOT_TO_DERIVED_ACTUAL_REFERENCE_IDENTITY_NOT_ESTABLISHED',
    'HISTORICAL_TARGET_IS_MAY_ALTERNATIVE_NOT_MATCHED_CALLER_CONTEXT',
    'ARGUMENT_VALUE_IS_NOT_EFFECT_OR_ESCAPE_SUMMARY',
    'NO_CONTENT_PRESERVATION_OR_RUNTIME_DISPATCH_PROOF',
)


def _index(rows, ordinal):
    if type(ordinal) is not int or not 0 <= ordinal < len(rows):
        raise ValueError('value interface index is outside its original parent table')
    return rows[ordinal]


def _original_call(slicer, unit, record):
    prefix = slicer.fact(unit, 'calls', 0).locator.rsplit('/', 1)[0] + '/'
    locator = record.fact.locator
    if not locator.startswith(prefix):
        raise ValueError('value interface call reference differs from its original source table')
    suffix = locator[len(prefix):]
    if not suffix.isascii() or not suffix.isdecimal() or str(int(suffix)) != suffix:
        raise ValueError('value interface call needs its canonical original row ordinal')
    ordinal = int(suffix)
    call = _index(unit.calls, ordinal)
    if record.call != call or record.fact != slicer.fact(unit, 'calls', ordinal):
        raise ValueError('value interface body call changed its original fact or artifact receipt')
    return call


def connect_value_interfaces(snapshot, bodies, reaches):
    """Join every parent call input using one complete historical calls scan.

    ``SourceConsumerBinding.use`` and frontier.use index the returned uses.
    ``ReferenceArgumentUse.node`` and frontier.node are parent reach ordinals,
    not world-return node indices. No body entry, caller-context admission or
    root-to-actual reference equality is inferred. The caller retains snapshot
    parent guards and is responsible for its final validate_parents() check.
    """
    slicer = ReferenceSlicer(snapshot)
    uses = []; sites = []; wanted = set(); wanted_units = set(); body_calls = {}
    for reach_ordinal, reach in enumerate(reaches):
        body = _index(bodies, reach.body)
        if reach.formal.unit != body.body.unit or body.source_function.unit != body.body.unit:
            raise ValueError('value interface reach formal belongs to a different source body')
        slicer.local(reach.formal)
        provider, function_port = slicer.local(body.source_function)
        function = next((f for f in provider.functions if f.value == function_port), None)
        if (function is None or T.Body(provider.unit, function.template, function.body) != body.body
                or reach.formal not in tuple(source_port(provider, p) for p in function.formals[1:-1])):
            raise ValueError('value interface root is not an original parameter of its source function')
        if reach.body not in body_calls:
            unit, *_ = slicer.unit(body.body.unit)
            records = {}
            for record in body.calls:
                call = _original_call(slicer, unit, record)
                if record.fact in records and records[record.fact] != call:
                    raise ValueError('value interface body has conflicting original call records')
                records[record.fact] = call
            body_calls[reach.body] = unit, records
        unit, records = body_calls[reach.body]
        for input_ordinal, value in enumerate(reach.call_inputs):
            if value.call not in records:
                raise ValueError('dependent call input has no exact original SourceBodyCall reference')
            call = records[value.call]
            try:
                role = R.ArgumentRole(value.role)
            except (TypeError, ValueError) as error:
                raise ValueError('dependent call input has an unknown original argument role') from error
            if type(value.ordinal) is not int or not any(
                    role is expected_role and value.ordinal == ordinal and value.keyword == keyword
                    and value.actual == source_port(unit, local)
                    for expected_role, ordinal, keyword, local in argument_points(call)):
                raise ValueError('dependent call input differs from its original actual, role, position or keyword')
            before, after = source_port(unit, call.world), source_port(unit, call.result_world)
            conditions = tuple(dict.fromkeys((*reach.conditions, *_CONDITIONS)))
            use = R.ReferenceArgumentUse(reach_ordinal, value.call, role, value.ordinal, value.keyword,
                value.actual, (), False, before, after, conditions)
            uses.append(V.SourceValueInterfaceUse(reach_ordinal, input_ordinal, use))
            result = source_port(unit, call.result)
            sites.append((call, result, source_port(unit, call.callee)))
            wanted.add(_json(encode(result))); wanted_units.add(unit.unit)

    targets = defaultdict(list)
    # Decode only wanted records while RelationSnapshot checks both complete
    # receipts. All reaches and call inputs share this single original scan.
    for _, link, evidence in snapshot.rows('calls', lambda wire:
            wire['result']['unit'] in wanted_units and _json(wire['result']) in wanted, T.CallLink):
        targets[link.result].append((link, evidence))
    bindings = []; frontiers = []
    for use_ordinal, item in enumerate(uses):
        use = item.use
        call, result, callee = sites[use_ordinal]
        matched = False
        for link, evidence in targets.get(result, ()):
            if link.result != result or link.callee != callee:
                continue
            matched = True
            records, reason = bind_consumer_interface(slicer, use_ordinal, use, call, link, evidence)
            bindings.extend(records)
            if reason is not None:
                frontiers.append(R.ConsumerFrontier(item.reach, use_ordinal, use.actual, evidence, reason))
        if not matched:
            frontiers.append(R.ConsumerFrontier(item.reach, use_ordinal, use.actual, None,
                'HISTORICAL_CALL_TARGET_INTERFACE_UNRESOLVED'))
    return V.SourceValueInterfaceGraph(tuple(uses), tuple(bindings), tuple(frontiers))
