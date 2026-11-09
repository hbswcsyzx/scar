"""Identify protocol address requests on the original sealed F4 step ports.

These are requested attribute/index interfaces, not physical slots or complete
descriptor effects. Parent material certification and runtime selection guards
belong to the enclosing source provider; no fact payload is used as a site.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING

from scar.analysis.source_namespace_interfaces import NamespacePlanView
from scar.analysis.source_reference_slice import source_port
from scar.ir.program import normal_links as F, normal_targets as T
from scar.ir.program import source_address_paths as A, source_content as O
from scar.ir.program import source_productions as P
from scar.ir.program.control import LanguageCompletionKind as C
from scar.ir.program.model import ValueKind, ValueType
from scar.ir.program.structured import PythonProtocolKind as K

if TYPE_CHECKING:
    from scar.analysis.program_view import SourceUnitProvider


@dataclass(frozen=True, slots=True)
class IdentifiedContent:
    kind: str
    receiver: T.GlobalPort
    receiver_argument: int
    selector: O.ContentSelector
    payload: T.GlobalPort | None
    result: T.GlobalPort | None
    attribute_fact: int | None


_ATTRIBUTES = {
    P.LanguageActionKind.ATTRIBUTE_GET: 'GET',
    P.LanguageActionKind.ATTRIBUTE_SET: 'SET',
    P.LanguageActionKind.ATTRIBUTE_DELETE: 'DELETE',
}
_ITEMS = {
    P.LanguageActionKind.ITEM_GET: 'GET',
    P.LanguageActionKind.ITEM_SET: 'SET',
    P.LanguageActionKind.ITEM_DELETE: 'DELETE',
}
_PROTOCOLS = frozenset((K.SOURCE_INDEX, K.STORE_SUBSCRIPT, K.MAP_ADD,
    K.BINARY_SLICE, K.STORE_SLICE, K.STORE_SLICE_SUBSCRIPT))


def _shape(context, step, references, outputs):
    """Check the selected original ABI, including the final normal world."""
    normal = [c for c in step.completions if c.kind is C.FALLTHROUGH]
    if (len(step.arguments) != references + 1 or len(normal) != 1
            or len(normal[0].types) != outputs + 1):
        raise ValueError('content request original operand/completion arity differs')
    inputs = tuple(context.emitter.value(v)[1] for v in step.arguments)
    result_types = normal[0].types
    reference = lambda t: type(t) is ValueType and t.kind is ValueKind.REFERENCE
    state = lambda t: type(t) is ValueType and t.kind is ValueKind.STATE
    if (not all(reference(t) for t in inputs[:-1]) or not state(inputs[-1])
            or not all(reference(t) for t in result_types[:-1])
            or result_types[-1] != inputs[-1]):
        raise ValueError('content request original reference/world types differ')
    return context.worlds(step)


class ContentInterfaceIndex:
    """One unit's original attribute facts indexed by exact before/after worlds."""

    def __init__(self, source: SourceUnitProvider):
        self.source = source
        self.attributes = defaultdict(list)
        for ordinal, fact in enumerate(source.facts.attributes):
            worlds = (source_port(source.facts, fact.world),
                source_port(source.facts, fact.result_world))
            self.attributes[worlds].append((ordinal, fact))

    def identify(self, context: NamespacePlanView, step) -> IdentifiedContent | None:
        ins = step.instruction
        language = type(ins) is P.ApplyLanguageAction
        protocol = type(ins) is P.ApplyPythonProtocol
        if not (language and (ins.action in _ATTRIBUTES or ins.action in _ITEMS)
                or protocol and ins.protocol in _PROTOCOLS):
            return None
        if (context.unit != self.source.unit or context.steps.get(step.id) != step
                or self.source.plans.get(context.key) != context.plan):
            raise ValueError('content request context is outside its original source unit/plan')

        if language:
            attribute = ins.action in _ATTRIBUTES
            kind = (_ATTRIBUTES if attribute else _ITEMS)[ins.action]
            references = (1 if attribute else 2) + int(kind == 'SET')
            worlds = _shape(context, step, references, int(kind == 'GET'))
            receiver = context.value(step.arguments[0])
            payload = context.value(step.arguments[1 if attribute else 2]) if kind == 'SET' else None
            result = context.result(step, 0) if kind == 'GET' else None
            if not attribute:
                return IdentifiedContent(kind, receiver, 0,
                    A.ItemSelector(context.value(step.arguments[1])), payload, result, None)

            if not ins.selectors or type(ins.selectors[0]) is not P.SlotRef:
                raise ValueError('attribute request lacks its original selector reference')
            expected = result if kind == 'GET' else payload
            matches = []
            for ordinal, fact in self.attributes.get(worlds, ()):
                if (fact.action is F.AttributeAction(kind)
                        and source_port(self.source.facts, fact.receiver) == receiver
                        and (None if fact.value is None else source_port(self.source.facts, fact.value)) == expected):
                    matches.append((ordinal, fact))
            if len(matches) != 1:
                raise ValueError('attribute request lacks one exact original world/receiver/action/value fact')
            ordinal, fact = matches[0]
            if type(fact.name) is not str:
                raise ValueError('attribute fact lacks its original projected lookup name')
            return IdentifiedContent(kind, receiver, 0, A.FieldSelector(fact.name),
                payload, result, ordinal)

        kind = 'GET' if ins.protocol in (K.SOURCE_INDEX, K.BINARY_SLICE) else 'SET'
        references = (2 if ins.protocol is K.SOURCE_INDEX else 4
            if ins.protocol is K.STORE_SLICE else 3)
        _shape(context, step, references, int(kind == 'GET'))
        # The consuming slice stores retain the original RHS-first ABI.
        rhs_first = ins.protocol in (K.STORE_SLICE, K.STORE_SLICE_SUBSCRIPT)
        receiver_argument = 1 if rhs_first else 0
        receiver = context.value(step.arguments[receiver_argument])
        if ins.protocol in (K.BINARY_SLICE, K.STORE_SLICE):
            lower = 2 if rhs_first else 1
            selector = O.SliceBoundsSelector(context.value(step.arguments[lower]),
                context.value(step.arguments[lower + 1]))
        else:
            selector = A.ItemSelector(context.value(step.arguments[2 if rhs_first else 1]))
        payload = context.value(step.arguments[0 if rhs_first else 2]) if kind == 'SET' else None
        result = context.result(step, 0) if kind == 'GET' else None
        return IdentifiedContent(kind, receiver, receiver_argument, selector, payload, result, None)
