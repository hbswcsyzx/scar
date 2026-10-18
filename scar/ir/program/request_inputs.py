"""Joint static request/input recipes over original call and CFG ports.

No new producer, value identity or state chain is stored. These supplied-model
joins are conditional on source/call occurrence applicability, never cache or
transformation permissions.
"""
from scar.ir.execution.validity_budget import ValidityBudget
from scar.ir.literals import LiteralKind, PythonLiteral

from .input_origins import _input_origins_with_flow, _owned_use
from .control import ProtocolValueKind
from .model import LiteralOrigin, OperationResult, ProtocolValue, ReferenceValue
from .protocol_flow import ProtocolFlow


def _context(index, recipe, accounting, prefix=()):
    """Call-site context excludes differing argument ordinals; ports stay in recipes."""
    calls, choices = list(prefix), {}
    region = recipe['leaf'].region
    rooted = (calls[-1][2] == region if calls else region == index.graph.root)
    for step in recipe['path']:
        if not accounting.spend('request_context_steps', path='request_inputs.context'):
            return (), {}, False
        kind = step.get('kind')
        if kind == 'CALL_ACTUAL_TO_FORMAL':
            caller = step['caller']
            caller_region = index._blocks[index._operation_blocks[caller.id]]
            if caller_region != region:
                return (), {}, False
            calls.append((caller.id, caller_region, step['callee']))
            region = step['callee']
        elif kind == 'CFG_COPY':
            # A loop visit can select both edges at different times. It cannot
            # be compressed into one selected evaluation by a dict overwrite.
            key = (tuple(calls), step['operation'].id)
            previous = choices.get(key)
            selected = step['successor_index']
            if previous is not None and previous != selected:
                return tuple(calls), choices, False
            choices[key] = selected
    return tuple(calls), choices, rooted


def _none_content(recipe):
    """Only exact content declarations on an original Reference, not Data identity."""
    leaf = recipe['leaf']
    if not isinstance(leaf, ReferenceValue):
        return None
    if type(leaf.origin) is LiteralOrigin:
        return leaf.origin.value is None
    literals = tuple(row.literal for row in recipe['literal_evaluations']
                     if type(row.literal) is PythonLiteral)
    if len(literals) == 1:
        return literals[0].kind is LiteralKind.NONE
    return None


def request_input_binding(index, raw, input, ordinal=0, *, budget=4096, accounting=None, _flow=None):
    """Join a driver raw Use and a separate input Use through the same caller path.

    The raw pack's exact operand, its origin, and the input's origin must all
    agree in one complete supplied call-site context and compatible CFG choices.
    The original Uses differ; equal ValueIDs or equal literal contents alone
    never establish this join. Opaque computations and return summaries stop
    at their original producers. Dynamic visits and source identity stay open.
    """
    from .queries import ProgramIndex
    if type(index) is not ProgramIndex:
        raise TypeError('request_input_binding requires exact ProgramIndex')
    if type(ordinal) is not int or ordinal < 0:
        raise ValueError('request operand ordinal must be exact nonnegative int')
    raw_operation, raw_use = _owned_use(index, raw, 'raw')
    _, input_use = _owned_use(index, input, 'input')
    raw_value = index.values[raw_use.value]
    if not isinstance(raw_value, ProtocolValue) or raw_value.protocol is not ProtocolValueKind.RAW_DRIVER_REQUEST:
        raise ValueError('raw Use must carry the original RAW_DRIVER_REQUEST role')
    if not isinstance(index.values[input_use.value], ReferenceValue):
        raise ValueError('request operand input must be an original Reference Use')
    if accounting is None:
        accounting = ValidityBudget(budget)
    elif type(accounting) is not ValidityBudget or budget != 4096:
        raise TypeError('use one exact shared accounting budget or an integer budget')
    flow = ProtocolFlow(index.graph, budget=accounting) if _flow is None else _flow
    if type(flow) is not ProtocolFlow or flow.graph is not index.graph or flow.budget is not accounting:
        raise ValueError('request input query must share this exact graph and accounting flow')
    raw_view = _input_origins_with_flow(index, raw.operation, raw.use, accounting=accounting, _copy_flow=flow)
    input_view = _input_origins_with_flow(index, input.operation, input.use, accounting=accounting, _copy_flow=flow)
    bindings, gaps, cursor, operands = [], [], None, {}
    consumer_forward = None
    if raw_operation.callee is not None:
        arguments = (raw_operation.invoke_arguments if raw_operation.terminator is not None
                     else raw_operation.call_arguments)
        if raw_use.id in arguments:
            position = arguments.index(raw_use.id)
            formal = index.entry_arguments(raw_operation.callee)[position]
            consumer_forward = {'operation': raw_operation, 'actual': raw_use, 'formal': formal,
                'context': (raw_operation.id,
                    index._blocks[index._operation_blocks[raw_operation.id]], raw_operation.callee)}
    for raw_number, raw_recipe in enumerate(raw_view['recipes']):
        for request in raw_recipe['raw_requests']:
            definition = request['definition']
            if ordinal >= len(definition.operands):
                gaps.append({'code': 'request_ordinal_absent', 'definition': definition, 'ordinal': ordinal})
                continue
            if ordinal >= len(request['operands']):
                gaps.append({'code': 'request_operand_inventory_truncated', 'definition': definition,
                             'ordinal': ordinal})
                cursor = {'phase': 'request_operands', 'raw_recipe': raw_number,
                          'ordinal': ordinal, 'pair_enumeration_incomplete': True}
                break
            original = request['operands'][ordinal]
            owner, use = original['operation'], original['use']
            if owner is None or use is None or type(raw_recipe['leaf'].origin) is not OperationResult:
                gaps.append({'code': 'request_operand_producer_unresolved', 'definition': definition})
                continue
            if use.id not in operands:
                operands[use.id] = _input_origins_with_flow(index, owner.id, use.id,
                    accounting=accounting, _copy_flow=flow)
            for operand_number, operand_recipe in enumerate(operands[use.id]['recipes']):
                operand_calls, operand_choices, operand_rooted = _context(index, operand_recipe, accounting)
                raw_calls, raw_choices, raw_rooted = _context(index, raw_recipe, accounting, operand_calls)
                if not operand_rooted or not raw_rooted:
                    gaps.append({'code': 'request_pack_call_context_unresolved', 'definition': definition,
                                 'operand_use': use, 'raw_recipe': raw_number})
                    continue
                for input_number, input_recipe in enumerate(input_view['recipes']):
                    if not accounting.spend('request_input_pairs', path='request_inputs.pairs'):
                        cursor = {'raw_recipe': raw_number, 'operand_recipe': operand_number,
                                  'input_recipe': input_number, 'input_recipe_count': len(input_view['recipes']),
                                  'pair_enumeration_incomplete': True}
                        break
                    input_calls, input_choices, input_rooted = _context(index, input_recipe, accounting)
                    forwarded = (consumer_forward is not None
                                 and (*raw_calls, consumer_forward['context']) == input_calls)
                    if not input_rooted or (raw_calls != input_calls and not forwarded):
                        continue
                    if operand_recipe['leaf'].id != input_recipe['leaf'].id:
                        continue
                    choices = dict(operand_choices)
                    consistent = True
                    for key, selected in (*raw_choices.items(), *input_choices.items()):
                        if not accounting.spend('request_cfg_choices', path='request_inputs.cfg'):
                            consistent = False
                            break
                        if key in choices and choices[key] != selected:
                            consistent = False
                            break
                        choices[key] = selected
                    if not consistent:
                        continue
                    selected_recipes = (raw_recipe, operand_recipe, input_recipe)
                    if any(recipe['freshness'] is False for recipe in selected_recipes):
                        gaps.append({'code': 'request_input_old_evaluation', 'definition': definition,
                                     'raw_recipe': raw_number, 'input_recipe': input_number})
                        continue
                    bindings.append({'definition': definition, 'ordinal': ordinal,
                        'pack_operation': owner, 'operand': use, 'raw': raw, 'input': input,
                        'raw_recipe': raw_recipe, 'operand_recipe': operand_recipe, 'input_recipe': input_recipe,
                        'caller_context': input_calls, 'cfg_choices': tuple(choices.items()),
                        'raw_consumer_forward': consumer_forward if forwarded else None,
                        'declared_operand_is_none': _none_content(operand_recipe),
                        'status': 'DECLARED_SAME_SOURCE',
                        'runtime_identity_verified': False, 'source_runtime_verified': False,
                        'transformation_authorized': False})
                if cursor is not None or accounting.truncated:
                    break
            if cursor is not None or accounting.truncated:
                break
        if cursor is not None or accounting.truncated:
            break
    if not bindings:
        gaps.append({'code': 'request_input_binding_unresolved', 'raw': raw, 'input': input, 'ordinal': ordinal})
    if accounting.truncated and cursor is None:
        cursor = {'phase': 'origin_or_context', 'pair_enumeration_incomplete': True}
    gaps.extend((*raw_view['gaps'], *input_view['gaps']))
    for view in operands.values():
        gaps.extend(view['gaps'])
    return {'raw': raw_view, 'input': input_view, 'operand_origins': tuple(operands.values()),
        'bindings': tuple(bindings), 'gaps': tuple(gaps), 'cursor': cursor,
        'status': 'TRUNCATED' if accounting.truncated else 'PARTIAL' if gaps else 'DECLARED',
        'budget': {'limit': accounting.limit, 'used': accounting.used, 'costs': dict(accounting.costs),
                   'truncated': accounting.truncated},
        'caller_scope': 'SUPPLIED_STATIC_CALLERS_ONLY', 'caller_scope_complete': False,
        'source_runtime_verified': False, 'runtime_identity_verified': False,
        'transformation_authorized': False}
