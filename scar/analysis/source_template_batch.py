"""Read selected original plans with one sealed graph/domain pass per batch.

This is an adapter over existing F4 stores, not a new source frontend. It
retains full fragment/plan admission and only returns after EOF validation.
"""
from collections import OrderedDict, defaultdict
from hashlib import sha256
import json
from pathlib import Path

from scar.analysis.source_productions import _digest, read_production_plan
from scar.analysis.source_template_links import (
    _implementation, _require, _worker_stores, read_template_graph,
)
from scar.ir.program import source_productions as P, source_template_links as T


_GRAPHS = OrderedDict()


def _graph(store, unit, raw, report):
    """Reuse admitted typed graphs only while their original bytes still match."""
    _require(store.resolve() == store and type(unit) is str
        and Path(unit).name == unit and unit not in ('', '.', '..'), store, 'invalid store or source unit')
    key = str(store), unit, sha256(raw).hexdigest()
    graph = _GRAPHS.get(key)
    if graph is None:
        graph = read_template_graph(store, unit)
    else:
        _require(report['link_types_sha256'] == sha256(Path(T.__file__).read_bytes()).hexdigest()
            and report['generator_sha256'] == _implementation(), store, 'stored interface or generator declarations differ')
        entries = [row for row in report['units'] if row['unit'] == unit]
        _require(len(entries) == 1 and entries[0]['header'] == 'units/' + unit + '/header.json',
            unit, 'source header identity differs')
        row = entries[0]; path = store / row['header']
        _require(path.resolve() == path and path.is_relative_to(store), unit, 'unsafe unit header')
        header = path.read_bytes()
        _require(len(header) == row['header_bytes'] and sha256(header).hexdigest() == row['header_sha256'],
            unit, 'unit header receipt differs')
        header = json.loads(header)
        for name in ('templates', 'links'):
            descriptor = header[name]; fragment = path.parent / descriptor['path']
            _require(fragment.resolve() == fragment and fragment.parent == path.parent, path, 'unsafe graph table')
            payload = fragment.read_bytes()
            _require(len(payload) == descriptor['bytes'] and sha256(payload).hexdigest() == descriptor['sha256'],
                path, 'graph table compressed receipt differs')
    _require((store / 'result.json').read_bytes() == raw, unit, 'template graph root changed during admission')
    _GRAPHS[key] = graph
    _GRAPHS.move_to_end(key)
    while len(_GRAPHS) > 2:
        _GRAPHS.popitem(last=False)
    return graph


def read_template_bodies(store, unit, keys, *, max_visits=1_000_000):
    """Expand multiple original nodes without repeatedly scanning their unit.

    Typed graphs are reused only after checking their original byte receipts
    and current declarations. Parent proofs are checked before returning,
    every selected domain is exhausted once, and every selected plan receives
    its original structural/control-flow admission. No bodies are cached and
    no target Python is imported/executed.
    """
    keys = tuple(dict.fromkeys(keys))
    _require(all(type(key) is T.SourceTemplateKey for key in keys), unit, 'invalid template keys')
    if not keys:
        return {}
    store = Path(store).absolute()
    raw = (store / 'result.json').read_bytes()
    report = json.loads(raw)
    graph = _graph(store, unit, raw, report)
    nodes = {node.key: node for node in graph.templates}
    _require(all(key in nodes for key in keys), unit, 'selected template is absent')
    specifications = tuple((p['domain'], p['materials'], p['verification'],
        p['collection_sha256'], p['verification_sha256']) for p in report['parents'])
    parents = {parent.domain: parent for parent in _worker_stores(specifications, report['model_manifest_sha256'])}
    selected = defaultdict(lambda: defaultdict(list))
    for key in keys:
        node = nodes[key]
        selected[node.origin.domain][node.origin.line].append((key, node))
    result = {}
    for domain, lines in selected.items():
        material = parents[domain]
        parent = next(p for p in report['parents'] if p['domain'] == domain.value)
        _require(material.receipt == parent, unit, 'parent proof changed since interface linking')
        _check_catalog(material, unit)
        basis = material.basis[unit]
        # records() hashes the complete original fragment, including records
        # after the final selected line. Nothing escapes before that check.
        for _, line, document in material.records(dict(key=unit, **{k:v for k,v in basis.items() if k!='unit'})):
            if line not in lines:
                continue
            digest = _digest(document)
            _require(all(digest == node.origin.plan_sha256 for _, node in lines[line]),
                unit, 'original recipe body differs')
            plan = read_production_plan(document, max_visits=max_visits)
            for key, node in lines[line]:
                _require(plan.source == P.ProductionOccurrence(key.occurrence)
                    and plan.purpose is key.purpose and plan.root == node.root
                    and plan.input == graph.input and plan.profile == graph.profile,
                    key, 'original recipe identity/input/profile differs')
                result[key] = plan
    _require(set(result) == set(keys), unit, 'selected recipe is absent from its original domain')
    for parent in report['parents']:
        material = parents[T.SourceMaterialDomain(parent['domain'])]
        _require(material.receipt == parent, unit, 'parent proof changed since interface linking')
        _check_catalog(material, unit)
        _require(material.unchanged() and material.generator_pins == _implementation(),
            unit, 'original material changed during batch reading')
    _require((store / 'result.json').read_bytes() == raw, unit, 'template graph root changed during batch reading')
    return {key: result[key] for key in keys}


def _check_catalog(material, unit):
    # _worker_stores caches admitted catalogs, whereas unchanged() checks
    # reports and the current schema/compiler. Keep fresh on-disk catalog
    # admission as well; a cache hit must not conceal a changed catalog.
    raw = (material.root / 'catalog.json').read_bytes()
    _require(sha256(raw).hexdigest() == material.rows[unit]['catalog_sha256']
        and (material.verification / 'catalog.json').read_bytes() == raw,
        unit, 'parent catalog differs')
