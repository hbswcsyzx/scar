"""Captured suffix/caller/prefix paths of two exact synchronous calls."""
from dataclasses import replace

from scar.ir.execution.calls import CallActivation
from scar.ir.execution.common import Unresolved
from scar.ir.execution.coordinates import OccurrencePhase, OccurrencePoint
from scar.ir.execution.ids import CallActivationID
from scar.ir.program.ids import BlockID
from scar.ir.program.model import ExitKind, StateVersionValue
from scar.ir.program.validation import require_valid
from tests.fixtures.execution_call_graphs import _model
from tests.fixtures.program_call_effect_expansion_graphs import (
    call_effect_expansion_program, ordinary_call_effect_expansion_program,
)


def call_effect_expansion_execution(*, raised=False, outer_complete=True, expanded=True,
                                    interval_write=False, opaque=False,
                                    missing=None, instances=2):
    """The two children have one shared definition, distinct actual identities.

    A missing future prefix completion is different from a missing completion
    on the first child's required return. No change rebinds a sibling's ports.
    """
    allowed = (None, 'association', 'transfer', 'use',
               'prefix-completion', 'suffix-completion')
    if missing not in allowed:
        raise ValueError('unknown finite capture omission')
    graph, static = call_effect_expansion_program(outer_complete=outer_complete,
        expanded=expanded, interval_write=interval_write, opaque=opaque)
    require_valid(graph)
    kind = ExitKind.RAISE if raised else ExitKind.NORMAL
    terminal = static['child_terminals'][kind]
    terminal_block = next(block for block in static['child'].blocks if terminal.id in block.operations)
    child_path = ((static['child'].entry, int(raised)), (terminal_block.id, None))
    paths = tuple(path for instance in range(instances) for path in (
        (graph.root, static['caller_paths'][kind], f'expansion.{instance}.caller'),
        (static['child'].id, child_path, f'expansion.{instance}.child.0'),
        (static['child'].id, child_path, f'expansion.{instance}.child.1')))
    model, scopes, evidence = _model(graph, paths)
    examples, links = [], []
    for instance in range(instances):
        parent, first, second = scopes[instance * 3:instance * 3 + 3]
        calls = tuple(CallActivation(CallActivationID(f'expansion.{instance}.call.{ordinal}'),
            parent[2][definition.id], child[0], child[1][0], child[2][terminal.id], evidence)
            for ordinal, (definition, child) in enumerate(zip(static['calls'], (first, second))))
        links.extend(calls)
        examples.append({'parent': parent, 'children': (first, second),
            'links': calls, 'original_links': calls,
            'start': OccurrencePoint(first[2][static['source'].id], OccurrencePhase.AFTER),
            'end': OccurrencePoint(second[2][static['target'].id], OccurrencePhase.BEFORE),
            'prefix': second[2][static['prefix'].id],
            'outside_writes': (first[2][static['source'].id], second[2][static['source'].id])})
    model = replace(model, call_activations=tuple(links))
    if missing is not None:
        example = examples[0]
        if missing == 'association':
            omitted = example['links'][1]
            model = replace(model, call_activations=tuple(row for row in model.call_activations if row.id != omitted.id))
        elif missing == 'transfer':
            omitted = example['children'][0][2][static['branch'].id]
            model = replace(model, transfers=tuple(row for row in model.transfers if row.operation != omitted))
        elif missing == 'use':
            definition = static['calls'][1]
            values = {row.id: row for row in graph.values}
            omitted = next(use.id for use in definition.uses if use.id in definition.invoke_arguments
                and type(values[use.value]) is StateVersionValue and values[use.value].location == static['world'])
            model = replace(model, uses=tuple(row for row in model.uses
                if (row.operation, row.use) != (example['links'][1].caller, omitted)))
        else:
            ordinal = int(missing == 'prefix-completion')
            original = example['links'][ordinal]
            point = next(row.entry for row in model.activations if row.id == original.activation)
            changed = replace(original, completion=Unresolved('this exact completion was not captured', point))
            model = replace(model,
                operations=tuple(row for row in model.operations if row.id != original.completion),
                uses=tuple(row for row in model.uses if row.operation != original.completion),
                call_activations=tuple(changed if row.id == changed.id else row for row in model.call_activations))
            examples[0] = {**example, 'links': tuple(changed if row.id == changed.id else row for row in example['links'])}
    return graph, model, {'static': static, 'examples': tuple(examples), 'kind': kind,
                         'missing': missing, 'evidence': evidence}


def ordinary_call_effect_expansion_execution(*, future_missing=False):
    """One caller and the original counter implementation's two activations."""
    graph, static = ordinary_call_effect_expansion_program()
    require_valid(graph)
    child = static['calls'][0].callee
    model, scopes, evidence = _model(graph, (
        (graph.root, ((BlockID('caller.entry'), None),), 'ordinary.caller'),
        (child, ((BlockID('callee.entry'), None),), 'ordinary.first'),
        (child, ((BlockID('callee.entry'), None),), 'ordinary.second')))
    parent, first, second = scopes
    links = tuple(CallActivation(CallActivationID(f'ordinary.call.{ordinal}'),
        parent[2][definition.id], scope[0], scope[1][0], scope[2][static['terminal'].id], evidence)
        for ordinal, (definition, scope) in enumerate(zip(static['calls'], (first, second))))
    model = replace(model, call_activations=links)
    if future_missing:
        original = links[1]
        point = next(row.entry for row in model.activations if row.id == original.activation)
        absent = Unresolved('future completion/result lies after the requested prefix', point)
        changed = replace(original, completion=absent)
        outputs = {row.id for row in model.values if row.origin == original.caller}
        model = replace(model,
            operations=tuple(row for row in model.operations if row.id != original.completion),
            values=tuple(row for row in model.values if row.id not in outputs),
            uses=tuple(replace(row, value=absent) if row.value in outputs else row
                for row in model.uses if row.operation != original.completion),
            call_activations=(links[0], changed))
        links = (links[0], changed)
    return graph, model, {'static': static, 'parent': parent, 'children': (first, second),
        'links': links,
        'start': OccurrencePoint(first[2][static['source'].id], OccurrencePhase.AFTER),
        'end': OccurrencePoint(second[2][static['target'].id], OccurrencePhase.BEFORE),
        'future_missing': future_missing}


__all__ = ['call_effect_expansion_execution', 'ordinary_call_effect_expansion_execution']
