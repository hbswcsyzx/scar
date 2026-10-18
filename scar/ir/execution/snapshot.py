"""Canonical artifact identities; no URI is opened or provider executed."""
import hashlib
import json

from scar.ir.program.codec import dumps as program_dumps
from scar.ir.program.providers import ProviderArtifact
from .coordinates import ProgramSnapshot


def snapshot_for(program, uri='memory:canonical-program'):
    wire = program_dumps(program).encode('utf-8')
    version = json.loads(wire)['schema_version']
    return ProgramSnapshot(ProviderArtifact(uri, hashlib.sha256(wire).hexdigest(), len(wire),
                                             'scar.program-graph'), version)


def external_bytes(graph):
    return json.dumps(graph.to_dict(), ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False).encode('utf-8')


def _families():
    """A closed decoder table; schema strings never select imports or code."""
    from scar.ir.v2.codec import evidence_from_dict, semantic_from_dict, values_from_dict
    from scar.ir.v2.evidence import EvidenceGraph
    from scar.ir.v2.semantic import SemanticGraph
    from scar.ir.v2.values import ValueGraph
    return {ValueGraph: values_from_dict, EvidenceGraph: evidence_from_dict,
            SemanticGraph: semantic_from_dict}


class SnapshotError(ValueError):
    """A supplied external snapshot violates its explicit catalog contract."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def _validated_bytes(graph):
    try:
        report = graph.validate()
        if not report['valid']:
            raise ValueError('; '.join(report['errors']))
        return external_bytes(graph)
    except (AttributeError, TypeError, KeyError, ValueError, OverflowError, RecursionError) as error:
        raise SnapshotError('external_graph_invalid',
                            'invalid external graph shape or encoding: ' + str(error)) from error


class ExternalSnapshots:
    """Exact detached external graphs, cached only within one query/resolver.

    A fresh resolver rechecks mutable caller catalogs on first access. Cached
    graphs are detached from callers and correspond to the bytes checked on
    that access. This verifies declarations, never runtime/provider facts.
    Snapshot serialization/validation cost is separate from geometry budgets.
    No artifact URI is opened and no caller-specified decoder is executed.
    """

    def __init__(self, value_graphs=None, evidence_graphs=None, semantic_graphs=None):
        families = _families()
        self._catalogs = {}
        for kind, catalog in zip(families, (value_graphs, evidence_graphs, semantic_graphs), strict=True):
            if catalog is None:
                catalog = {}
            if type(catalog) is not dict or any(type(key) is not str for key in catalog):
                raise SnapshotError('catalog_type', 'external graph catalogs require exact dicts with exact string keys')
            self._catalogs[kind] = catalog
        self._verified = {}

    def graph(self, artifact, kind):
        families = _families()
        if type(kind) is not type or kind not in families:
            raise SnapshotError('external_graph_type', 'external graph kind must be an exact whitelisted graph class')
        try:
            if type(artifact) is not ProviderArtifact:
                raise TypeError('external artifact must be an exact ProviderArtifact')
            artifact.__post_init__()
        except (TypeError, ValueError) as error:
            raise SnapshotError('external_snapshot', str(error)) from error
        key = kind, artifact.sha256, artifact.schema, artifact.size_bytes
        if key in self._verified:
            return self._verified[key]
        catalog = self._catalogs[kind]
        if artifact.sha256 not in catalog:
            self._verified[key] = None
            return None
        graph = catalog[artifact.sha256]
        if type(graph) is not kind:
            raise SnapshotError('external_graph_type', 'supplied external graph has the wrong exact graph family')
        wire = _validated_bytes(graph)
        if (artifact.schema != graph.SCHEMA or artifact.size_bytes != len(wire)
                or artifact.sha256 != hashlib.sha256(wire).hexdigest()):
            raise SnapshotError('external_snapshot', 'external graph bytes/schema/hash do not match artifact')
        try:
            snapshot = families[kind](json.loads(wire))
        except (AttributeError, TypeError, KeyError, ValueError, OverflowError, RecursionError) as error:
            raise SnapshotError('external_graph_invalid',
                                'invalid external graph canonical snapshot: ' + str(error)) from error
        self._verified[key] = snapshot
        return snapshot


def external_artifact(graph, uri='memory:external-graph'):
    if type(graph) not in _families():
        raise TypeError('external artifact requires exact ValueGraph, EvidenceGraph or SemanticGraph')
    wire = _validated_bytes(graph)
    return ProviderArtifact(uri, hashlib.sha256(wire).hexdigest(), len(wire), graph.SCHEMA)


__all__ = ['snapshot_for', 'external_artifact', 'ExternalSnapshots', 'SnapshotError']
