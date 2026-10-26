"""Reconsume the existing small original SP5 after stricter source guards."""
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import time

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2];start=time.monotonic()
spec=importlib.util.spec_from_file_location('ordinary_entry_inputs',ROOT/'artifacts/experiments/function_try_source_entries_20261026/common.py')
common=importlib.util.module_from_spec(spec);spec.loader.exec_module(common)
config=json.loads(Path('/home/zyf/AAA/scar-worktrees/source209-model/artifacts/experiments/source209_resume01_20261026/inputs.json').read_bytes())
owner,archives,catalog,metadata=common.normal_inputs(config,None)
row=json.loads((HERE/'entry-01/worker/attempt-00001/result.json').read_bytes())
entry=catalog.resolve(row['entry_key']);context=catalog.prepare(entry)
from scar.analysis.inventory_partitions import _read_receipt
from scar.analysis.program_lowering import SourceProgram
from scar.analysis.source_language import SourceLanguageOptions,SourceCodeEvidence
from scar.analysis.structured_lowering import require_valid_structured_body
from scar.ir.program.source_language import SourceLanguageCapability as C
document,receipt=_read_receipt(row['program']['uri'],limit=128_000_000)
assert all(receipt[k]==row['program'][k]for k in('physical_bytes','physical_sha256','decoded_bytes','decoded_sha256'))
result=SourceProgram.read_structure(document,max_operations=4000,source_texts={entry.reference.snapshot.path:context.text})
options=SourceLanguageOptions(tuple(C(v)for v in row['active_capabilities']),SourceCodeEvidence.from_entry(catalog,entry))
require_valid_structured_body(result.structured,result.graph,result.interface,result.metadata,semantic=result.semantic,
    control=result.control,language=result.language,source_tree=context.tree,language_options=options)
common.save(HERE/'guard-readback.json',{'status':'EXACT_PACKET_CARRIER_AND_SUPPRESSION_SOURCE_GUARD_PASS',
    'entry_key':row['entry_key'],'program':row['program'],'operations':row['operations_emitted'],
    'source_sha256':sha256((ROOT/'scar/analysis/source_with_validation.py').read_bytes()).hexdigest(),
    'readonly_counts':[s.counts for s in archives._stores.values()],'lower':0,'compile':0,'target':0,'raw':0,
    'elapsed_seconds':time.monotonic()-start})
print('normal existing-body structure/source/CodeWitness PASS',time.monotonic()-start)
