"""Read bounded scalar fields without expanding content-factor products."""
import gzip
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path

from scar.analysis import source_scalar_graph, source_scalar_values, source_builtin_values, constants_v2
from scar.analysis.normal_query import NormalCallGraph
from scar.ir.program import scalar_values as V, normal_targets as T, source_productions as P
from scar.ir.record_codec import _decode, _record_tags


class ScalarGraphFields:
    """Receipt-bound fields over the original graph, never a rewrite proof."""

    _types = dict(operations=T.LanguageOperationSite, sources=V.ScalarLiteralSource,
        fields=V.ScalarSnapshot, groups=V.ScalarTransferGroup,
        derivations=V.ScalarDerivation, obligations=V.ScalarObligation)

    def __init__(self, path):
        self.path = Path(path).absolute()
        self.report = json.loads((self.path/'result.json').read_bytes())
        r = self.report
        if (r['schema'], r['schema_version']) != ('scar.source-scalar-graph', 1):
            raise ValueError('expected scalar field graph')
        root = Path(source_scalar_graph.__file__).parents[2]
        pins = {str(Path(m.__file__).relative_to(root)):sha256(Path(m.__file__).read_bytes()).hexdigest()
            for m in (source_scalar_values, source_builtin_values, constants_v2, V)}
        if (r['implementation_sha256'] != pins
                or r['bridge_sha256'] != sha256(Path(source_scalar_graph.__file__).read_bytes()).hexdigest()):
            raise ValueError('scalar field producer differs')
        self.source = NormalCallGraph(r['source_targets'])
        if (r['source_targets_sha256'] != sha256((self.source.path/'result.json').read_bytes()).hexdigest()
                or r['source_facts_sha256'] != self.source.report['source_facts_sha256']):
            raise ValueError('scalar source parent differs')
        if not set(r['selected_units']) <= set(self.source.units):
            raise ValueError('scalar source slice is outside its parent')
        if r['must_value_proven'] or r['transformation_authorized'] or r['first_stage_complete']:
            raise ValueError('scalar may fields do not confer proof authority')

    def rows(self, table):
        expected = self._types[table]
        receipt = self.report['tables'][table]
        payload = (self.path/receipt['path']).read_bytes()
        if len(payload) != receipt['bytes'] or sha256(payload).hexdigest() != receipt['sha256']:
            raise ValueError('scalar compressed table differs')
        # Validate in bounded memory before returning any decoded record.
        # Two gzip passes avoid retaining the complete decoded table in RAM.
        digest = sha256(); size = count = 0
        with gzip.GzipFile(fileobj=BytesIO(payload)) as stream:
            for line in stream:
                digest.update(line); size += len(line); count += 1
                if not line.endswith(b'\n'):
                    raise ValueError('scalar table has an incomplete row')
        if (size != receipt['decoded_bytes'] or count != receipt['records']
                or digest.hexdigest() != receipt['decoded_sha256']):
            raise ValueError('scalar decoded table differs')
        tags = _record_tags(P.PRODUCTION_RECORD_TAGS)
        with gzip.GzipFile(fileobj=BytesIO(payload)) as stream:
            for line in stream:
                row = _decode(expected, json.loads(line), tags)
                if table == 'groups':
                    if (not row.sources or not row.targets
                            or any(p.unit not in self.source.units for p in (*row.sources, *row.targets))
                            or any(p.unit not in self.report['selected_units'] for p in row.targets)):
                        raise ValueError('scalar group has empty or foreign endpoints')
                    if row.source_table != 'unit.names':
                        parent = self.source.report[row.source_table]
                        if not 0 <= row.source_ordinal < parent['records']:
                            raise ValueError('scalar group has no original table row')
                if table == 'fields' and row.complete:
                    raise ValueError('a scalar may field is not a must value')
                yield row
