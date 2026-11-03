"""Source attribute-lookup requests over existing canonical INVOKE ports.

A selector configures a language lookup request. It does not identify an
instance dictionary, descriptor, resolved callable or physical state address.
Completions retain their original values, including method-lookup carriers.
These records add no nodes and grant no alias, purity or effect-completeness
claim. Source/compiler replay belongs to the enclosing source reader.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from scar.ir.program.ids import OperationID, UseID, ValueID
from scar.ir.program.structured import ControlEdgeReference
from scar.ir.v2.common import SourceReference


def _exact(value, expected, name):
    if type(value) is not expected:
        raise TypeError(name + " must be exact " + expected.__name__)
    post = getattr(value, "__post_init__", None)
    if post is not None:
        post()


def _text(value, name):
    if type(value) is not str or not value or "\0" in value:
        raise ValueError(name + " must be nonempty text without NUL")


class SelectorResolution(str, Enum):
    AS_WRITTEN = "AS_WRITTEN"
    LEXICAL_MANGLED = "LEXICAL_MANGLED"
    UNRESOLVED = "UNRESOLVED"


@dataclass(frozen=True, slots=True)
class StaticAttributeSelector:
    """Source spelling and actual lookup name are different static fields.

    ``key_use`` references an already existing key operand when the producer
    has one. A string configuration never manufactures a Python Value/Use.
    ``UNRESOLVED`` applies to the lookup-name field, not the whole operation.
    """
    source_spelling: str
    lookup_name: str | None
    resolution: SelectorResolution
    lexical_class_source: SourceReference | None = None
    key_use: UseID | None = None
    unresolved_reason: str | None = None

    def __post_init__(self):
        _text(self.source_spelling, "attribute source spelling")
        _exact(self.resolution, SelectorResolution, "selector resolution")
        if self.lookup_name is not None:
            _text(self.lookup_name, "attribute lookup name")
        if self.lexical_class_source is not None:
            _exact(self.lexical_class_source, SourceReference, "lexical class source")
        if self.key_use is not None:
            _exact(self.key_use, UseID, "attribute key Use")
        if self.resolution is SelectorResolution.UNRESOLVED:
            if self.lookup_name is not None or self.unresolved_reason is None:
                raise ValueError("an unresolved lookup-name field needs a concrete reason and no claimed name")
            _text(self.unresolved_reason, "unresolved lookup-name reason")
        elif self.resolution is SelectorResolution.AS_WRITTEN:
            if self.lookup_name != self.source_spelling or self.unresolved_reason is not None:
                raise ValueError("AS_WRITTEN must retain the exact source spelling")
        elif (self.lookup_name is None or self.lookup_name == self.source_spelling
                or self.lexical_class_source is None or self.unresolved_reason is not None):
            raise ValueError("LEXICAL_MANGLED needs a distinct name and original lexical class source")


class AttributeLookupForm(str, Enum):
    SOURCE_GETATTR = "SOURCE_GETATTR"
    CPYTHON_LOAD_ATTR = "CPYTHON_LOAD_ATTR"
    CPYTHON_LOAD_METHOD = "CPYTHON_LOAD_METHOD"


@dataclass(frozen=True, slots=True)
class AttributeLookupCompletion:
    """Original non-world payloads in signature order and its exact world slot.

    Payload arity is taken from the real signature. RAISE may carry one or
    several reference/protocol slots; no exception packet is synthesized.
    """
    edge: ControlEdgeReference
    payloads: tuple[ValueID, ...]
    world: ValueID

    def __post_init__(self):
        _exact(self.edge, ControlEdgeReference, "lookup completion edge")
        if type(self.payloads) is not tuple:
            raise TypeError("lookup completion payloads must be an ordered tuple")
        for value in self.payloads:
            _exact(value, ValueID, "lookup completion payload")
        _exact(self.world, ValueID, "lookup completion world")
        if len(set((*self.payloads, self.world))) != len(self.payloads) + 1:
            raise ValueError("lookup completion must retain distinct original formal slots")


@dataclass(frozen=True, slots=True)
class AttributeLookupInterface:
    """A lookup attempt, retaining opaque world and both real outcomes."""
    operation: OperationID
    source: SourceReference
    receiver: UseID
    selector: StaticAttributeSelector
    world: UseID
    form: AttributeLookupForm
    normal: AttributeLookupCompletion
    raised: AttributeLookupCompletion

    def __post_init__(self):
        for value, expected, name in (
                (self.operation, OperationID, "lookup operation"),
                (self.source, SourceReference, "lookup source"),
                (self.receiver, UseID, "lookup receiver"),
                (self.selector, StaticAttributeSelector, "lookup selector"),
                (self.world, UseID, "lookup world"),
                (self.form, AttributeLookupForm, "lookup form"),
                (self.normal, AttributeLookupCompletion, "lookup normal completion"),
                (self.raised, AttributeLookupCompletion, "lookup raised completion")):
            _exact(value, expected, name)
        uses = (self.receiver, self.world, *((self.selector.key_use,)
            if self.selector.key_use is not None else ()))
        if len(set(uses)) != len(uses):
            raise ValueError("lookup receiver/key/world must name distinct original Uses")
        if (self.normal.edge.operation != self.operation or self.raised.edge.operation != self.operation
                or self.normal.edge == self.raised.edge):
            raise ValueError("lookup outcomes must be distinct edges of this original operation")
        lexical = self.selector.lexical_class_source
        if lexical is not None and (lexical.path != self.source.path
                or lexical.fingerprint != self.source.fingerprint):
            raise ValueError("lookup selector and lexical class must retain the same source version")


__all__ = ["SelectorResolution", "StaticAttributeSelector", "AttributeLookupForm",
    "AttributeLookupCompletion", "AttributeLookupInterface"]
