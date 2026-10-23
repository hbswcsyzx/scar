"""AST and import/API check only; no program/archive/model data is opened."""
import ast
from hashlib import sha256
import inspect
import json
from pathlib import Path
import sys
from typing import get_type_hints

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
paths = ['scar/analysis/source_program_publication.py', 'scar/analysis/inventory_partitions.py',
    'scar/ir/program/inventory.py', 'scar/analysis/program_inventory.py',
    'scar/analysis/program_composition.py', 'scar/analysis/source_language.py']
for name in paths:
    ast.parse((ROOT / name).read_bytes(), filename=name)
from scar.analysis.source_program_publication import publish_source_programs
from scar.analysis.program_composition import CompositionIndex, compose_source_publication
from scar.analysis.inventory_partitions import InventoryPartitions, TypedBodyPartition
from scar.analysis.call_demand import derive_call_source_admission
from scar.ir.program.inventory import BodyInventory
assert get_type_hints(BodyInventory)['construction_operations'] == int | None
modules = []
for name, module in sorted(sys.modules.items()):
    path = getattr(module, '__file__', None)
    if name.startswith('scar.') and path and Path(path).resolve().is_relative_to(ROOT):
        raw = Path(path).read_bytes()
        modules.append({'name': name, 'path': str(Path(path).resolve()), 'sha256': sha256(raw).hexdigest(), 'bytes': len(raw)})
doc = {'status': 'AST_AND_MINIMAL_IMPORT_API_PASS', 'ast_files': len(paths),
    'api': {name: str(inspect.signature(fn)) for name, fn in (
        ('publish_source_programs', publish_source_programs),
        ('compose_source_publication', compose_source_publication),
        ('derive_call_source_admission', derive_call_source_admission))},
    'typed_body_language_fields': list(TypedBodyPartition.__dataclass_fields__)[8:],
    'source_prepared': False, 'code_witness_loaded': False, 'source_compiled': False,
    'actual_publication_performed': False, 'target_executed': False, 'modules': modules}
(HERE / 'minimal-check.json').write_text(json.dumps(doc, indent=2) + '\n')
print(json.dumps({key: doc[key] for key in ('status', 'ast_files', 'actual_publication_performed')}))
