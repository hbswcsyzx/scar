"""Read conditional input requests against their immutable call/entry parents."""
from hashlib import sha256
import json
from pathlib import Path

from scar.analysis import source_configuration_requests as producer
from scar.analysis.source_symbol_variants import _table
from scar.ir.program import configuration_requests as R
from scar.ir.record_codec import decode


def read_configuration_requests(path):
    path=Path(path).absolute();raw=(path/'result.json').read_bytes();report=json.loads(raw)
    if ((report['schema'],report['schema_version'],report['status'])!=
            ('scar.configuration-requests',1,'CONDITIONAL_LIBRARY_REQUESTS_EXTRACTED')
            or report['implementation_sha256']!=sha256(Path(producer.__file__).read_bytes()).hexdigest()
            or report['types_sha256']!=sha256(Path(R.__file__).read_bytes()).hexdigest()):
        raise ValueError('configuration request producer or types differ')
    target=Path(report['targets']);target_raw=(target/'result.json').read_bytes()
    if sha256(target_raw).hexdigest()!=report['targets_sha256']:
        raise ValueError('configuration call graph parent differs')
    graph=json.loads(target_raw);catalog=graph['context_facts']
    facts_raw=(target/catalog['path']).read_bytes()
    if (len(facts_raw)!=catalog['bytes'] or sha256(facts_raw).hexdigest()!=catalog['sha256']
            or sha256(facts_raw).hexdigest()!=report['source_catalog_sha256']):
        raise ValueError('configuration source catalog differs')
    entry=Path(report['script_entry']['path'])
    if (sha256((entry/'result.json').read_bytes()).hexdigest()!=report['script_entry']['sha256']
            or sha256((entry/'entry.json').read_bytes()).hexdigest()!=report['entry_sha256']):
        raise ValueError('configuration entry input snapshot differs')
    units={row['unit'] for row in json.loads(facts_raw)['units']}
    requests=tuple(decode(R.ConfigurationRequest,wire) for wire in _table(path,report['requests']))
    if (len(requests)!=report['request_count'] or len({r.id for r in requests})!=len(requests)
            or sum(len(r.sources) for r in requests)!=report['source_candidates']):
        raise ValueError('configuration request denominators differ')
    calls=graph['calls']
    for request in requests:
        ref=request.call_reference
        if (request.api.unit not in units or request.factory_result.unit not in units
                or ref.artifact.uri!=str(target/calls['path'])
                or (ref.artifact.sha256,ref.artifact.size_bytes)!=(calls['sha256'],calls['bytes'])
                or not ref.locator.startswith('#/records/')
                or not 0<=int(ref.locator.removeprefix('#/records/'))<calls['records']):
            raise ValueError('configuration request lost its original source call reference')
        if (not request.conditions or any(not source.conditions for source in request.sources)
                or request.semantics!='CONDITIONAL_REQUEST_CANDIDATES_NOT_CURRENT_ARGV_OR_COMPOSED_CFG'):
            raise ValueError('configuration source selection has no conditional provenance')
    if (report['target_executed'] or report['configuration_composed'] or report['current_argv_proven']
            or report['first_stage_complete'] or (path/'result.json').read_bytes()!=raw):
        raise ValueError('configuration requests have no execution or composition authority')
    return report,requests
