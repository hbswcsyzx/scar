"""AST/import/schema check only; no worklist planning or worker execution."""
import ast
from hashlib import sha256
import inspect
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
path = ROOT / 'scar/analysis/source_frontend_worklist.py'
ast.parse(path.read_bytes(), filename=str(path))
from scar.analysis.source_frontend_worklist import (
    SourceFrontendBudget, SourceFrontendPlan, plan_source_frontend, run_source_frontend,
)
budget = SourceFrontendBudget()
modules = []
for name, module in sorted(sys.modules.items()):
    filename = getattr(module, '__file__', None)
    if name.startswith('scar.') and filename and Path(filename).resolve().is_relative_to(ROOT):
        raw = Path(filename).read_bytes()
        modules.append({'name': name, 'path': str(Path(filename).resolve()),
                        'sha256': sha256(raw).hexdigest(), 'bytes': len(raw)})
result = {'status': 'AST_IMPORT_AND_API_SCHEMA_PASS', 'owned_source_files': 1,
    'api': {fn.__name__: str(inspect.signature(fn)) for fn in (plan_source_frontend, run_source_frontend)},
    'budget_fields': list(budget.__dataclass_fields__), 'plan_fields': list(SourceFrontendPlan.__dataclass_fields__),
    'planner_called': False, 'worker_called': False, 'program_or_graph_loaded': False,
    'source_prepared': False, 'code_compiled_or_loaded': False, 'target_executed': False, 'modules': modules}
(HERE / 'minimal-api.json').write_text(json.dumps(result, indent=2)+'\n')
print(json.dumps({key:result[key] for key in ('status','planner_called','worker_called')}))
