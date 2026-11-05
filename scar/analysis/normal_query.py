"""Read conditional source-call edges and expand their original shared bodies.

No new program nodes are constructed. A fixed point is not complete dispatch
coverage, and source candidates never grant transformation authority.
"""
import argparse
from collections import Counter
import gzip
from hashlib import sha256
import json
from pathlib import Path

from scar.analysis.normal_links import _pins
from scar.analysis import normal_targets
from scar.analysis.source_template_links import read_template_body
from scar.ir.program import normal_targets as T
from scar.ir.program import source_productions as P
from scar.ir.record_codec import decode


class NormalCallGraph:
    """Small report index; bodies and value tables remain in their unit stores."""

    def __init__(self, targets):
        self.path = Path(targets).absolute()
        self.report = json.loads((self.path / 'result.json').read_bytes())
        if self.report['schema'] != 'scar.normal-source-targets' or self.report['schema_version'] != 2:
            raise ValueError('expected current source target graph')
        if self.report['types_sha256'] != sha256(Path(T.__file__).read_bytes()).hexdigest():
            raise ValueError('call edge declarations differ')
        if self.report['implementation_sha256'] != sha256(Path(normal_targets.__file__).read_bytes()).hexdigest():
            raise ValueError('call target producer differs')
        self.facts = Path(self.report['source_facts'])
        raw = (self.facts / 'result.json').read_bytes()
        if sha256(raw).hexdigest() != self.report['source_facts_sha256']:
            raise ValueError('source fact result differs')
        self.inputs = json.loads(raw)
        if self.inputs['implementation_sha256'] != _pins():
            raise ValueError('source fact implementation differs')
        self.units = {row['unit']: row for row in self.inputs['units']}
        self.sources = {row['path']: row['unit'] for row in self.inputs['units']}
        self.templates = Path(self.inputs['templates'])
        if sha256((self.templates / 'result.json').read_bytes()).hexdigest() != self.inputs['source_result_sha256']:
            raise ValueError('source template version differs')

    def calls(self, source=None, *, occurrence=None):
        """Validate the whole fragment receipt; decode selected unit edges only."""
        unit = None if source is None else self.sources[str(Path(source).absolute())]
        receipt = self.report['calls']
        payload = (self.path / receipt['path']).read_bytes()
        if len(payload) != receipt['bytes'] or sha256(payload).hexdigest() != receipt['sha256']:
            raise ValueError('call fragment differs')
        raw = gzip.decompress(payload)
        if len(raw) != receipt['decoded_bytes'] or sha256(raw).hexdigest() != receipt['decoded_sha256']:
            raise ValueError('decoded call fragment differs')
        if raw.count(b'\n') != receipt['records']:
            raise ValueError('call record count differs')
        for line in raw.splitlines():
            document = json.loads(line)
            if unit is not None and document['result']['unit'] != unit:
                continue
            if occurrence is not None and document['result']['port']['template']['occurrence'] != occurrence:
                continue
            link = decode(T.CallLink, document, record_tags=P.PRODUCTION_RECORD_TAGS)
            if link.result.unit not in self.units or link.callee.unit != link.result.unit:
                raise ValueError('call source is not in its input domain')
            if link.body is not None:
                if link.source_callable is None or link.body.unit != link.source_callable.unit or link.body.unit not in self.units:
                    raise ValueError('call body has no qualified source')
                if any(route.formal.unit != link.body.unit for route in link.parameters):
                    raise ValueError('formal parameters belong to another body source')
            yield link

    def expand(self, link):
        """Return the sealed original plan containing this candidate body.

        The caller selects link.body.region within that plan. Deferred bodies
        are definitions; expansion does not mean they execute at creation.
        """
        if link.body is None:
            raise ValueError('this edge has no source body')
        plan = read_template_body(self.templates, link.body.unit, link.body.template)
        if link.body.region not in {region.id for region in plan.regions}:
            raise ValueError('candidate region absent from original plan')
        return plan


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--targets', required=True)
    parser.add_argument('--source', required=True)
    parser.add_argument('--occurrence', type=int)
    args = parser.parse_args()
    view = NormalCallGraph(args.targets)
    links = tuple(view.calls(args.source, occurrence=args.occurrence))
    print(json.dumps(dict(source=str(Path(args.source).absolute()), candidate_links=len(links),
        modes=dict(Counter(link.mode for link in links)),
        source_targets=sorted({view.units[link.body.unit]['path'] for link in links if link.body is not None}),
        packed_links=sum(link.argument_packs is not None for link in links),
        runtime_dispatch_verified=False, first_stage_complete=False), indent=2))


if __name__ == '__main__':
    main()
