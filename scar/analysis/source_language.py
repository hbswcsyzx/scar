"""Opt-in inputs and validation for extended source protocols.

CodeType inputs are supplied by an already verified CodeWitnessStore. This
module does not compile, import the target, or open a report-selected archive.
"""
from __future__ import annotations

import ast
import json
from dataclasses import dataclass, field
from types import CodeType

from scar.ir.program.call_edges import CapturedCode, CodeSourceLink, CodeCapture, CallLinkStatus
from scar.ir.program.source_language import SourceLanguageCapability
from scar.ir.record_codec import decode, encode
from scar.trace.code_snapshot import describe_code


@dataclass(frozen=True)
class SourceCodeEvidence:
    store: object
    composition: object
    captured: CapturedCode
    code: CodeType = field(init=False)
    source_link: CodeSourceLink = field(init=False)
    _witness_json: str = field(init=False, repr=False)

    def __post_init__(self):
        from scar.analysis.code_witness import CodeWitnessStore
        from scar.analysis.program_composition import CompositionIndex
        if (type(self.store) is not CodeWitnessStore or self.store.writable or self.store.compile_missing
                or type(self.composition) is not CompositionIndex or type(self.captured) is not CapturedCode):
            raise ValueError("source language requires explicit original composition and read-only CodeWitnessStore")
        source = self.composition.inventory_component("call_sources")["model"]
        captures = [(i, decode(CodeCapture, row)) for i, row in enumerate(source["codes"])
                    if row["code"]["key"] == self.captured.key]
        links = [(i, decode(CodeSourceLink, row)) for i, row in enumerate(source["code_links"])
                 if row["code"] == self.captured.key]
        if (not captures or any(row.code != self.captured for _, row in captures) or len(links) != 1
                or links[0][1].status is not CallLinkStatus.VERIFIED):
            raise ValueError("original composition has no complete matching captured-code/source witness")
        link_index, link = links[0]
        code, reference = self.store.resolve(self.captured, link.snapshot, link.optimize_levels, allow_compile=False)
        if type(code) is not CodeType or describe_code(code) != encode(self.captured):
            raise ValueError("owned CodeWitness archive did not reproduce the complete code descriptor")
        witness = {**reference, "store": self.store.receipt(),
            "source_link_locator": self.composition.inventory_component_locator("call_sources", f"/model/code_links/{link_index}"),
            "captured_code_locator": self.composition.inventory_component_locator("call_sources", f"/model/codes/{captures[0][0]}/code"),
            "inventory": self.composition.document["inventory"]}
        object.__setattr__(self, "code", code)
        object.__setattr__(self, "source_link", link)
        object.__setattr__(self, "_witness_json", json.dumps(witness, sort_keys=True, separators=(",", ":"), allow_nan=False))

    @property
    def witness(self):
        # A caller may annotate its copy of a receipt, never the independently
        # verified evidence retained by this input object.
        return json.loads(self._witness_json)

    def require_definition(self, snapshot, definition, source):
        link = self.source_link
        if (link.snapshot != snapshot or link.definition != definition or link.source != source
                or self.captured.filename != snapshot.path):
            raise ValueError("CodeWitness does not identify this exact source definition")

    def to_dict(self):
        return {"captured": encode(self.captured), "source_link": encode(self.source_link),
                "witness": self.witness, "runtime_code_instance_established": False}


@dataclass(frozen=True)
class SourceLanguageOptions:
    capabilities: tuple[SourceLanguageCapability, ...] = tuple(SourceLanguageCapability)
    code_evidence: SourceCodeEvidence | None = None

    def __post_init__(self):
        if (type(self.capabilities) is not tuple or not self.capabilities
                or any(type(row) is not SourceLanguageCapability for row in self.capabilities)
                or len(set(self.capabilities)) != len(self.capabilities)
                or self.code_evidence is not None and type(self.code_evidence) is not SourceCodeEvidence):
            raise ValueError("invalid explicit source-language inputs")


def require_source_tree(tree, snapshot, source_reference):
    """Resolve a source node by complete span and kind, under its fixed snapshot."""
    if source_reference.path != snapshot.path or source_reference.fingerprint != snapshot.fingerprint:
        raise ValueError("language source reference differs from its fixed snapshot")
    return [node for node in ast.walk(tree) if hasattr(node, "end_lineno")
            and (node.lineno, node.end_lineno, node.col_offset, node.end_col_offset)
            == (source_reference.start_line, source_reference.end_line,
                source_reference.start_column, source_reference.end_column)]


__all__ = ["SourceCodeEvidence", "SourceLanguageOptions", "require_source_tree"]
