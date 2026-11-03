"""Original source-definition references independent of CALL publications.

The shared session owns all I/O, receipts, graphs and bounded caches.  These
helpers only locate an existing definition inside its original source unit.
They neither discover call targets nor write a source basis or another graph.
"""
from __future__ import annotations

import ast
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from scar.ir.program.dependencies import GraphNamespace
from scar.ir.program.inventory import SourceContextDigest
from scar.ir.program.providers import ProviderFactReference
from scar.ir.program.source_call_bindings import SourceBodyNamespace
from scar.ir.program.source_references import SourceArtifactLocator, SourceDefinitionReference
from scar.ir.record_codec import decode, encode
from scar.ir.semantics_v2 import SourceSemanticsGraph, SourceSnapshot
from scar.ir.control_flow_v2 import SourceControlFlowGraph
from scar.ir.v2.common import SourceVersion
from scar.ir.v2.ids import OperationDefinitionID


_CONTEXT_PARTS = ("source", "lexical", "semantic", "semantics", "control")
_FUNCTION_KINDS = {"FUNCTION": ast.FunctionDef, "ASYNC_FUNCTION": ast.AsyncFunctionDef, "LAMBDA": ast.Lambda}


class SourceDefinitionUnavailable(LookupError):
    """A precise missing/not-applicable input, distinct from corrupt evidence."""
    kind: str
    detail: str
    missing_fields: tuple[str, ...]

    def __init__(self, kind: str, detail: str, missing_fields: tuple[str, ...] = ()):
        if kind not in ("SOURCE_DEFINITION_NOT_APPLICABLE", "SOURCE_DEFINITION_CONTEXT_UNAVAILABLE"):
            raise ValueError("unsupported source-definition unavailability kind")
        if (type(detail) is not str or not detail or type(missing_fields) is not tuple
                or any(type(name) is not str or not name for name in missing_fields)):
            raise TypeError("source-definition unavailability needs precise typed details")
        self.kind, self.detail, self.missing_fields = kind, detail, missing_fields
        super().__init__(kind + ": " + detail)


@dataclass(frozen=True, slots=True)
class _UnitDefinitionFacts:
    context: SourceContextDigest
    positions: Mapping[OperationDefinitionID, int]


def _span(reference):
    return reference.start_line, reference.end_line, reference.start_column, reference.end_column


def _owned_body(session, namespace):
    if type(namespace) not in (SourceBodyNamespace, GraphNamespace):
        raise TypeError("source definition lookup needs an original source-body/graph namespace")
    session.check()
    body = session.load(namespace)
    if (type(body.namespace) is not SourceBodyNamespace or getattr(body, "interface", None) is None
            or body.row.get("kind") not in _FUNCTION_KINDS or body.namespace.source is None):
        raise SourceDefinitionUnavailable("SOURCE_DEFINITION_NOT_APPLICABLE",
            "This original entry is not a function/async/lambda source-body definition.")
    missing = tuple(name for name in _CONTEXT_PARTS if name not in body.unit.get("artifacts", {}))
    if missing:
        raise SourceDefinitionUnavailable("SOURCE_DEFINITION_CONTEXT_UNAVAILABLE",
            "The original unit lacks retained source/context fragments.", missing)
    return body


def _root_locator(session, body, authority=None):
    """Retain the supplied body's declaration authority, including plain roots."""
    from scar.analysis.static_calls import input_basis_unit
    declaration = body.namespace.graph.declaration
    if declaration is None:
        raise ValueError("source definition body has no original declaration authority")
    artifact = declaration.artifact if authority is None else authority
    pointer = f"#/units/{body.unit_number}"
    if artifact == session.manifest_artifact:
        locator = SourceArtifactLocator(artifact, artifact.sha256, artifact.size_bytes,
            "canonical-json", pointer)
    elif artifact in session._bases:
        locator = session._locator(artifact.uri, artifact.schema, pointer)
        if locator.artifact != artifact:
            raise ValueError("source definition basis differs from the original body declaration")
    else:
        raise ValueError("source definition authority is outside the owned manifest/registered bases")
    root = session.read_artifact(locator)
    try:
        original = root["units"][body.unit_number]
    except (KeyError, IndexError, TypeError):
        raise ValueError("source definition root points outside its original source unit") from None
    # Compare the actual input projection, never analysis diagnostics or a
    # remembered PASS.  Only this selected unit is inspected, not the scope.
    expected = input_basis_unit(body.unit)
    projected = input_basis_unit(original) if artifact == session.manifest_artifact else original
    if projected != expected:
        raise ValueError("source definition root unit differs from its original input declaration")
    return locator


def _unit_facts(session, body, documents):
    from scar.analysis.source_layers import _digest
    unit = body.unit
    receipts = tuple((name, *(unit["artifacts"][name][field] for field in (
        "path", "bytes", "sha256", "decoded_bytes", "decoded_sha256"))) for name in _CONTEXT_PARTS)
    key = ("source-definition-unit-facts", unit["key"], unit["namespace_root"],
        unit["raw_sha256"], unit["decoded_sha256"], receipts)
    found = session._get(key)
    if found is not None:
        return found
    context = SourceContextDigest(unit["namespace_root"], *(_digest(documents[name])
        for name in ("semantic", "semantics", "control")))
    positions = {}
    rows = documents["semantic"].get("definitions")
    if type(rows) is not list:
        raise ValueError("source definition semantic record array is absent")
    for position, row in enumerate(rows):
        session.check()
        identity = decode(OperationDefinitionID, row["id"])
        if identity in positions:
            raise ValueError("source definition has duplicate original semantic IDs")
        positions[identity] = position
    facts = _UnitDefinitionFacts(context, MappingProxyType(positions))
    return session._put(key, facts, 512 + 128 * len(positions))


def _source_inputs(session, namespace):
    body = _owned_body(session, namespace)
    # Every use rechecks registered file stamps/receipts, including lexical
    # material after refinement; only immutable derived facts may be reused.
    documents = {name: session.read(body.unit["artifacts"][name]) for name in _CONTEXT_PARTS}
    text = session.source_text(body)
    catalog = session._catalog(body.unit_number)
    if catalog != documents["lexical"]:
        raise ValueError("source definition lexical catalog differs from its original retained fragment")
    entries = [entry for entry in catalog["entries"] if entry["entry_key"] == body.row["entry_key"]]
    if len(entries) != 1:
        raise ValueError("source definition lacks its unique original lexical entry")
    entry = entries[0]
    if (entry["kind"] != body.row["kind"] or entry.get("source_ref") != encode(body.namespace.source)
            or encode(body.namespace.definition) not in (entry.get("semantic_definition_ids") or ())):
        raise ValueError("source definition differs from its original lexical source/definition ownership")
    tree, semantic, original_text = session.source_context(body)
    if original_text != text:
        raise ValueError("source definition source context changed its retained text")
    source = body.namespace.source
    atom = semantic.source_atoms.get(source.atom_id)
    definition = semantic.definitions.get(body.namespace.definition)
    if (atom is None or atom.reference != source or atom.kind != _FUNCTION_KINDS[entry["kind"]].__name__
            or definition is None or definition.source_file != body.unit["path"]
            or definition.metadata.get("phase") != "call_time" or definition.code_id != source.atom_id.wire
            or source.atom_id not in definition.source_atoms):
        raise ValueError("source definition is not its original semantic call-time/source-atom record")
    nodes = [node for node in ast.walk(tree) if type(node) is _FUNCTION_KINDS[entry["kind"]]
        and (node.lineno, node.end_lineno, node.col_offset, node.end_col_offset) == _span(source)]
    if len(nodes) != 1:
        raise ValueError("source definition has no unique exact retained AST span/kind")
    snapshot = body.metadata.source
    semantics = documents["semantics"]
    if (semantics.get("schema") != SourceSemanticsGraph.SCHEMA
            or type(semantics.get("schema_version")) is not int
            or semantics["schema_version"] not in (1, SourceSemanticsGraph.SCHEMA_VERSION)
            or type(semantics.get("sources")) is not list):
        raise ValueError("source definition has an unsupported original source-semantics profile")
    if any(type(row) is not dict for row in semantics["sources"]):
        raise ValueError("source definition source-semantics snapshot record is malformed")
    snapshots = [decode(SourceSnapshot, row) for row in semantics["sources"] if row.get("path") == snapshot.path]
    if snapshots != [snapshot]:
        raise ValueError("source definition snapshot differs from its original source-semantics input")
    control = documents["control"]
    if (control.get("schema") != SourceControlFlowGraph.SCHEMA
            or type(control.get("schema_version")) is not int
            or control.get("schema_version") != SourceControlFlowGraph.SCHEMA_VERSION
            or type(control.get("graph")) is not dict or type(control["graph"].get("sources")) is not dict):
        raise ValueError("source definition has an unsupported original control profile")
    version = decode(SourceVersion, control["graph"]["sources"].get(snapshot.path))
    if version != SourceVersion(snapshot.path, snapshot.fingerprint):
        raise ValueError("source definition control source version differs")
    facts = _unit_facts(session, body, documents)
    position = facts.positions.get(body.namespace.definition)
    if position is None:
        raise ValueError("source definition ID is absent from its original semantic record table")
    original = documents["semantic"]["definitions"][position]
    if (original["id"] != encode(body.namespace.definition) or original.get("code_id") != source.atom_id.wire
            or encode(source.atom_id) not in original.get("source_atoms", ())
            or original.get("metadata", {}).get("phase") != "call_time"):
        raise ValueError("source definition semantic JSON pointer changed its original ID/source meaning")
    return body, facts, position


def _locators(session, body, position, authority=None):
    root = _root_locator(session, body, authority)
    def locator(name, schema, pointer):
        return session._locator(str(session.root / body.unit["artifacts"][name]["path"]), schema, pointer,
            ProviderFactReference(root.artifact, f"#/units/{body.unit_number}/artifacts/{name}"))
    providers = tuple(locator(name, "scar.static-source-fragment/1", "#") for name in _CONTEXT_PARTS)
    graph = locator("semantic", "scar.ir.v2.semantic", f"#/definitions/{position}")
    for original in (*providers, graph):
        session.read_artifact(original)
    return root, providers, graph


def source_definition_reference(session, namespace):
    """Locate an original function definition without any saved CALL target.

    A plain-manifest authority pins this reference to that immutable input
    version; durable publication is a separate step and never happens here.
    """
    body, facts, position = _source_inputs(session, namespace)
    root, providers, graph = _locators(session, body, position)
    return SourceDefinitionReference(root, providers, graph, body.metadata.source, facts.context,
        body.namespace.definition, body.namespace.source)


def validate_source_definition_reference(session, reference, namespace):
    """Independently replay original ownership/receipts, not a cached result."""
    if type(reference) is not SourceDefinitionReference:
        raise TypeError("expected an original typed source-definition reference")
    reference.__post_init__()
    body, facts, position = _source_inputs(session, namespace)
    # A source-definition identity does not require its valid authority to be
    # the body namespace's chosen authority.  Validate both independently;
    # only registered roots describing these exact original inputs are legal.
    root, providers, graph = _locators(session, body, position, reference.root.artifact)
    if (reference.root != root or reference.providers != providers or reference.graph != graph
            or reference.snapshot != body.metadata.source or reference.context != facts.context
            or reference.definition != body.namespace.definition or reference.source != body.namespace.source):
        raise ValueError("source-definition reference differs from original authority/source/context/record locators")
    return True


__all__ = ["SourceDefinitionUnavailable", "source_definition_reference", "validate_source_definition_reference"]
