"""Join actual resumable segments to existing shared source-body ports.

Interpreter events select activation/segment identity. Sealed source bodies
provide entry, suspension, completion and fresh-world ingress ports. Delegated
resumption remains a driver entry, never an assumed normalized delivery.
"""
import argparse
from collections import Counter, defaultdict
from hashlib import sha256
import json
from pathlib import Path
import time

from scar.analysis.source_body_interfaces import BodyInterfaceResolver
from scar.analysis.source_body_activations import _links
from scar.analysis.source_observed_calls import _span
from scar.analysis.source_observed_interfaces import ObservedFunctionInterfaceStore
from scar.analysis.source_declared_catalog import _receipt, _check
from scar.analysis.source_stage import _durable_bytes, _durable_mkdir
from scar.analysis.source_template_links import _json
from scar.analysis.normal_output import write_table
from scar.ir.program import control as C, source_productions as P
from scar.ir.record_codec import encode
from scar.trace.code_snapshot import site as code_site
from scar.trace.resumptions import read_resumptions, ENTRIES, FLAGS

SCHEMA = 'scar.source-observed-resumptions'


def _pins():
    from scar.analysis import source_body_interfaces
    from scar.trace import resumptions
    return {name: sha256(Path(module.__file__).read_bytes()).hexdigest() for name, module in (
        ('producer', __import__(__name__, fromlist=['__file__'])),
        ('bodies', source_body_interfaces), ('boundaries', resumptions))}


def _contains(outer, inner):
    return (outer[0], outer[2]) <= (inner[0], inner[2]) and (inner[1], inner[3]) <= (outer[1], outer[3])


def derive(index, metadata):
    index.check(); capture, events = read_resumptions(metadata)
    if Path(index.codes.trace.directory).resolve() != Path(metadata).absolute().parent:
        raise ValueError('resumption join requires the same original frame trace')
    by_code = defaultdict(list)
    for link in _links(index.codes):
        for captured in link.captures:
            if captured.code.flags & FLAGS:
                by_code[captured.process_id, captured.code.key].append(link)
    resolver = BodyInterfaceResolver(index.view)
    interfaces = {}; bindings = []; frontiers = []; yielded = {}; covered = set()
    entries = {entry.invocation: entry for entry in index.codes.trace.entries}
    exits = {exit_.invocation: exit_ for exit_ in index.codes.trace.exits}
    counts = Counter()
    for event in events:
        original = (entries if event.kind in ENTRIES else exits).get(event.invocation)
        if original is None or original.code != event.position.code:
            raise ValueError('resumption segment is absent from its admitted trace index')
        callers = index._callers.get((event.invocation.process_id, event.position.code), ())
        if any(code_site(c.code, event.position.offset) != encode(event.position) for c in callers):
            raise ValueError('resumption position differs from the admitted full compiler code')
        candidates = tuple({link.id: link for link in by_code[event.invocation.process_id, event.position.code]}.values())
        if candidates and not callers:
            frontiers.append(dict(sequence=event.sequence, reason='FULL_SOURCE_CODE_POSITION_NOT_ADMITTED'))
            continue
        if not candidates:
            frontiers.append(dict(sequence=event.sequence, reason='RESUMABLE_CODE_HAS_NO_SOURCE_BODY_CORRESPONDENCE'))
        for link in candidates:
            body = resolver.resolve(link.body); interfaces[body.id] = body
            if body.scope != link.scope: raise ValueError('resumption code/body scopes differ')
            selected = (); selection = 'ORIGINAL_SOURCE_PORT'
            key = event.activation, link.id
            if event.kind == 'PY_START':
                selected = tuple(p for p in body.ingresses if p.suspension is None)
            elif event.kind == 'PY_YIELD':
                syntax = index._source_syntax(body.body.unit); located = []
                for suspension in body.suspensions:
                    span = _span(syntax, suspension.step.port.template.occurrence)
                    position = event.position.position
                    if position is not None and all(type(n) is int for n in span) and _contains(span, position):
                        located.append((span, suspension))
                selected = tuple(s for span, s in located if not any(
                    other != span and _contains(span, other) for other, _ in located))
                yielded[key] = event.sequence, selected
                if len(selected) != 1:
                    selection = 'SOURCE_SUSPENSION_ALTERNATIVES'
            elif event.kind in ('PY_RESUME', 'PY_THROW'):
                prior = yielded.get(key)
                suspensions = prior[1] if prior is not None and prior[0] == event.previous else ()
                delegated = any(s.kind in (P.SuspensionKind.YIELD_FROM, P.SuspensionKind.AWAIT) for s in suspensions)
                kind = C.LanguageCompletionKind.FALLTHROUGH if event.kind == 'PY_RESUME' else C.LanguageCompletionKind.RAISE
                selected = tuple(p for p in body.ingresses if p.suspension in {s.step for s in suspensions}
                    and (delegated or p.delivery is kind))
                if delegated:
                    selection = 'DELEGATED_DRIVER_ENTRY_NORMALIZED_DELIVERY_NOT_PROVEN'
            else:
                kind = C.LanguageCompletionKind.RETURN if event.kind == 'PY_RETURN' else C.LanguageCompletionKind.RAISE
                selected = tuple(p for p in body.completions if p.kind is kind)
            if selected: covered.add(event.sequence)
            else:
                frontiers.append(dict(sequence=event.sequence, code_link=encode(link.id),
                    reason='SOURCE_TEMPORAL_PORT_NOT_SELECTED'))
            if selection != 'ORIGINAL_SOURCE_PORT':
                frontiers.append(dict(sequence=event.sequence, code_link=encode(link.id), reason=selection))
            bindings.append(dict(sequence=event.sequence, activation=event.activation,
                invocation=encode(event.invocation), code_link=encode(link.id), interface=encode(body.id),
                source_ports=encode(selected), selection=selection,
                runtime_payload_or_saved_content_proven=False))
            counts[event.kind] += len(selected)
    index.check()
    return dict(capture=capture, events=events, interfaces=tuple(interfaces.values()), bindings=bindings,
        frontiers=frontiers, covered=len(covered), source_port_counts=dict(counts))


def build(interfaces, metadata, out, *, index=None):
    started = time.monotonic(); out = Path(out).absolute(); pins = _pins()
    if out.exists(): raise ValueError('fresh source-resumption output required')
    parent = _receipt(Path(interfaces).absolute()/'result.json'); raw = _receipt(Path(metadata).absolute())
    store = None
    if index is None:
        store = ObservedFunctionInterfaceStore(interfaces); index = store.index
    result = derive(index, metadata)
    _durable_mkdir(out)
    tables = {name: write_table(out/(name+'.jsonl.gz'), (encode(v, record_tags=P.PRODUCTION_RECORD_TAGS)
        if name in ('events','interfaces') else v for v in result[name]))
        for name in ('events', 'interfaces', 'bindings', 'frontiers')}
    report = dict(schema=SCHEMA, schema_version=1, pins=pins, parent=parent,
        metadata=raw, catalog=str(index.view.catalog.path), trace=str(index.codes.trace.directory),
        process_id=result['capture']['process_id'], tables=tables,
        records=len(result['events']), activations=result['capture']['activations'],
        source_body_interfaces=len(result['interfaces']), source_port_events=result['covered'],
        source_port_counts=result['source_port_counts'], frontier_count=len(result['frontiers']),
        original_body_bytes_copied=0, loops_unrolled=False, target_executed=False,
        contents_or_driver_normalization_proven=False, first_stage_complete=False,
        seconds=time.monotonic()-started)
    _check(parent); _check(raw); index.check()
    if store is not None: store.validate()
    if pins != _pins(): raise ValueError('source-resumption rules changed')
    _durable_bytes(out/'result.json', _json(report), replace=False)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--interfaces', required=True); parser.add_argument('--metadata', required=True)
    parser.add_argument('--out', required=True); args = parser.parse_args()
    r = build(args.interfaces, args.metadata, args.out)
    print(json.dumps({k: r[k] for k in ('records','activations','source_body_interfaces',
        'source_port_events','source_port_counts','frontier_count','seconds')}), flush=True)


if __name__ == '__main__': main()
