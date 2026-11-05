"""Project exact resource-related input types and dispatch declarations."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import time

from scar.analysis.python_binding_query import PythonBindingGraph
from scar.analysis.source_stage import _durable_bytes,_durable_mkdir
from scar.analysis.source_template_links import _json,_stream
from scar.ir.program.providers import ProviderFactReference
from scar.ir.program import native_resource_declarations as R


def _projections(type_,path=(),pointer=''):
    if type_['kind'] in ('OptionalType','ListType'):
        projection=R.TypeProjection.OPTIONAL_ELEMENT if type_['kind']=='OptionalType' else R.TypeProjection.LIST_ELEMENT
        yield from _projections(type_['element'],(*path,projection),pointer+'/element')
    elif type_['kind']=='BaseType':
        kind={'Tensor':R.ResourceOperandKind.TENSOR_ARGUMENT,'Device':R.ResourceOperandKind.DEVICE_ARGUMENT,
            'Generator':R.ResourceOperandKind.GENERATOR_ARGUMENT}.get(type_.get('name'))
        if kind is not None:yield kind,type_['text'],path,pointer


def build_resource_declarations(bindings,out):
    started=time.monotonic();view=PythonBindingGraph(bindings);out=Path(out).absolute()
    if out.exists():raise ValueError('fresh resource declaration output required')
    operands=[];dispatch=[];seen=set();materials={}
    for definition in view.definitions():
        if definition.native is None or definition.native.boundary in seen:continue
        graph=view.expand_native(definition);boundary=next(b for b in graph.native_boundaries if b.id==definition.native.boundary)
        seen.add(boundary.id);artifact=boundary.signature.artifact
        if artifact.sha256 not in materials:
            raw=Path(artifact.uri).read_bytes()
            if len(raw)!=artifact.size_bytes or sha256(raw).hexdigest()!=artifact.sha256:raise ValueError('native declaration materials differ')
            materials[artifact.sha256]=json.loads(raw)
        pointer=boundary.signature.locator.rsplit('/',1)[0];row=materials[artifact.sha256]
        for key in pointer.removeprefix('#/').split('/'):row=row[int(key)] if type(row) is list else row[key]
        for index,(parameter,slot) in enumerate(zip(row['inputs'],boundary.inputs,strict=True)):
            for category,type_,path,tail in _projections(parameter['type']):
                operands.append(R.ResourceOperand(boundary.id,slot.port,category,type_,path,
                    ProviderFactReference(artifact,pointer+'/inputs/'+str(index)+'/type'+tail)))
        for index,candidate in enumerate(row['dispatch']):
            dispatch.append(R.DeclaredDispatchCandidate(boundary.id,tuple(candidate['keys']),candidate['symbol'],
                ProviderFactReference(artifact,pointer+'/dispatch/'+str(index))))
    _durable_mkdir(out);ot=_stream(out/'operands.jsonl.gz',operands);dt=_stream(out/'dispatch.jsonl.gz',dispatch)
    result=dict(schema='scar.native-resource-declarations',schema_version=1,status='DECLARED_OPERANDS_AND_DISPATCH',
        bindings=str(view.path),bindings_result_sha256=sha256((view.path/'result.json').read_bytes()).hexdigest(),
        native_boundaries=len(seen),resource_operands=ot,dispatch_candidates=dt,
        physical_resources_bound=False,resource_uses_created=0,kernels_observed=0,copies_observed=0,
        type_is_not_consumption_proof=True,target_executed=False,first_stage_complete=False,
        implementation_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),types_sha256=sha256(Path(R.__file__).read_bytes()).hexdigest(),
        seconds=time.monotonic()-started)
    _durable_bytes(out/'result.json',_json(result),replace=False);return result


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--bindings',required=True);parser.add_argument('--out',required=True)
    args=parser.parse_args();r=build_resource_declarations(args.bindings,args.out)
    print(json.dumps({k:r[k] for k in ('status','native_boundaries','seconds')},indent=2))


if __name__=='__main__':main()
