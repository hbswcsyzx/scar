"""Receipt-checked raw routing, without claiming typed relation validation.

Every serialized source-body namespace contributes its original shard to an
upper bound.  This includes foreign producers, creators and context witnesses,
not just caller/callee headers.  Only a selected shard is subsequently decoded
and replayed by the session's normal fresh verifier.  A complete routing index
therefore closes the *serialized lookup*, not target sets or program effects.
"""
from __future__ import annotations

from dataclasses import dataclass

from scar.ir.program.dependencies import GraphNamespace
from scar.ir.program.source_call_bindings import SourceBodyNamespace
from scar.ir.record_codec import decode


_BODY_FIELDS = frozenset(("graph", "graph_representation", "definition", "source", "entry", "region"))
_RELATION_FIELDS = frozenset(("source_model", "caller", "calls", "import_routes",
    "module_attribute_flows", "module_frontiers", "module_globals_flows"))


@dataclass(frozen=True, slots=True)
class RelationRoutingResult:
    uris: tuple[str, ...]
    complete: bool
    issue: str | None = None


def _namespace_identities(document, check):
    """Visit all wire fields, retaining no document or second program graph."""
    pending = [document]
    found = set()
    visits = 0
    while pending:
        value = pending.pop()
        visits += 1
        if visits % 256 == 0:
            check()
        if type(value) is dict:
            if "graph_representation" in value:
                if set(value) != _BODY_FIELDS:
                    raise ValueError("raw relationship routing found a malformed source-body namespace")
                # Decode the small namespace record, never its referenced graph.
                # This also checks the typed region/wire, locator and declaration.
                namespace = GraphNamespace.from_source(decode(SourceBodyNamespace, value))
                found.add(namespace.identity)
                continue
            pending.extend(value.values())
        elif type(value) is list:
            pending.extend(value)
    return found


class RawCallRelationRouting:
    """One immutable-session, bounded namespace -> original-shard upper bound."""
    def __init__(self, *, items, source_model, version, read, check,
                 max_shards, max_references):
        self.items = items
        self.source_model, self.version = source_model, version
        self.read, self.check = read, check
        self.max_shards, self.max_references = max_shards, max_references
        self.routes = {}
        self.shards = self.references = 0
        self.complete = False
        self.issue = None
        self._remaining = iter(items)
        self._pending = None

    def ensure(self):
        if self.complete:
            return
        if self.version not in (8, 9):
            self.issue = "Raw routing does not assert completeness for historical call wire profiles."
            return
        try:
            while True:
                self.check()
                if self._pending is None:
                    self._pending = next(self._remaining, None)
                if self._pending is None:
                    self.complete, self.issue = True, None
                    return
                if self.shards >= self.max_shards:
                    raise OverflowError("dependency raw routing shard budget exhausted")
                uri = self._pending
                document = self.read(uri)
                if (type(document) is not dict or set(document) != {"schema", "schema_version", "relations"}
                        or document["schema"] != "scar.static-calls"
                        or type(document["schema_version"]) is not int or document["schema_version"] != self.version):
                    raise ValueError("raw routing shard differs from its exact published call wire profile")
                relations = document["relations"]
                if (type(relations) is not dict or set(relations) != _RELATION_FIELDS
                        or relations["source_model"] != self.source_model
                        or relations["caller"] != self.items[uri]["caller"]
                        or any(type(relations[name]) is not list for name in _RELATION_FIELDS - {"source_model", "caller"})):
                    raise ValueError("raw routing shard differs from its original source basis or owner")
                identities = _namespace_identities(relations, self.check)
                if self.references + len(identities) > self.max_references:
                    raise OverflowError("dependency raw routing reference budget exhausted")
                # Commit a whole receipt-checked shard atomically.  A partial
                # prefix is still only an upper bound for that known prefix.
                for identity in identities:
                    self.routes.setdefault(identity, []).append(uri)
                self.references += len(identities)
                self.shards += 1
                self._pending = None
        except (OverflowError, TimeoutError) as error:
            self.issue = type(error).__name__ + ": " + str(error)

    def lookup(self, namespace):
        if type(namespace) is not GraphNamespace:
            raise TypeError("raw call routing needs an original graph namespace")
        self.ensure()
        return RelationRoutingResult(tuple(self.routes.get(namespace.identity, ())), self.complete, self.issue)


__all__ = ["RawCallRelationRouting", "RelationRoutingResult"]
