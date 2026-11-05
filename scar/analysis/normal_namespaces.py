"""Expose inferred namespace origins and open member-binding requirements."""
from scar.ir.program import normal_links as F, normal_namespaces as N


def namespace_lookups(solver):
    """Project existing facts, not another analysis or invented call target."""
    emitted=set()
    for unit in solver.units:
        offset=solver.offsets[unit.unit]
        for access in unit.attributes:
            if access.write:continue
            receiver=offset+access.receiver;result=offset+access.value
            for value in sorted(solver.values[receiver],key=repr):
                if value[0] not in ('module','external'):continue
                namespace=value[1];identity=(receiver,result,namespace,access.name,value[0])
                if identity in emitted:continue
                emitted.add(identity)
                source_units=tuple(solver.module_units.get(namespace,())) if value[0]=='module' else ()
                possible=set()
                for source in source_units:
                    possible.update(solver.ns_values[(source,F.NamespaceKind.MODULE.value,0,access.name)])
                yield N.NamespaceLookup(solver.gp(receiver),solver.gp(result),namespace,access.name,
                    N.NamespaceKind.MODULE if value[0]=='module' else N.NamespaceKind.EXTERNAL_SYMBOL,
                    source_units,len(possible),namespace+'.'+access.name in solver.imported_modules)
