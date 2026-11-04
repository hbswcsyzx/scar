"""Supplement source capture paths with accepted FREE and implicit requirements.

Old F3 relay IDs remain unchanged. Missing paths use a separate composite key
and shared parent edges. Cell ownership is a logical binding requirement,
not a physical co_freevars/co_cellvars ordering or allocation observation.
"""
from collections import defaultdict
from dataclasses import dataclass,replace
from scar.ir.program import source_productions as P


def _require(condition,path,detail):
    if not condition:
        from scar.analysis.source_productions import ProductionError
        raise ProductionError('CAPTURE_TRANSPORT',str(path),detail)


@dataclass(frozen=True,slots=True)
class CapturePathHop:
    scope: int
    binding: int
    parent: P.CaptureReference | None


class CaptureInterfaceIndex:
    def __init__(self,source):
        self.source=source;self.data=source.frontend.bindings;self.scopes=source.context.material.scopes
        self.captures=defaultdict(list);self.cells=defaultdict(set);self.transports={};self._by_pair={}
        active=set()
        for demand in self.data.captures:
            if demand.activation in ('TEMPLATE_ONLY','TYPE_GRAMMAR'):continue
            hop=demand.hop
            while hop is not None and hop not in active:
                active.add(hop);hop=self.data.relays[hop].parent
        for index,hop in enumerate(self.data.relays):
            if index in active:
                self._by_pair[hop.scope,hop.binding]=index;self.captures[hop.scope].append(index)
        for index,binding in enumerate(self.data.bindings):
            if binding.cell_required:self.cells[binding.owner].add(index)
        native=source.frontend.symbols;topology=source.frontend.topology
        constants={c.name:c.value for c in source.frontend.native.profile.constants}
        _require('FREE' in constants,'compiler profile','original FREE symbol constant is required')
        free=defaultdict(list)
        for index,slot in enumerate(native.slots):
            block=topology.blocks[slot.block]
            if block.source_scope is None or block.projection in ('FUTURE_DETACHED','DETACHED_DESCENDANT'):continue
            if slot.final_fact is not None and native.facts[slot.final_fact].scope_code==constants['FREE']:
                free[block.source_scope,source.frontend.compiler.name(slot.name)].append(index)
        self.native_requirements=[]
        for resolution,row in enumerate(self.data.resolutions):
            witnesses=free.get((row.scope,source.frontend.namespace.name(row.name)),())
            if row.classification=='FREE' and row.binding is not None and witnesses:
                self.native_requirements.append((resolution,tuple(witnesses)))
                self._ensure(row.scope,row.binding,tuple(witnesses))
        # Some implicit reads are recorded at their creator (e.g. conditional
        # annotation registry), while the actual consumer is the request scope.
        # Use its original anchor/read target; compiler witnesses supplement
        # rather than replace the implicit source dependency.
        for ordinal,row in enumerate(self.data.implicit):
            if row.binding is None:continue
            if row.analysis_visibility!='SYMBOL_VISIT' or row.activation in ('TEMPLATE_ONLY','TYPE_GRAMMAR'):continue
            state=source.context.context_at_slot(row.anchor).state
            if source.context.material.regions[state.region].eligibility!='ELIGIBLE':continue
            scope=state.environment
            witnesses=free.get((scope,source.frontend.namespace.name(row.name)),())
            if self.data.bindings[row.binding].owner!=scope:
                self._ensure(scope,row.binding,tuple(witnesses),(ordinal,))

    def _ensure(self,scope,binding,witnesses,implicit=()):
        owner=self.data.bindings[binding].owner;missing=[];current=scope;seen=set()
        while current!=owner and (current,binding) not in self._by_pair:
            _require(current is not None and current not in seen,scope,'capture must reach its original owner through source scope parents')
            seen.add(current);missing.append(current);current=self.scopes[current].parent
        parent=None if current==owner else self._by_pair[current,binding]
        for current in reversed(missing):
            reference=P.DerivedCaptureRef(current,binding)
            self.transports[reference]=P.CaptureTransport(reference,parent,witnesses,implicit)
            self._by_pair[current,binding]=reference;self.captures[current].append(reference);parent=reference
        # Multiple consumers may share a carrier; keep the union of original
        # compiler witnesses without cloning the shared path.
        current=self._by_pair.get((scope,binding))
        while type(current) is P.DerivedCaptureRef:
            row=self.transports[current]
            self.transports[current]=replace(row,compiler_slots=tuple(sorted(set(row.compiler_slots)|set(witnesses))),
                implicit_requirements=tuple(sorted(set(row.implicit_requirements)|set(implicit))))
            current=row.parent
        self.cells[owner].add(binding)

    def relay(self,reference):
        if type(reference) is int:
            _require(0<=reference<len(self.data.relays),reference,'original relay is outside its F3 table')
            return self.data.relays[reference]
        _require(type(reference) is P.DerivedCaptureRef and reference in self.transports,reference,
            'derived relay must have original compiler/source evidence')
        # Same logical fields as the old ForwardHop; its reference domain stays separate.
        row=self.transports[reference]
        return CapturePathHop(reference.scope,reference.binding,row.parent)

    def owned_cells(self,scope):return tuple(sorted(self.cells[scope]))

    def export_references(self,references):
        selected=set();pending=list(references)
        while pending:
            reference=pending.pop()
            if type(reference) is int:continue
            _require(reference in self.transports,reference,'unknown derived capture reference')
            if reference in selected:continue
            selected.add(reference);parent=self.transports[reference].parent
            if parent is not None:pending.append(parent)
        return tuple(self.transports[r] for r in sorted(selected,key=lambda r:(r.scope,r.binding)))

    def export_steps(self,steps):
        return self.export_references(s.instruction.source.relay for s in steps if type(s.instruction) is P.ReferenceEnvironment
            and type(s.instruction.source) is P.ClosureEnvironment)
