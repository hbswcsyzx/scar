"""Namespace order, deletion and actual function globals survive projection."""
from scar.analysis.source_namespace_interfaces import extract_namespace_interfaces, CallerReferencePaths
from scar.ir.program import source_productions as P, source_bindings as B, source_declarations as D
from scar.ir.program.source_template_links import SourceTemplateKey
from scar.ir.record_codec import decode, encode
from tests.unit.test_source_construction_connections import source_facts
from tests.unit.test_source_expression_rules import _documents, _rules


def test_ordered_namespaces_delete_and_function_capture():
    text = 'name = 3\ndef read():\n    return name\ndel name\nresult = read()\n'
    documents = _documents(text)
    declarations = decode(D.SourceDeclarationsMaterial,documents[5])
    bindings = decode(B.SourceBindingsMaterial,documents[6])
    unit,index = source_facts(text,protocols=True)
    ports = CallerReferencePaths(unit).ports
    keys = {p.port.template for p in ports.values()}
    source = _rules(documents).source
    # Legacy primitive facts omit DELETE; enumerate those original templates
    # from syntax instead of inheriting that omission in the new projection.
    keys.update(SourceTemplateKey(i,P.ProductionPurpose.DELETE)
        for i,node in enumerate(documents[2]['nodes'])
        if node['constructor']=='Name' and source.roles.context(i)=='Del')
    rows = {k:[] for k in ('accesses','explicit','references','captures','obligations')}
    for key in sorted(keys,key=lambda k:(k.occurrence,k.purpose.value)):
        plan = index._plan(unit,key)[0]
        values = extract_namespace_interfaces(unit.unit,plan,bindings,declarations)
        for name,value in zip(rows,values):
            rows[name].extend(value)
    accesses = rows['accesses']
    root_read = next(a for a in accesses if a.key=='read' and a.action is P.BindingActionKind.READ)
    function_read = next(a for a in accesses if a.key=='name' and a.action is P.BindingActionKind.READ)
    assert [bindings.interfaces[s.interface.index].kind for s in root_read.lookup]==['ROOT_LOCALS','ROOT_GLOBALS','BUILTINS']
    assert [bindings.interfaces[s.interface.index].kind for s in function_read.lookup]==['ENV_GLOBALS','BUILTINS']
    deleted = next(a for a in accesses if a.action is P.BindingActionKind.DELETE)
    assert deleted.key=='name' and deleted.target is not None and deleted.value is None
    assert deleted.world_in!=deleted.world_out
    assert all(a.world_in!=a.world_out for a in accesses)
    assert len(rows['captures'])==len(rows['references'])==1
    capture,reference = rows['captures'][0],rows['references'][0]
    assert capture.globals==reference.result
    assert capture.function!=capture.globals and capture.body.source_scope==function_read.owner.source_scope
    assert not rows['obligations']
    for group in rows.values():
        for row in group:
            assert decode(type(row),encode(row,record_tags=P.PRODUCTION_RECORD_TAGS),record_tags=P.PRODUCTION_RECORD_TAGS)==row
