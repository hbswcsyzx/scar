"""One archived IR and bounded negative ownership mutations; no lowering.

The in-memory augmented fixture is deliberately not a published program or a
new source proof. Original artifacts remain byte-for-byte unchanged.
"""
from dataclasses import replace
import gzip
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import sys
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT))
started = time.perf_counter()
from scar.analysis.program_lowering import SourceProgram
from scar.ir.program.ids import UseID
from scar.ir.program.model import Use, UseRole
from scar.ir.program.source import UseSource
from scar.ir.program.structured import PythonProtocolKind as Kind
from scar.ir.semantics_v2 import Opcode

path = ROOT / 'artifacts/experiments/first_stage_source_language_bodies_attempt03_20261023/result/body-26.source-program5.json.gz'
raw = path.read_bytes()
program = SourceProgram.read_structure(json.loads(gzip.decompress(raw)), max_operations=4000)
module_path = HERE / 'proposal_sources/scar/analysis/source_tuple_validation.py'
spec = importlib.util.spec_from_file_location('scar.analysis.source_tuple_validation', module_path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

def checked(graph, metadata):
    return module.validate_tuple_key_ownership(program.structured, graph, program.interface,
        metadata, program.semantic, structural_only=True)

results = []
def rejects(name, graph, metadata, phrase):
    try:
        checked(graph, metadata)
    except ValueError as error:
        if phrase not in str(error):
            raise
        results.append({'case': name, 'rejected': True, 'error': str(error)})
    else:
        raise ValueError('invalid IR was not rejected: ' + name)

rejects('archived_tuple_failure_missing_elements', program.graph, program.metadata,
        'failure dropped/reordered pending element references')
operations = {row.id: row for row in program.graph.operations}
protocols = {row.operation: row for row in program.structured.protocols}
blocks = {block.id: block for region in program.graph.regions for block in region.blocks}
tuple_ids = [row.operation for row in program.metadata.operation_links if row.opcode is Opcode.BUILD_TUPLE]
if len(tuple_ids) != 1:
    raise ValueError('bounded original fixture does not have one tuple operation')
construction = operations[tuple_ids[0]]
failure = blocks[construction.terminator.successors[1].block]
cleanup = operations[failure.operations[0]]
if protocols[cleanup.id].kind is not Kind.FRAME_EXIT:
    raise ValueError('original fixture does not have its exact cleanup operation')
source = next(row.source for row in program.metadata.operation_links if row.operation == construction.id)
parts = tuple(use.value for use in construction.uses[:-1])
added = tuple(Use(UseID('isolated-tuple-failure-hold-' + str(i)), value, UseRole.REFERENCE)
              for i, value in enumerate(parts))
new_cleanup = replace(cleanup, uses=cleanup.uses[:-1] + added + cleanup.uses[-1:])
index = len(cleanup.uses) - 1
new_metadata = replace(program.metadata, use_links=program.metadata.use_links
    + tuple(UseSource(cleanup.id, use.id, source, 'held-temporary', index + i)
            for i, use in enumerate(added)))
new_graph = replace(program.graph, operations=tuple(new_cleanup if row.id == cleanup.id else row
                                                  for row in program.graph.operations))
positive = checked(new_graph, new_metadata)
results.append({'case': 'in_memory_retention_shape_only', 'accepted': True,
    'not_published_or_source_replayed': True, 'check': positive})

missing = replace(new_cleanup, uses=tuple(use for use in new_cleanup.uses if use.id != added[0].id))
missing_graph = replace(new_graph, operations=tuple(missing if row.id == cleanup.id else row
                                                  for row in new_graph.operations))
missing_metadata = replace(new_metadata, use_links=tuple(row for row in new_metadata.use_links
                                                        if row.use != added[0].id))
rejects('remove_one_pending_element', missing_graph, missing_metadata,
        'failure dropped/reordered pending element references')
if len(parts) > 1:
    reversed_cleanup = replace(new_cleanup, uses=cleanup.uses[:-1] + tuple(reversed(added)) + cleanup.uses[-1:])
    reversed_graph = replace(new_graph, operations=tuple(reversed_cleanup if row.id == cleanup.id else row
                                                       for row in new_graph.operations))
    rejects('reverse_pending_element_order', reversed_graph, new_metadata,
            'failure dropped/reordered pending element references')
if path.read_bytes() != raw:
    raise ValueError('original archived body drifted')
report = {'schema': 'scar.isolated-tuple-key-ir-check', 'schema_version': 1,
    'original_artifact': {'path': str(path), 'sha256': sha256(raw).hexdigest(), 'bytes': len(raw)},
    'validator': {'path': str(module_path), 'sha256': sha256(module_path.read_bytes()).hexdigest()},
    'checks': results, 'elapsed_s': time.perf_counter() - started,
    'source_or_code_proof_repeated': False, 'original_artifact_unchanged': True,
    'source_lowered': False, 'code_compiled': False, 'target_executed': False,
    'current_production_files_modified': False, 'whole_lifetime_verified': False}
(HERE / 'ir-check-final.json').write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps({'checks': len(results), 'elapsed_s': report['elapsed_s'],
                  'output': str(HERE / 'ir-check-final.json')}))
