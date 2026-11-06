"""Connect selected function captures to frame-global references and reads.

Root namespace tokens denote formal inputs, not module instances or concrete
dictionary allocations. Source name channels remain conservative content
constraints, separately qualified by the root/creation conditions below.
"""
from collections import defaultdict
from hashlib import sha256

from scar.analysis.source_frame_captures import FrameCaptureIndex
from scar.analysis.source_root_namespace_views import RootNamespaceViews
from scar.analysis.source_template_links import _json
from scar.ir.program import normal_links as F,normal_graph as G,normal_targets as T
from scar.ir.program import source_frame_bindings as B,source_productions as P
from scar.ir.record_codec import encode


class FrameGlobalsFlow:
    def __init__(self, solver):
        self.s=solver
        self.index=FrameCaptureIndex(solver.store,solver.namespace_graph.exec_graph,jobs=solver.analysis_jobs)
        self.activations=defaultdict(set); self.sources=defaultdict(lambda:defaultdict(set))
        self.exec_requests=defaultdict(dict); self.read_requests=defaultdict(dict)
        self.requested=set(); self.materials={}
        self.roots={}; self.bindings={}; self.reads={}; self.obligations={}
        self.entry_contracts={}
        self.root_content_watchers=defaultdict(set)
        self.views=RootNamespaceViews(solver,self)

    def point(self, endpoint):
        return self.s.original_point(endpoint)

    def _formal(self, root, index):
        return T.GlobalPort(root.owner.unit,G.Port(root.template,root.region,G.PortKind.PARAMETER,index))

    def configure_entry(self, contract):
        self.entry_contracts[contract.source.unit]=contract
        self._material(contract.source.unit)

    def _material(self, unit):
        if unit in self.materials:return self.materials[unit]
        material=self.index.load(unit); self.materials[unit]=material
        root=material.root; globals=self._formal(root,0); locals=self._formal(root,1)
        if unit not in self.s.store.original_source_units:
            contract=self.entry_contracts.get(unit)
            conditions=(contract.conditions if contract is not None else
                ('STANDARD_SOURCE_MODULE_INITIALIZATION','SOURCE_ROOT_GLOBALS_AND_LOCALS_USE_THE_SELECTED_NAMESPACE'))
            row=B.RootNamespaceBinding(root,globals,locals,'DECLARED_SCRIPT_ENTRY' if contract else 'SOURCE_MODULE_ROOT',
                (*conditions,'SOURCE_NAME_CHANNELS_ARE_MAY_CONTENT_NOT_MODULE_OBJECT_IDENTITY'),
                None if contract is None else sha256(_json(encode(contract,record_tags=P.PRODUCTION_RECORD_TAGS))).hexdigest())
            self.roots[unit]=row
            self.views.admit(row,contract)
            token=('source_root_namespace',unit,self.point(globals))
            self.s.add(self.point(globals),token); self.s.add(self.point(locals),token)
        for reference in material.references:
            if reference.globals_scope==root.source_scope:
                self.s.edge(self.point(globals),self.point(reference.result))
        self.sources[root.owner][globals].add(None)
        return material

    def activate_function(self, fid, callee):
        unit,function=self.s.functions[fid]
        owner=function.body_scope.owner
        self.activations[owner].add((fid,callee))
        if owner in self.requested:
            self._source(owner,fid,callee)

    def _source(self, owner, fid, callee):
        unit,function=self.s.functions[fid]
        material=self._material(unit.unit); callable=self.s.gp(fid)
        for capture in material.captures:
            if capture.function!=callable or capture.body.owner!=owner:continue
            witness=next(w for w in material.witnesses if w.template==capture.site.port.template
                and w.step==capture.site.port.owner)
            frame=B.FunctionFrameSource(callable,self.s.gp(callee),capture.body,
                self.s.gp(self.s.offsets[unit.unit]+function.formals[0]),capture,witness,
                ('ADMITTED_SOURCE_FUNCTION_CALL','CURRENT_CALLABLE_IS_SELECTED_FUNCTION_CREATION',
                 'GLOBALS_REFERENCE_RETAINED_AT_CREATION_NOT_CONTENT_SNAPSHOT'))
            self.sources[owner][capture.globals].add(frame)
            self._apply(owner,capture.globals,frame)

    def request(self, owner):
        self.requested.add(owner)
        unit=self.s.store.load(owner.unit)
        if owner==unit.root_scope.owner:
            self._material(owner.unit)
        for fid,callee in tuple(self.activations.get(owner,())):
            self._source(owner,fid,callee)
        return self.sources.get(owner,{})

    def connect_exec(self, connection, target):
        owner=connection.owner
        self.exec_requests[owner][connection.id]=(connection,target)
        self.request(owner)
        for source,frames in tuple(self.sources.get(owner,{}).items()):
            for frame in tuple(frames):self._apply(owner,source,frame)
        if not self.sources.get(owner):
            self.obligations[owner,connection.site.result]=B.FrameGlobalsObligation(owner,connection.site.result,
                'CALLER_FRAME_GLOBALS_CAPTURE_OR_ROOT_ARGUMENT_NOT_RESOLVED')
            return False
        return True

    def read_globals(self, owner, result, world):
        self.read_requests[owner][result]=world
        self.request(owner)
        for source,frames in tuple(self.sources.get(owner,{}).items()):
            for frame in tuple(frames):self._apply(owner,source,frame)
        if not self.sources.get(owner):
            self.obligations[owner,result]=B.FrameGlobalsObligation(owner,result,
                'GLOBALS_CALL_FRAME_CAPTURE_OR_ROOT_ARGUMENT_NOT_RESOLVED')
            return False
        return True

    def _apply(self, owner, source, frame):
        conditions=('SELECTED_FRAME_GLOBALS_REFERENCE','CURRENT_FRAME_USES_THIS_ROOT_OR_FUNCTION_CREATION',
            'REFERENCE_IDENTITY_NOT_CONTENT_OR_STORAGE_IDENTITY')
        for connection,target in tuple(self.exec_requests.get(owner,{}).values()):
            key=connection.id,source,frame
            if key not in self.bindings:
                self.s.edge(self.point(source),target)
                self.bindings[key]=B.FrameGlobalsBinding(connection.id,owner,connection.globals.value,
                    source,self.s.gp(target),connection.site.world,frame,conditions)
            self.obligations.pop((owner,connection.site.result),None)
        for result,world in tuple(self.read_requests.get(owner,{}).items()):
            key=owner,result,source,frame
            if key not in self.reads:
                self.s.edge(self.point(source),self.point(result))
                self.reads[key]=B.FrameGlobalsRead(owner,result,source,world,frame,conditions)
            self.obligations.pop((owner,result),None)

    def access_root(self, token, key, target, write):
        self.views.access(token,key,target,write)

    def watch_root_content(self, token, key, callback):
        channel=(token[1],F.NamespaceKind.MODULE.value,0,key)
        subscription=token,callback
        if subscription in self.root_content_watchers[token[1],key]:return
        self.root_content_watchers[token[1],key].add(subscription)
        for source in tuple(self.s.containers.namespace_sources.get(channel,())):
            callback(token,('str',key),source)

    def name_write(self, unit, key, source):
        self.views.name_write(unit,key,source)
        for token,callback in tuple(self.root_content_watchers.get((unit,key),())):
            callback(token,('str',key),source)

    def name_read(self, unit, key, target):
        self.views.name_read(unit,key,target)

    def validate_parents(self):
        return self.index.validate_parents()

    def close(self):
        self.index.close()
