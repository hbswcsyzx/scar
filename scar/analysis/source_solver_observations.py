"""Bounded diagnostic views of an existing solver, without admitting work.

Reprs below describe analyzer transfer tokens, not logical values, runtime
objects, tensor contents or a proof of an execution. No solver query methods,
defaultdict subscriptions, source loaders or propagation callbacks are used.
"""
from collections import Counter, defaultdict
from hashlib import sha256

from scar.ir.program import normal_graph as G, source_productions as P
from scar.ir.record_codec import decode, encode


_SAMPLE = 4
_TEXT = 768


def _repr(value):
    text = repr(value)
    return dict(text=text[:_TEXT],truncated=len(text)>_TEXT,characters=len(text))


def snapshot_ports(solver, requests):
    """Observe selected original ``(unit, local)`` ports at this work frontier.

    Counts cover complete selected value sets; each kind and subscription list
    has at most four displayed entries. The queues are each traversed once, with
    no copy of their complete contents. Call this while propagation is stopped.
    An empty selected pending count never grants whole-program fixed point.
    """
    requests = tuple(dict.fromkeys(requests))
    if len(requests)>64:
        raise ValueError('at most 64 original source ports may be observed')
    store = getattr(solver,'store',None)
    units = {unit.unit:unit for unit in solver.units}
    references = {}

    def ref(point):
        if point in references:return references[point]
        result = dict(point=point if type(point) is int else None,gp=None)
        if type(point) is not int:
            result.update(kind='INTERNAL_LOOKUP_KEY',diagnostic=_repr(point))
        elif point<0:
            endpoint = getattr(solver,'interface_ports',{}).get(point)
            result.update(kind='DECLARED_INTERFACE_POINT',endpoint=None if endpoint is None else
                encode(endpoint,record_tags=P.PRODUCTION_RECORD_TAGS),unknown=endpoint is None)
        else:
            if store is not None:
                identity,local = store.locate(point)
                unit = store.loaded.get(identity)
            else:
                identity = solver.owner[point];local = point-solver.offsets[identity]
                unit = units.get(identity)
            result.update(kind='ORIGINAL_SOURCE_POINT',unit=identity,local=local)
            if unit is None:
                result['unknown']='UNIT_NOT_LOADED_NO_SOURCE_READ_PERFORMED'
            else:
                raw = unit.ports[local]
                wire = encode(raw,record_tags=P.PRODUCTION_RECORD_TAGS)
                result['gp']=dict(unit=identity,port=wire)
        references[point]=result
        return result

    def values(items):
        counts=Counter();samples=defaultdict(list)
        for value in items:
            kind=value[0] if type(value) is tuple and value and type(value[0]) is str else 'UNRECOGNIZED_TOKEN'
            counts[kind]+=1
            if len(samples[kind])>=_SAMPLE:continue
            row=dict(repr=_repr(value))
            positions={'function':(1,),'class':(1,),'instance':(1,2),'bound':(1,2),
                'classbound':(1,2,3),'staticmethod':(1,),'classmethod':(1,),'container':(1,)}.get(kind,())
            row['point_references']=[dict(token_ordinal=i,reference=ref(value[i]))
                for i in positions if len(value)>i and type(value[i]) is int]
            samples[kind].append(row)
        return dict(count=sum(counts.values()),by_kind={kind:dict(count=count,samples=samples[kind],
            truncated=count>len(samples[kind])) for kind,count in sorted(counts.items())})

    def points(items):
        total=0;sample=[]
        for point in items:
            total+=1
            if len(sample)<_SAMPLE:sample.append(ref(point))
        return dict(count=total,samples=sample,truncated=total>len(sample))

    descriptors=getattr(solver,'descriptors',None)
    selected={};namespace_rows={}
    for request in requests:
        if (type(request) is not tuple or len(request)!=2 or type(request[0]) is not str
                or type(request[1]) is not int or request[1]<0):
            raise ValueError('observation needs an exact source unit and nonnegative local ordinal')
        identity,local=request
        if identity not in solver.offsets:raise ValueError('observed source unit is outside the solver catalog')
        size=(store.rows[identity]['counts']['ports'] if store is not None else len(units[identity].ports))
        if local>=size:raise ValueError('observed ordinal is outside its original source port table')
        point=solver.offsets[identity]+local;endpoint=ref(point)
        if endpoint['gp'] is not None:
            # Decode only the explicitly requested ports, never every token GP.
            decode(G.Port,endpoint['gp']['port'],record_tags=P.PRODUCTION_RECORD_TAGS)
        accesses=() if descriptors is None else descriptors.accesses.get(point,())
        gets=solver.gets.get(point,())
        members={access.member for access in accesses}
        members.update(name for name,_ in gets)
        access_rows=[];read_rows=[]
        for access in accesses[:_SAMPLE]:
            access_rows.append(dict(key=_repr(access.key),action=access.action.value,member=access.member,
                receiver=ref(access.receiver),result=None if access.result is None else ref(access.result),
                assigned=None if access.assigned is None else ref(access.assigned),world=ref(access.world),
                result_world=ref(access.result_world)))
        if descriptors is not None:
            pairs={(a.member,a.result) for a in accesses if a.result is not None}
            pairs.update(gets)
            for member,target in list(pairs)[:_SAMPLE]:
                registered=descriptors.reads.get((point,member,target),())
                read_rows.append(dict(member=member,target=ref(target),count=len(registered),
                    accesses=[_repr(a.key) for a in registered[:_SAMPLE]],truncated=len(registered)>_SAMPLE))
        call_rows=[];watch=solver.call_watch.get(point,())
        for index in watch[:_SAMPLE]:
            unit,call=solver.call_rows[index];offset=solver.offsets[unit.unit]
            call_rows.append(dict(index=index,unit=unit.unit,callee=ref(offset+call.callee),
                result=ref(offset+call.result),world=ref(offset+call.world),result_world=ref(offset+call.result_world)))
        tokens=solver.values.get(point,())
        classes={value[1] for value in tokens if type(value) is tuple and len(value)>1
            and value[0] in ('class','instance')}
        class_rows=[]
        for cls in list(classes)[:_SAMPLE]:
            row=dict(source_class=ref(cls));declaration=solver.classes.get(cls)
            if declaration is None:
                row['unknown']='SOURCE_CLASS_METADATA_NOT_AVAILABLE'
            else:
                unit,descriptor=declaration
                row.update(namespace_unit=unit.unit,namespace_class_scope=descriptor.scope,members=[])
                for member in sorted(members)[:_SAMPLE]:
                    key=(unit.unit,'CLASS',descriptor.scope,member)
                    if key not in namespace_rows:
                        namespace_rows[key]=dict(unit=unit.unit,scope=descriptor.scope,member=member,
                            values=values(solver.ns_values.get(key,())),
                            readers=points(solver.reads.get(key,())),
                            member_watch=dict(count=len(solver.member_watch.get(key,())),
                                samples=[_repr(v) for v in list(solver.member_watch.get(key,()))[:_SAMPLE]],
                                truncated=len(solver.member_watch.get(key,()))>_SAMPLE))
                    row['members'].append(dict(namespace_key=list(key)))
            class_rows.append(row)
        selected[point]=dict(request=dict(unit=identity,local=local),source=endpoint,
            original_port_validated=endpoint['gp'] is not None,values=values(tokens),
            outgoing=points(solver.adj.get(point,())),
            descriptor_accesses=dict(count=len(accesses),samples=access_rows,truncated=len(accesses)>_SAMPLE),
            descriptor_read_subscriptions=read_rows,
            gets=dict(count=len(gets),samples=[dict(member=name,target=ref(target)) for name,target in list(gets)[:_SAMPLE]],
                truncated=len(gets)>_SAMPLE),
            call_watch=dict(count=len(watch),samples=call_rows,truncated=len(watch)>_SAMPLE),
            classes=dict(count=len(classes),samples=class_rows,truncated=len(classes)>_SAMPLE),
            subscription_scope='EXISTING_RECEIVER_INDEXES_ONLY_NO_GLOBAL_REVERSE_SCAN')

    pending=Counter();pending_kinds=defaultdict(Counter);namespace_pending=Counter();namespace_kinds=defaultdict(Counter)
    queue=getattr(solver,'queue',())
    for point,value in queue:
        if point in selected:
            pending[point]+=1;pending_kinds[point][value[0]]+=1
        for key in solver.writes.get(point,()):
            if key in namespace_rows:
                namespace_pending[key]+=1;namespace_kinds[key][value[0]]+=1
    other_pending=getattr(solver,'namespace_pending',())
    other_counts=Counter()
    for point,value in other_pending:
        if point in selected:other_counts[point]+=1
    for point,row in selected.items():
        row['pending']=dict(value_queue=pending[point],by_kind=dict(pending_kinds[point]),
            namespace_protocol_queue=other_counts[point],zero_does_not_imply_fixed_point=True)
    for key,row in namespace_rows.items():
        row['pending_source_write_events']=namespace_pending[key]
        row['pending_by_kind']=dict(namespace_kinds[key])
        row['pending_scope']='VALUE_QUEUE_EVENTS_WITH_EXISTING_WRITES_SUBSCRIPTION_TO_THIS_NAMESPACE'
    raw=None if store is None else store.raw
    return dict(schema='scar.source-solver-observations',schema_version=1,event_count=solver.events,
        frontier=len(queue),namespace_frontier=len(other_pending),
        pending_scopes=len(getattr(solver,'pending',())),unfixed=bool(queue or other_pending or getattr(solver,'pending',())),
        whole_program_fixed_point_claimed=False,source_catalog_sha256=None if raw is None else sha256(raw).hexdigest(),
        limits=dict(samples_per_kind_or_subscription=_SAMPLE,repr_characters=_TEXT),
        value_semantics='BOUNDED_ANALYZER_ABSTRACT_TOKEN_REPRS_NOT_LOGICAL_VALUES_OR_RUNTIME_OBJECT_CONTENTS',
        ports=list(selected.values()),class_namespaces=list(namespace_rows.values()),
        unknown_fields=('RUNTIME_DISPATCH_AND_OBJECT_CONTENTS_NOT_OBSERVED',
            'UNLOADED_SOURCE_PORT_BYTES_NOT_READ','UNSUBSCRIBED_MEMBERS_NOT_QUERIED',
            'NAMESPACE_PROTOCOL_QUEUE_HAS_POINT_EVENTS_NOT_DIRECT_CLASS_NAMESPACE_KEYS'),
        solver_mutated=False,source_units_loaded=False,propagation_performed=False,target_executed=False)
