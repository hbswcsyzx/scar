"""Complete ordinary consumers on the first original SP5; do not lower again."""
from dataclasses import replace
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import time

HERE = Path(__file__).resolve().parent; ROOT = HERE.parents[2]
spec = importlib.util.spec_from_file_location('ordinary_entry_inputs', ROOT/'artifacts/experiments/function_try_source_entries_20261026/common.py')
common = importlib.util.module_from_spec(spec); spec.loader.exec_module(common)
start = time.monotonic()
config = json.loads(Path('/home/zyf/AAA/scar-worktrees/source209-model/artifacts/experiments/source209_resume01_20261026/inputs.json').read_bytes())
owner, archives, catalog, metadata = common.normal_inputs(config, None)
old = json.loads((HERE/'first/worker/attempt-00001/result.json').read_bytes())
entry = catalog.resolve(old['entry_key']); context = catalog.prepare(entry)
from scar.analysis.source_frontend_worklist import _read_receipt
from scar.analysis.program_lowering import SourceProgram
from scar.analysis.source_language import SourceCodeEvidence, SourceLanguageOptions
from scar.analysis.structured_lowering import require_valid_structured_body
from scar.ir.program.source_language import SourceLanguageCapability as C
ref = old['program']; document, actual = _read_receipt(ref['uri'], limit=128_000_000)
assert all(ref[k] == actual[k] for k in ('physical_bytes','physical_sha256','decoded_bytes','decoded_sha256'))
body = SourceProgram.read_structure(document, max_operations=10_000, source_texts={entry.reference.snapshot.path:context.text})
evidence = SourceCodeEvidence.from_entry(catalog, entry)
options = SourceLanguageOptions(tuple(C(v) for v in old['active_capabilities']), evidence)
require_valid_structured_body(body.structured, body.graph, body.interface, body.metadata,
    semantic=body.semantic, control=body.control, language=body.language, source_tree=context.tree, language_options=options)
from scar.analysis.source_import_lowering import validate_imports
from scar.ir.program.structured import PythonProtocolKind as K
op = next(o for o in body.graph.operations if any(p.operation==o.id and p.kind is K.FUNCTION_IMPORT_NAME for p in body.structured.protocols))
wrong = replace(op, uses=(replace(op.uses[0],value=op.uses[1].value),)+op.uses[1:])
bad_graph = replace(body.graph,operations=tuple(wrong if o.id==op.id else o for o in body.graph.operations))
try:
    validate_imports(body.structured,bad_graph,body.interface,body.metadata,body.semantic,body.language,
        source_tree=context.tree,options=options)
except ValueError as error: rejection=str(error)
else: raise AssertionError('foreign builtins substituted for globals')
result = {'status':'INDEPENDENT_SOURCE_AND_READONLY_CODE_READER_PASS_WITH_OPEN',
    'entry_key':old['entry_key'],'source_calls':old['source_calls'],'program':ref,
    'operations_emitted':old['operations_emitted'],'original_worker_status':old['status'],
    'source_structure_reader':True,'independent_code_reader':True,'repeated_lower':False,
    'wrong_globals_rejected':rejection,'readonly_counts':[s.counts for s in archives._stores.values()],
    'compile':0,'raw':0,'target':0,'publication':0,'currentRun_binding':0,
    'elapsed_seconds':time.monotonic()-start}
common.save(HERE/'first-readback.json',result)
print(json.dumps(result,sort_keys=True))
