"""Publish runtime/source channels with one admitted code/source index.

All channels use existing producers and original IDs. This coordinator avoids
reconstructing the same index when adding an optional observation channel.
"""
import argparse
import json
from pathlib import Path
import time

from scar.analysis.program_view import ProgramView
from scar.analysis.source_call_view import open_function_interfaces
from scar.analysis.source_observed_codes import ObservedSourceCodeProvider
from scar.analysis.source_observed_calls import ObservedSourceCallsiteIndex
from scar.analysis.source_observed_interfaces import build_observed_interfaces
from scar.analysis.source_declared_catalog import _receipt
from scar.analysis.source_stage import _durable_bytes
from scar.analysis.source_template_links import _json


def publish(parent,trace,project_root,out,*,boundaries_out=None,activations_out=None,
        graph_check_out=None,resource_scopes_out=None,resumptions_out=None):
    timings={}
    def phase(name, function, *args, **kwargs):
        print(json.dumps(dict(channel=name,status='RUNNING')),flush=True)
        started=time.monotonic();result=function(*args,**kwargs);timings[name]=time.monotonic()-started
        print(json.dumps(dict(channel=name,status='ADMITTED',seconds=timings[name])),flush=True)
        return result
    parent=phase('parent-interfaces',open_function_interfaces,parent);view=ProgramView(parent.catalog)
    codes=phase('source-code-index',ObservedSourceCodeProvider,view,trace,project_root)
    index=phase('source-callsite-index',ObservedSourceCallsiteIndex,codes)
    report=phase('observed-function-interfaces',build_observed_interfaces,parent,index,out)
    if boundaries_out:
        from scar.analysis.source_observed_boundaries import build_boundaries
        phase('native-boundaries',build_boundaries,index,boundaries_out)
    if activations_out:
        from scar.analysis.source_body_activations import build_body_activations
        phase('body-activations',build_body_activations,index,activations_out)
        if graph_check_out:
            from scar.analysis.source_body_activation_view import verify_body_activations
            phase('body-graph-check',verify_body_activations,activations_out,graph_check_out,index=index)
    if resource_scopes_out:
        from scar.analysis.source_resource_scopes import build_resource_scopes
        phase('resource-scopes',build_resource_scopes,Path(trace).resolve().parent,resource_scopes_out,
            catalog=parent.catalog.path,project_root=project_root,index=index,
            graph_check_out=Path(resource_scopes_out)/'graph-check.json')
    resumptions=[]
    if resumptions_out:
        from scar.analysis.source_observed_resumptions import build
        from scar.analysis.source_resumption_view import verify_resumption_graph
        metadata=sorted(Path(trace).resolve().glob('resumption-meta.*.json'))
        for path in metadata:
            target=Path(resumptions_out)
            if len(metadata)>1:target=target.with_name(target.name+'-'+path.name.split('.')[1])
            phase('resumptions-'+path.name,build,out,path,target,index=index)
            phase('resumption-graph-check-'+path.name,verify_resumption_graph,target,target/'graph-check.json',index=index)
            resumptions.append(_receipt(target/'result.json'))
    index.check()
    _durable_bytes(Path(out)/'runtime-channels.json',_json(dict(
        schema='scar.runtime-source-channel-publications',resumptions=resumptions,
        code_source_index_reused=True,seconds_by_channel=timings,target_executed=False,first_stage_complete=False)),replace=False)
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('parent','trace','project-root','out'):parser.add_argument('--'+name,required=True)
    for name in ('boundaries-out','activations-out','graph-check-out','resource-scopes-out','resumptions-out'):
        parser.add_argument('--'+name)
    args=parser.parse_args();r=publish(**vars(args));print(json.dumps(r['counts']),flush=True)


if __name__=='__main__':main()
