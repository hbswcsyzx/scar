"""Connect software interfaces and artifacts to a retained target description.

Candidates express compatible locations/referents, not allocations, selected
devices, resource consumption, or transfer events. Source routes express
normalization dependencies, never equality with native values or storage.
"""
import argparse
from collections import Counter,defaultdict
import gzip
from hashlib import sha256
import json
import os
from pathlib import Path
import time

from scar.analysis.python_binding_query import PythonBindingGraph
from scar.analysis.target_graph import TargetHardwareGraph,_artifact
from scar.analysis.source_stage import _durable_bytes,_durable_mkdir
from scar.analysis.source_template_links import _json,_stream
from scar.ir.program import software_resources as S,target_hardware as H,native_resource_declarations as R,python_bindings as B,source_productions as P
from scar.ir.program.providers import ProviderFactReference
from scar.ir.record_codec import decode


def _records(directory,receipt,cls):
    payload=(directory/receipt['path']).read_bytes()
    if len(payload)!=receipt['bytes'] or sha256(payload).hexdigest()!=receipt['sha256']:raise ValueError('resource declaration table differs')
    raw=gzip.decompress(payload)
    if len(raw)!=receipt['decoded_bytes'] or sha256(raw).hexdigest()!=receipt['decoded_sha256'] or raw.count(b'\n')!=receipt['records']:
        raise ValueError('decoded resource declaration table differs')
    return tuple(decode(cls,json.loads(line),record_tags=P.PRODUCTION_RECORD_TAGS) for line in raw.splitlines())


def _input_sources(definition,operand,native_name,*,result,positional,keywords,positional_pack,keyword_pack,
        receiver,receiver_mode,conditions,semantics=S.NormalizationDependencyKind.CALL):
    if definition.implicit_receiver and native_name==definition.implicit_receiver:
        kind=S.OperandSourceKind.RECEIVER if receiver is not None else S.OperandSourceKind.RECEIVER_OPEN
        actuals=() if receiver is None else (receiver,)
        if receiver is None and receiver_mode=='UNBOUND' and positional_pack is not None:
            kind=S.OperandSourceKind.PACK_DEPENDENCY;actuals=(positional_pack,)
        yield S.OperandSource(result,definition.id,operand.boundary,operand.port,definition.implicit_receiver,
            actuals,kind,None,(*conditions,'METHOD_RECEIVER_DEPENDENCY_NOT_STORAGE_ALIAS'),semantics)
        return
    params={a.parser_index:a for a in definition.arguments};found=False
    for conversion in definition.conversions:
        if conversion.stage is not B.ConversionStage.PYTHON_PARSE or native_name not in conversion.schema_arguments:continue
        if conversion.parser_index not in params:continue
        argument=params[conversion.parser_index];found=True;named=dict(keywords)
        actuals=();kind=S.OperandSourceKind.CONVERSION_OPEN;expression=None
        if argument.name in named:
            kind=S.OperandSourceKind.KEYWORD;actuals=(named[argument.name],)
        elif keyword_pack is not None or (not argument.keyword_only and positional_pack is not None):
            # CALL_FUNCTION_EX retains whole evaluated packs. Either pack can
            # supply a positional-or-keyword parameter; **kwargs does not
            # erase the *args dependency. This is not a binding/alias proof.
            kind=S.OperandSourceKind.PACK_DEPENDENCY
            actuals=tuple(p for p in (None if argument.keyword_only else positional_pack,keyword_pack) if p is not None)
        elif argument.position is not None and argument.position+(1 if receiver_mode=='UNBOUND' else 0)<len(positional):
            shift=1 if receiver_mode=='UNBOUND' else 0
            kind=S.OperandSourceKind.POSITIONAL;actuals=(positional[argument.position+shift],)
        elif argument.default is not None or argument.default_init is not None:
            kind=S.OperandSourceKind.DEFAULT_EXPRESSION;expression=argument.default_init or argument.default
        yield S.OperandSource(result,definition.id,operand.boundary,operand.port,argument.name,actuals,kind,expression,
            (*conditions,'PARSER_SIGNATURE_ACCEPTS_ACTUAL_ARGUMENTS','NORMALIZATION_DEPENDENCY_NOT_NATIVE_VALUE_ALIAS'),semantics)
    if not found:
        kind=S.OperandSourceKind.RECEIVER_OPEN if definition.implicit_receiver and native_name=='self' else S.OperandSourceKind.CONVERSION_OPEN
        yield S.OperandSource(result,definition.id,operand.boundary,operand.port,None,(),kind,None,
            (*conditions,'RECEIVER_OR_CONVERSION_BINDING_OPEN'),semantics)


def _operand_sources(definition,call,operand,native_name):
    site=call.site
    yield from _input_sources(definition,operand,native_name,result=site.result,positional=site.positional,
        keywords=site.keywords,positional_pack=site.positional_pack,keyword_pack=site.keyword_pack,
        receiver=call.receiver,receiver_mode=call.receiver_mode,conditions=call.conditions)


def _operator_sources(definition,call,operand,native_name):
    # These are the implicit protocol's parser dependencies, not a fabricated
    # source CALL/SourceCallSite. The language operation keeps its original ABI.
    yield from _input_sources(definition,operand,native_name,result=call.result,positional=call.arguments,
        keywords=(),positional_pack=None,keyword_pack=None,receiver=call.receiver,
        receiver_mode=B.ReceiverMode.BOUND,conditions=call.conditions,semantics=S.NormalizationDependencyKind.LANGUAGE_PROTOCOL)


def build_software_resources(bindings,declarations,target,out):
    started=time.monotonic();view=PythonBindingGraph(bindings);hardware=TargetHardwareGraph(target)
    declarations=Path(declarations).absolute();out=Path(out).absolute()
    if out.exists():raise ValueError('fresh software/target output required')
    raw=(declarations/'result.json').read_bytes();report=json.loads(raw)
    if report['schema']!='scar.native-resource-declarations' or report['schema_version']!=1:raise ValueError('resource declarations version differs')
    if report['bindings_result_sha256']!=sha256((view.path/'result.json').read_bytes()).hexdigest():raise ValueError('resource declaration binding scope differs')
    if report['types_sha256']!=sha256(Path(R.__file__).read_bytes()).hexdigest():raise ValueError('resource declaration types differ')
    operands=_records(declarations,report['resource_operands'],R.ResourceOperand)
    resources=hardware.resources();snapshot=_artifact(hardware.path/'result.json','scar.target-hardware-graph')
    evidence=_artifact(declarations/report['resource_operands']['path'],'scar.native-resource-operands+gzip-jsonl')
    placements=[];by_boundary=defaultdict(list)
    for index,operand in enumerate(operands,1):
        by_boundary[operand.boundary].append(operand)
        declaration=ProviderFactReference(evidence,'jsonl:'+str(index))
        for resource in resources:
            if operand.category is R.ResourceOperandKind.TENSOR_ARGUMENT and type(resource) is H.MemoryDomain:
                relation=H.ResourceCandidateKind.TENSOR_STORAGE_POOL
                conditions=('PRESENT_MATERIALIZED_TENSOR','SOURCE_DEVICE_AND_STORAGE_PLACEMENT_MATCH','TARGET_ACCESS_POLICY_MATCHES')
            elif operand.category is R.ResourceOperandKind.DEVICE_ARGUMENT and type(resource) in (H.CpuExecutor,H.Accelerator):
                relation=H.ResourceCandidateKind.DEVICE_REFERENT
                conditions=('DEVICE_VALUE_PRESENT','FRAMEWORK_VISIBILITY_AND_TARGET_MAPPING_MATCHES')
            elif operand.category is R.ResourceOperandKind.GENERATOR_ARGUMENT and type(resource) in (H.CpuExecutor,H.Accelerator):
                relation=H.ResourceCandidateKind.GENERATOR_DEVICE
                conditions=('GENERATOR_PRESENT','GENERATOR_DEVICE_AND_TARGET_MAPPING_MATCHES','NO_RNG_CONSUMPTION_CLAIM')
            else:continue
            placements.append(S.OperandTargetCandidate(operand.boundary,operand.port,declaration,H.TargetResourceRef(snapshot,resource.id),relation,conditions))
    definitions={d.id:d for d in view.definitions()};sources=[];port_names={};materials={}
    def interface_sources(call,definition,operator=False):
        if definition.native is None:return
        boundary=definition.native.boundary
        if boundary not in port_names:
            graph=view.expand_native(definition);native=next(b for b in graph.native_boundaries if b.id==boundary)
            artifact=native.signature.artifact;key=(artifact.uri,artifact.sha256,artifact.size_bytes)
            if key not in materials:
                payload=Path(artifact.uri).read_bytes()
                if len(payload)!=artifact.size_bytes or sha256(payload).hexdigest()!=artifact.sha256:
                    raise ValueError('native normalization materials differ')
                materials[key]=json.loads(payload)
            material=materials[key]
            index=int(native.signature.locator.split('/')[2]);names=material['declarations'][index]['inputs']
            port_names[boundary]={slot.port:row['name'] for slot,row in zip(native.inputs,names,strict=True)}
        resolver=_operator_sources if operator else _operand_sources
        for operand in by_boundary[boundary]:sources.extend(resolver(definition,call,operand,port_names[boundary][operand.port]))
    for call in view.native_calls():interface_sources(call,definitions[call.binding])
    for call in view.declared_operators():
        if call.binding is not None:interface_sources(call,definitions[call.binding],True)
    endpoints=[r for r in resources if type(r) is H.StorageEndpoint]
    locations=[];facts=_artifact(view.source.facts/'result.json','scar.normal-source-link-facts')
    for index,row in enumerate(view.source.inputs['units']):
        path=Path(row['path']).resolve();matches=[e for e in endpoints if path.is_relative_to(Path(e.mount_point))]
        endpoint=max(matches,key=lambda e:len(e.mount_point)) if matches else None
        # Match actual filesystem IDs at this platform observation. The IDs
        # are routing helpers, not OS objects/nodes in the optimization graph.
        try:matches_device=endpoint is not None and path.stat().st_dev==Path(endpoint.mount_point).stat().st_dev
        except OSError:matches_device=False
        locations.append(S.SoftwareArtifactLocation(row['unit'],row['path'],str(path),
            H.TargetResourceRef(snapshot,endpoint.id) if matches_device else None,
            ProviderFactReference(facts,'#/units/'+str(index)+'/path')))
    _durable_mkdir(out)
    pt=_stream(out/'operand-targets.jsonl.gz',placements);st=_stream(out/'operand-sources.jsonl.gz',sources)
    at=_stream(out/'artifact-locations.jsonl.gz',locations)
    result=dict(schema='scar.software-target-resource-graph',schema_version=2,status='CONDITIONAL_RESOURCE_RELATIONSHIPS_BUILT',
        bindings=str(view.path),bindings_result_sha256=sha256((view.path/'result.json').read_bytes()).hexdigest(),
        declarations=str(declarations),declaration_result_sha256=sha256(raw).hexdigest(),
        target=str(hardware.path),target_result_sha256=snapshot.sha256,
        operand_targets=pt,operand_sources=st,artifact_locations=at,source_kinds=dict(Counter(row.kind.value for row in sources)),
        source_semantics=dict(Counter(row.semantics.value for row in sources)),
        source_artifacts_with_endpoints=sum(row.endpoint is not None for row in locations),
        actual_placement_established=False,resource_uses_created=0,transfers_observed=0,target_program_executed=False,first_stage_complete=False,
        implementation_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),types_sha256=sha256(Path(S.__file__).read_bytes()).hexdigest(),
        seconds=time.monotonic()-started)
    _durable_bytes(out/'result.json',_json(result),replace=False);return result


class SoftwareResourceGraph:
    def __init__(self,path):
        self.path=Path(path).absolute();self.report=json.loads((self.path/'result.json').read_bytes())
        if self.report['schema']!='scar.software-target-resource-graph' or self.report['schema_version']!=2:raise ValueError('software resource graph version differs')
        if self.report['implementation_sha256']!=sha256(Path(__file__).read_bytes()).hexdigest():raise ValueError('software resource builder differs')
        if self.report['types_sha256']!=sha256(Path(S.__file__).read_bytes()).hexdigest():raise ValueError('software resource types differ')
        self.bindings=PythonBindingGraph(self.report['bindings']);self.hardware=TargetHardwareGraph(self.report['target'])
        for key,path_ in (('bindings_result_sha256',self.bindings.path),('target_result_sha256',self.hardware.path),
                ('declaration_result_sha256',Path(self.report['declarations']))):
            if sha256((path_/'result.json').read_bytes()).hexdigest()!=self.report[key]:raise ValueError('software resource parent differs')

    def candidates(self,boundary=None):
        rows=_records(self.path,self.report['operand_targets'],S.OperandTargetCandidate)
        return tuple(row for row in rows if boundary is None or row.boundary==boundary)

    def sources(self,source=None):
        unit=self.bindings.source.units_for_source(source)
        rows=_records(self.path,self.report['operand_sources'],S.OperandSource)
        return tuple(row for row in rows if unit is None or row.call.unit in unit)

    def artifact_locations(self):
        return _records(self.path,self.report['artifact_locations'],S.SoftwareArtifactLocation)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('bindings','declarations','target','out'):parser.add_argument('--'+name,required=True)
    args=parser.parse_args();r=build_software_resources(args.bindings,args.declarations,args.target,args.out)
    print(json.dumps({k:r[k] for k in ('status','source_kinds','source_artifacts_with_endpoints','seconds')},indent=2))


if __name__=='__main__':main()
