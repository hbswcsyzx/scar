"""Late custom builtin-map writes retain actual source-callable dependencies."""
from types import SimpleNamespace

from scar.analysis.normal_targets import _Solver
from scar.analysis.source_relation_replay import SharedContainerFlow
from scar.analysis.source_namespace_builtins import BuiltinNamespaceFlow
from scar.analysis.source_namespace_interfaces import CallerReferencePaths,extract_namespace_interfaces
from scar.ir.program import source_productions as P,source_bindings as B,source_declarations as D,normal_graph as G
from scar.ir.program.source_namespaces import NamespaceInterfaceBinding
from scar.ir.program.normal_targets import GlobalPort
from scar.ir.record_codec import decode,encode
from tests.unit.test_source_construction_connections import source_facts
from tests.unit.test_source_expression_rules import _documents


def test_custom_builtin_mapping_arriving_after_read_subscription():
    text='def callback(value):\n    return value\ntable = {"len": callback}\nnamespace = {}\nanswer = len([7])\n'
    docs=_documents(text);unit,index=source_facts(text,protocols=True);solver=_Solver([unit])
    bindings=decode(B.SourceBindingsMaterial,docs[6]);declarations=decode(D.SourceDeclarationsMaterial,docs[5])
    paths=CallerReferencePaths(unit);accesses=[]
    for key in {p.port.template for p in paths.ports.values()}:
        accesses.extend(extract_namespace_interfaces(unit.unit,index._plan(unit,key)[0],bindings,declarations)[0])
    access=next(a for a in accesses if a.key=='len' and a.lookup)
    lookup=next(s for s in access.lookup if bindings.interfaces[s.interface.index].kind=='BUILTINS')
    assigned={n.namespace.name:n.value for n in unit.names if n.write and n.namespace.kind.value=='MODULE'}
    root=unit.root_scope
    world=solver.original_point(GlobalPort(unit.unit,G.Port(root.template,root.region,G.PortKind.PARAMETER,2)))
    flow=SimpleNamespace(s=solver,point=solver.original_point,captures=(),
        formal=lambda connection,i:assigned['namespace'] if i==0 else world)
    flow.builtins=helper=BuiltinNamespaceFlow(flow);solver.namespace_flow=flow
    solver.containers=SharedContainerFlow(solver,[unit]);solver.solve()
    connection=SimpleNamespace(id='controlled-root-entry',root=root)
    binding=NamespaceInterfaceBinding(connection.id,lookup.interface,bindings.interfaces[lookup.interface.index],
        'ROOT_FRAME_BUILTINS_SELECTED_AT_ENTRY',None,None,('CONTROLLED_SOURCE_FIXTURE',))
    helper.admit(connection,access,binding);solver.solve()
    assert not any(link.source_callable==solver.gp(unit.functions[0].value) for link in solver.links.values())
    namespace=next(v for v in solver.values[assigned['namespace']] if v[0]=='container')
    # A late write uses real retained table/value ports. The namespace hook
    # must subscribe to its contents rather than substituting builtins.len.
    solver.containers.write(namespace,('str','__builtins__'),assigned['table'])
    solver.solve()
    assert any(link.source_callable==solver.gp(unit.functions[0].value) for link in solver.links.values())
    assert helper.selections and helper.fallbacks
    assert all('STANDARD_BUILTIN_MAP_AND_BINDING_SELECTED' in row.conditions for row in helper.fallbacks)
    for row in (*helper.selections,*helper.fallbacks):
        assert decode(type(row),encode(row,record_tags=P.PRODUCTION_RECORD_TAGS),record_tags=P.PRODUCTION_RECORD_TAGS)==row
