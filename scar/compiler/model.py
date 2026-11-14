"""CPU array-region profile and versioned macro execution-plan contracts.

This bounded profile is a derived optimization IR, not a replacement for the
whole-program graph. Source IDs survive lowering; runtime type/layout guards
qualify NumPy semantics. An elementwise body is shared by explicit loop axes.
"""
from dataclasses import dataclass, field, asdict
import json
from pathlib import Path

SCHEMA='scar.execution-plan'
PROFILE='cpu-array-region-v1'
OPS=frozenset(('input','const','slice','add','sub','mul','div','neg'))

@dataclass(frozen=True)
class SourceRef:
    path: str
    sha256: str
    qualname: str
    line: int
    column: int
    code_key: str
    origins: tuple[dict,...]=()

@dataclass(frozen=True)
class Expr:
    id: str
    op: str
    inputs: tuple[str,...]=()
    attrs: dict=field(default_factory=dict)

@dataclass(frozen=True)
class ArrayRegion:
    id: str
    source: SourceRef
    parameters: tuple[str,...]
    nodes: tuple[Expr,...]
    output: str
    assumptions: tuple[str,...]=('EXACT_NUMPY_NDARRAY_FLOAT64_CPU_2D','FRESH_OUTPUT','NO_INPUT_WRITES')
    frontiers: tuple[str,...]=()

@dataclass(frozen=True)
class LoopAxis:
    variable: str
    extent: str

@dataclass(frozen=True)
class CpuPlacement:
    """A CPU execution allocation tied to an original hardware snapshot.

    The memory domain names a planning candidate. UNBOUND explicitly does
    not promise NUMA page placement, residency, or an available byte budget.
    """
    target_path: str
    target_sha256: str
    executor_id: str
    cpu_ids: tuple[int,...]
    memory_domain_id: str|None=None
    memory_budget_bytes: int|None=None
    numa_node: int|None=None
    memory_policy: str='UNBOUND'
    evidence: tuple[dict,...]=()

@dataclass(frozen=True)
class ExecutionPlan:
    region: ArrayRegion
    schema_version: int=1
    profile: str=PROFILE
    operator_abi_version: int=1
    schedule: tuple[LoopAxis,...]=(LoopAxis('row','output.shape[0]'),LoopAxis('col','output.shape[1]'))
    device: str='cpu'
    buffer_policy: str='fresh_output'
    passes: tuple[str,...]=()
    proof: dict=field(default_factory=dict)
    cost: dict=field(default_factory=dict)
    cpu_threads: int=1
    resource_binding: CpuPlacement|None=None

def region_from_dict(r):
    src=dict(r['source']);src['origins']=tuple(src.get('origins',()))
    return ArrayRegion(r['id'],SourceRef(**src),tuple(r['parameters']),
        tuple(Expr(n['id'],n['op'],tuple(n.get('inputs',())),n.get('attrs',{})) for n in r['nodes']),
        r['output'],tuple(r.get('assumptions',())),tuple(r.get('frontiers',())))

def plan_from_dict(r):
    r=dict(r)
    if r.pop('schema',None)!=SCHEMA:raise ValueError('unsupported execution plan schema')
    r['region']=region_from_dict(r['region'])
    r['schedule']=tuple(LoopAxis(**a) for a in r['schedule']);r['passes']=tuple(r.get('passes',()))
    if r.get('resource_binding') is not None:
        binding=dict(r['resource_binding'])
        binding['cpu_ids']=tuple(binding['cpu_ids']);binding['evidence']=tuple(binding.get('evidence',()))
        r['resource_binding']=CpuPlacement(**binding)
    return ExecutionPlan(**r)

def document(plan):
    result=dict(schema=SCHEMA,**asdict(plan))
    # Preserve the exact canonical document/digest of previously shipped v1
    # plans. Resource-bound plans explicitly opt into schema v2.
    if plan.resource_binding is None:result.pop('resource_binding')
    return result
def write_plan(plan,path):Path(path).write_text(json.dumps(document(plan),indent=2,allow_nan=False)+'\n')
def read_plan(path):return plan_from_dict(json.loads(Path(path).read_text()))
