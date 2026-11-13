"""Lower receipt-bound external source representations in independent workers.

Greedy selection chooses code-equivalent representations for complete matched
CodeID coverage. It does not recover original compiler options, historical
source versions, root execution or callable environments. Source is never run.
"""
import argparse
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from hashlib import sha256
import json
import multiprocessing
from multiprocessing.util import Finalize
import os
from pathlib import Path
import time
from types import CodeType

from scar.analysis.compiled_local_interfaces import build_material_interfaces, CompiledLocalInterfaces
from scar.analysis.observed_compiled_material import build_local_material, ObservedCompiledLocalMaterial
from scar.analysis.observed_external_sources import ExternalSourceMatches
from scar.analysis.source_interface_store import file_receipt, projection_pins
from scar.analysis.source_stage import _durable_bytes, _durable_mkdir
from scar.analysis.source_template_links import _json
from scar.trace.code_snapshot import describe_code


SCHEMA = 'scar.external-source-materials'
_FALSE = ('target_executed', 'original_compile_options_proven', 'historical_source_version_proven',
    'root_entry_proven', 'execution_namespace_proven', 'capture_implies_body_entry',
    'source_code_temporal_pairing_proven', 'first_stage_complete')
_ENTRY_FIELDS = {'material', 'interfaces', 'unit', 'recipe', 'root_code', 'matched_captures',
    'compatible_recipes', 'external_group', 'source_id', 'origin'}
_MATCHES = _WORKER = _PINS = None


def _pins():
    from scar.analysis import observed_compiled_material, compiled_local_interfaces, observed_external_sources
    from scar.analysis.source_f4_variants import pins
    return dict(producer=sha256(Path(__file__).read_bytes()).hexdigest(), f4=pins(),
        interface_projection=projection_pins(), dependencies={name:sha256(Path(module.__file__).read_bytes()).hexdigest()
            for name,module in (('material', observed_compiled_material),
                ('interfaces', compiled_local_interfaces), ('matches', observed_external_sources))})


def _keys(match):
    return {(entry['capture']['process_id'], entry['capture']['code']['key'])
        for entry in match['matched_captures']}


def _representative(match, groups):
    recipes = groups[match['group']]['compatible_recipes']
    if not recipes: raise ValueError('external source group has no compatible recipe')
    for recipe in recipes:
        if (set(recipe) != {'filename', 'mode', 'flags', 'dont_inherit', 'optimize'}
                or recipe['mode'] != 'exec' or recipe['dont_inherit'] is not True
                or recipe['filename'] != match['root_code']['filename']):
            raise ValueError('external source group has another replay domain')
    return min(recipes, key=lambda recipe:(recipe['flags'],recipe['optimize']))


def _select(reader):
    buckets = defaultdict(list); expected = set(); directory = {}
    for match in reader.matches:
        group = match['group']
        if group in directory: raise ValueError('external source group appears twice')
        recipe = _representative(match, reader.groups)
        keys = _keys(match); expected.update(keys); directory[group] = match
        buckets[match['source'],recipe['filename']].append((match, recipe, keys))
    chosen = []
    for _, candidates in sorted(buckets.items()):
        remaining = set().union(*(entry[2] for entry in candidates))
        while remaining:
            match, recipe, keys = min(candidates, key=lambda item:(-len(item[2] & remaining),
                item[1]['flags'],item[1]['optimize'],item[0]['group']))
            if not keys & remaining: raise ValueError('external source greedy coverage stalled')
            chosen.append((match, recipe)); remaining.difference_update(keys)
            candidates = [entry for entry in candidates if entry[0]['group'] != match['group']]
    if set().union(*(_keys(match) for match,_ in chosen)) != expected:
        raise ValueError('external source selected groups do not cover all matched CodeIDs')
    return tuple(chosen), expected, tuple(sorted(set(directory)-{match['group'] for match,_ in chosen}))


def _verify_code(raw, recipe, match):
    code = compile(raw, recipe['filename'], recipe['mode'], flags=recipe['flags'],
        dont_inherit=True, optimize=recipe['optimize'])
    if describe_code(code) != match['root_code']:
        raise ValueError('external material replay differs from its full root descriptor')
    for entry in match['matched_captures']:
        child = code
        for ordinal in entry['constant_path']:
            if type(ordinal) is not int or not 0 <= ordinal < len(child.co_consts):
                raise ValueError('external source code constant path is outside its original root')
            child = child.co_consts[ordinal]
            if type(child) is not CodeType: raise ValueError('external source constant path is not a code child')
        if describe_code(child) != entry['capture']['code']:
            raise ValueError('external source child descriptor differs from the actual typed capture')


def _close_worker():
    global _WORKER
    if _WORKER is not None:
        _WORKER.close(); _WORKER = None


def _initialize_worker(matches_path, receipt, pins):
    from scar.analysis.source_template_workers import _initialize_worker as initialize
    from scar.analysis.source_symbol_variants import SymbolVariantWorker
    global _MATCHES, _WORKER, _PINS
    initialize()
    if _pins() != pins or file_receipt(Path(matches_path)/'result.json') != receipt:
        raise ValueError('external worker inputs or producer changed before initialization')
    _MATCHES = ExternalSourceMatches(matches_path); _PINS = pins
    _WORKER = SymbolVariantWorker()
    Finalize(None, _close_worker, exitpriority=10)


def _build_one(reader, worker, pins, match, recipe, out):
    started, cpu = time.monotonic(), time.process_time()
    if _pins() != pins: raise ValueError('external material producer changed before lowering')
    group, source_id = match['group'], match['source']
    raw = reader.read_source(source_id)
    if sha256(raw).hexdigest() != reader.sources[source_id]['snapshot']['sha256']:
        raise ValueError('external source bytes differ from the retained match')
    _verify_code(raw, recipe, match)
    folder = Path(out)/'materials'/group; interfaces = Path(out)/'interfaces'/group
    local = build_local_material(raw, recipe, folder, worker=worker)
    if (local['replayed_root_code'] != match['root_code']
            or local['snapshot']['sha256'] != sha256(raw).hexdigest()):
        raise ValueError('external local F4 has another source or compiler root')
    build_material_interfaces(folder, interfaces)
    material = ObservedCompiledLocalMaterial(folder)
    summary = CompiledLocalInterfaces(interfaces, material)
    material.validate_parents(); summary.validate_parents(); reader.check()
    if _pins() != pins: raise ValueError('external material producer changed during lowering')
    entry = dict(material=file_receipt(folder/'result.json'), interfaces=file_receipt(interfaces/'result.json'),
        unit=local['unit'], recipe=recipe, root_code=match['root_code'],
        matched_captures=match['matched_captures'],
        compatible_recipes=reader.groups[group]['compatible_recipes'], external_group=group,
        source_id=source_id, origin='CURRENT_SOURCE_CODE_MATCH')
    return entry, dict(worker_pid=os.getpid(), seconds=time.monotonic()-started,
        cpu_seconds=time.process_time()-cpu)


def _worker_task(task):
    match, recipe, out = task
    return _build_one(_MATCHES, _WORKER, _PINS, match, recipe, out)


def build_external_materials(matches_path, out, *, jobs=4):
    """Build actual F4/interface leaves covering every matched input CodeID."""
    from scar.analysis.source_symbol_variants import SymbolVariantWorker
    from scar.analysis.source_template_workers import _torch_guard
    started = time.monotonic(); matches_path = Path(matches_path).absolute(); out = Path(out).absolute()
    if matches_path.is_file(): matches_path = matches_path.parent
    if out.resolve() != out or out.exists() or type(jobs) is not int or not 1 <= jobs <= 8:
        raise ValueError('fresh canonical output and jobs in [1,8] required')
    reader = ExternalSourceMatches(matches_path)
    source_receipt = file_receipt(matches_path/'result.json'); pins = _pins()
    selected, expected, unselected = _select(reader)
    _durable_mkdir(out); _durable_mkdir(out/'materials'); _durable_mkdir(out/'interfaces')
    tasks = tuple((match, recipe, str(out)) for match,recipe in selected)
    if not tasks: results = []
    elif jobs == 1:
        with _torch_guard(), SymbolVariantWorker() as worker:
            results = [_build_one(reader,worker,pins,match,recipe,folder) for match,recipe,folder in tasks]
    else:
        with ProcessPoolExecutor(max_workers=min(jobs,len(tasks)),
                mp_context=multiprocessing.get_context('spawn'), initializer=_initialize_worker,
                initargs=(str(matches_path),source_receipt,pins)) as pool:
            results = list(pool.map(_worker_task,tasks,chunksize=1))
    entries = [entry for entry,_ in results]
    if any(set(entry) != _ENTRY_FIELDS for entry in entries):
        raise ValueError('external material entry contract differs')
    covered = {(item['capture']['process_id'],item['capture']['code']['key'])
        for entry in entries for item in entry['matched_captures']}
    if covered != expected or len({entry['unit'] for entry in entries}) != len(entries):
        raise ValueError('external source material coverage or independent unit identities differ')
    reader.check()
    if file_receipt(matches_path/'result.json') != source_receipt or _pins() != pins:
        raise ValueError('external source material inputs or producer changed before publication')
    report = dict(schema=SCHEMA, schema_version=1, status='EXTERNAL_SOURCE_MATERIALS_BUILT',
        source_reader=source_receipt, entries=entries,
        coverage=dict(expected_keys=sorted(expected), covered_keys=sorted(covered), complete=True),
        selected_groups=[match['group'] for match,_ in selected], unselected_groups=unselected,
        group_evidence='ALL_ROOT_GROUPS_AND_COMPATIBLE_RECIPES_RETAINED_BY_SOURCE_READER_RECEIPT',
        selection='PER_SOURCE_AND_FILENAME_GREEDY_CODE_COVERAGE_NOT_ORIGINAL_COMPILER_REQUEST',
        jobs=jobs, worker_pids=sorted({timing['worker_pid'] for _,timing in results}),
        worker_seconds=sum(timing['seconds'] for _,timing in results),
        worker_cpu_seconds=sum(timing['cpu_seconds'] for _,timing in results), pins=pins,
        implementation_sha256=pins['producer'],
        **{name:False for name in _FALSE}, seconds=time.monotonic()-started)
    _durable_bytes(out/'result.json', _json(report), replace=False)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--matches',required=True); parser.add_argument('--out',required=True)
    parser.add_argument('--jobs',type=int,default=4); args = parser.parse_args()
    report = build_external_materials(args.matches,args.out,jobs=args.jobs)
    print(json.dumps(dict(status=report['status'],units=len(report['entries']),
        matched_code_templates=len(report['coverage']['covered_keys']),
        jobs=report['jobs'],worker_pids=report['worker_pids'],seconds=report['seconds'])),flush=True)


if __name__ == '__main__': main()
