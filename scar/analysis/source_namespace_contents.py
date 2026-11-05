"""Conditional dictionary definitions reaching original namespace read ports."""
from dataclasses import dataclass

from scar.analysis.source_namespace_interfaces import CallerReferencePaths, NamespacePlanView
from scar.ir.program import normal_links as F, normal_targets as T, source_namespaces as N
from scar.ir.program.source_exec_roots import ExecNamespaceKind
from scar.ir.literals import PythonLiteral


@dataclass(frozen=True, slots=True)
class _Definition:
    mapping: int
    assigned: int
    key: str
    key_source: T.GlobalPort | PythonLiteral
    key_literal_source: T.GlobalPort | None
    key_path: tuple[N.NamespaceReferenceHop, ...]
    world: T.GlobalPort
    result_world: T.GlobalPort
    table: F.FactTable
    row: int
    member: int | None


def _keys(paths, key):
    if type(key) is PythonLiteral:
        value = key.to_python()
        if type(value) is str:
            yield value,key,None,()
        return
    for row in paths.unit.constants:
        value = row.literal.to_python()
        if type(value) is not str:
            continue
        path = paths.path(row.value, paths.ports[key])
        if path is not None:
            yield value,paths.ports[key],paths.ports[row.value],path


def content_definitions(paths, targets, interface_index):
    """Select source mappings first; recover each needed F4 plan once."""
    unit = paths.unit
    relevant = lambda point:any(paths.path(point,target) is not None for target in targets)
    selected = [(i,row) for i,row in enumerate(unit.containers)
        if row.kind is F.ContainerKind.MAPPING and row.pairs and relevant(row.value)]
    keys = {paths.ports[row.value].port.template for _,row in selected}
    if keys:
        interface_index._prefetch(unit, keys)
    for index,row in selected:
        point = paths.ports[row.value]
        plan = interface_index._plan(unit,point.port.template)[0]
        view = NamespacePlanView(unit.unit,plan)
        step = view.steps[point.port.owner]
        before,after = view.worlds(step)
        for member,(key,value) in enumerate(row.pairs):
            for text,key_source,literal,path in _keys(paths,key):
                yield _Definition(row.value,value,text,key_source,literal,path,before,after,
                    F.FactTable.CONTAINERS,index,member)
    for index,row in enumerate(unit.items):
        if not row.write or not relevant(row.receiver):
            continue
        for text,key_source,literal,path in _keys(paths,row.key):
            yield _Definition(row.receiver,row.value,text,key_source,literal,path,
                paths.ports[row.world],paths.ports[row.result_world],F.FactTable.ITEMS,index,None)


def link_namespace_contents(connection, accesses, bindings, reference_bindings, caller, interface_index):
    """May-reaching content is guarded by worlds, lookup misses and callable."""
    paths = CallerReferencePaths(caller)
    references = {r.reference:r.actual for r in reference_bindings}
    targets = set()
    for binding in bindings:
        actual = references.get(binding.actual,binding.actual)
        if type(actual) is T.GlobalPort and actual.unit==caller.unit:
            targets.add(actual)
    definitions = tuple(content_definitions(paths,targets,interface_index))
    by_interface = {}
    for binding in bindings:
        by_interface.setdefault(binding.interface,[]).append(binding)
    links = []
    for access in accesses:
        for lookup in access.lookup:
            for binding in by_interface.get(lookup.interface,()):
                actual = references.get(binding.actual,binding.actual)
                if type(actual) is not T.GlobalPort or actual.unit!=caller.unit:
                    continue
                for definition in definitions:
                    if definition.key!=access.key:
                        continue
                    path = paths.path(definition.mapping,actual)
                    if path is None:
                        continue
                    conditions = (*binding.conditions,
                        'SOURCE_MAPPING_REFERENCE_PATH_SELECTED_AT_EXEC_CALL',
                        'SOURCE_KEY_REFERENCE_PATH_HAS_RECORDED_STRING_VALUE',
                        'DEFINITION_REACHES_READ_WORLD_WITHOUT_INTERVENING_REPLACEMENT',
                        'ALL_EARLIER_LOOKUP_STEPS_REPORT_MISSING',
                        'SELECTED_MAPPING_PROTOCOL_RETURNS_RECORDED_CONTENT')
                    links.append(N.NamespaceContentLink(connection.id,lookup.interface,lookup.ordinal,
                        access.value,access.world_in,paths.ports[definition.mapping],paths.ports[definition.assigned],
                        definition.world,definition.result_world,definition.row,definition.table,definition.member,
                        definition.key,definition.key_source,definition.key_literal_source,definition.key_path,
                        path,conditions,binding.capturing_function,
                        binding.actual if binding.capturing_function is not None else None))
    return tuple(links)
