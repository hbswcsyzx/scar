"""Original operation result interfaces; no new producers or wire records."""
from .model import (CompletionResult, ExitKind, InvokeLiteralResult, OperationResult,
                    StateVersionValue, TerminatorKind, ValueKind)
from .structured import ControlEdgeReference


def produced_slots(ctx, operation, leg):
    """Include states; signature ordinal is independent of landing position."""
    signature = leg['signature']
    if signature is not None:
        for slot, type_ in enumerate(signature.types):
            yield {'source': InvokeLiteralResult(leg['edge'], CompletionResult(slot)),
                   'slot': slot, 'type': type_}
    else:
        from .model import value_type
        for slot, identity in enumerate(operation.results):
            yield {'source': OperationResult(operation.id, slot), 'slot': slot,
                   'type': value_type(ctx.values[identity])}

def result_legs(ctx, operation):
    """Original kind/ordinal, independently of optional metadata row count."""
    term = operation.terminator
    if term is not None and term.kind is TerminatorKind.INVOKE:
        for number, edge in enumerate(term.successors):
            signature = next(row for row in operation.completions if row.kind is edge.kind)
            payloads = tuple(InvokeLiteralResult(ControlEdgeReference(operation.id, number),
                CompletionResult(slot)) for slot, value_type in enumerate(signature.types)
                if value_type.kind is not ValueKind.STATE)
            yield {'edge': ControlEdgeReference(operation.id, number), 'kind': edge.kind,
                   'own_result': payloads[0] if len(payloads) == 1 else None,
                   'payloads': payloads, 'signature': signature}
    elif term is None:
        payloads = tuple(OperationResult(operation.id, slot)
                         for slot, value in enumerate(operation.results)
                         if not isinstance(ctx.values[value], StateVersionValue))
        yield {'edge': None, 'kind': ExitKind.NORMAL,
               'own_result': payloads[0] if len(payloads) == 1 else None,
               'payloads': payloads, 'signature': None}


