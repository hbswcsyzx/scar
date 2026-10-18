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


def external_artifact(graph, uri='memory:external-graph'):
    from scar.ir.v2.evidence import EvidenceGraph
    from scar.ir.v2.values import ValueGraph
    if type(graph) not in (ValueGraph, EvidenceGraph):
        raise TypeError('external artifact requires exact ValueGraph or EvidenceGraph')
    try:
        report = graph.validate()
        if not report['valid']:
            raise ValueError('invalid external graph: ' + '; '.join(report['errors']))
        wire = external_bytes(graph)
    except (AttributeError, TypeError, KeyError) as error:
        raise ValueError('invalid external graph shape or encoding: ' + str(error)) from error
    return ProviderArtifact(uri, hashlib.sha256(wire).hexdigest(), len(wire), graph.SCHEMA)


__all__ = ['snapshot_for', 'external_artifact']
