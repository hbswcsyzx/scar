"""Field versions, missing semantics and reference phases remain distinct."""
from importlib.metadata import distribution,PackageNotFoundError
from types import SimpleNamespace

import pytest

from scar.ir.literals import PythonLiteral
from scar.ir.program.configuration_composition import ConfigurationStep,ConfigurationStepKind
from scar.ir.program.configuration_overrides import ConfigurationOverride,OverrideAction,OverrideExpression,OverrideExpressionKind
from scar.ir.program.normal_links import CodeScopeRef,CodeScopeWitness
from scar.ir.program.source_frame_bindings import StaticInputPort
from scar.ir.program.source_productions import ProductionRegionID,ProductionPurpose
from scar.ir.program.source_template_links import SourceTemplateKey
from scar.ir.program.configuration_values import ConfigurationValueKind as K


def _query(tmp_path,texts,writes=(),*,open_prefix=False):
    try:source=distribution('omegaconf').locate_file('omegaconf')
    except PackageNotFoundError:pytest.skip('optional installed interpolation grammar is absent')
    from scar.analysis.source_data_materials import parse_yaml_material
    from scar.analysis.source_configuration_values import compile_configuration_expressions
    from scar.analysis.source_configuration_value_query import ConfigurationValueQuery
    from scar.analysis.source_interpolation_syntax import InterpolationSyntax
    steps=[ConfigurationStep(0,ConfigurationStepKind.EMPTY,None,None,None,None,None,(),(),('FIXTURE',))]
    if open_prefix:steps.append(ConfigurationStep(1,ConfigurationStepKind.OPEN_PROVIDER,0,None,None,None,None,(),(),('FIXTURE',)))
    materials={}
    for index,text in enumerate(texts):
        path=tmp_path/(str(index)+'.yaml');path.write_text(text);material,_=parse_yaml_material(path)
        key=str(index);materials[key]=material;ordinal=len(steps)
        steps.append(ConfigurationStep(ordinal,ConfigurationStepKind.MERGE_MATERIAL,ordinal-1,key,None,key,
            material.root,(),('defaults',),('FIXTURE',)))
    witness=CodeScopeWitness(CodeScopeRef('fixture',0),SourceTemplateKey(0,ProductionPurpose.ROOT),ProductionRegionID('fixture:root'),0)
    expressions=[];rows=[]
    for ordinal,(action,key,value) in enumerate(writes):
        token=key+'='+str(value);input_index=ordinal+1;ref=None
        if action is not OverrideAction.DELETE:
            ref=len(expressions)
            expressions.append(OverrideExpression(ref,input_index,len(key)+1,len(token),OverrideExpressionKind.SCALAR,
                PythonLiteral.from_python(value,exact=True),None,(),(),None,()))
        rows.append(ConfigurationOverride(ordinal,StaticInputPort(witness,'0'*64,('inputs','argv',input_index)),token,
            action,key,None,tuple(key.split('.')),ref,ordinal,ordinal+1,('FIXTURE',)))
    base=SimpleNamespace(steps=tuple(steps),root_version=len(steps)-1)
    overlay=SimpleNamespace(composition_version=len(steps)-1,overrides=tuple(rows),expressions=tuple(expressions))
    operations,roots,selected=compile_configuration_expressions(base,overlay,'1'*64)
    query=ConfigurationValueQuery(operations,materials,overlay,'1'*64,InterpolationSyntax(source),('FIXTURE',))
    return query,roots,selected


def test_plain_field_versions_use_overridden_root_and_keep_cycles_and_markers(tmp_path):
    first=('base: 2\nselected: ${base}\nrelative: {number: 3, ref: "${.number}"}\n'
        'preserved: 8\nitems: [1, 2]\nmissing: ???\nnone: null\nnested: {a: 1}\n'
        "escaped: '\\${base}'\ntemplate: n=${base}\ncycle_a: ${cycle_b}\ncycle_b: ${cycle_a}\n"
        "key: nested.a\n'nested.a': 22\ndynamic: ${${key}}\nnegative: ${items[-1]}\n"
        'resolver: ${custom:}\nopen_template: ${custom:}-${base}\n')
    second='base: 4\npreserved: ???\nitems: [3]\nnested: {b: 2}\nchain: ${selected}\n'
    query,roots,selected=_query(tmp_path,(first,second),(
        (OverrideAction.CHANGE,'base',7),(OverrideAction.CHANGE,'preserved','???'),
        (OverrideAction.DELETE,'none',None)))
    def read(path,root=selected):return query.projections[query.project(root,tuple(path.split('.')))]
    before=next(r.expression for r in roots if r.stage=='OVERRIDE' and r.version==0)
    assert read('preserved',before).literal.to_python()==8  # merge missing keeps the old value
    assert read('preserved').kind is K.MISSING             # assignment missing replaces it
    assert read('none',before).literal.to_python() is None and read('none').kind is K.ABSENT
    assert read('selected').literal.to_python()==7 and read('selected').value_path==('base',)
    assert read('relative.ref').literal.to_python()==3
    assert read('template').literal.to_python()=='n=7'
    escaped=read('escaped');assert escaped.literal.to_python()=='${base}' and not escaped.dependencies
    assert read('items.0').literal.to_python()==3 and read('items.1').kind is K.ABSENT
    assert read('items.-1').kind is K.ABSENT and read('negative').kind is K.OPEN
    assert read('nested.a').literal.to_python()==1 and read('nested.b').literal.to_python()==2
    assert read('nested').members_complete is True and read('items').members_complete is True
    assert read('dynamic').literal.to_python()==1 and read('nested.a').literal.to_python()==1
    assert read('resolver.x').kind is K.OPEN and read('resolver.x').value_path is None
    template=read('open_template');assert template.kind is K.OPEN
    assert any(query.projections[d].path==('base',) for d in template.dependencies)
    assert read('missing').kind is K.MISSING and read('cycle_a').kind is K.CYCLE
    chain=read('chain');assert chain.value_path==('base',)
    assert next(i for i in query.interpolations if i.projection==chain.ordinal).target_path==('selected',)
    assert all(p is not None for p in query.projections)


def test_open_provider_and_intermediate_alias_reads_do_not_become_false_constants(tmp_path):
    body='known: 4\nmissing: ???\ntarget: {n: 1}\nalias: ${target}\n'
    query,roots,selected=_query(tmp_path,(body,),((OverrideAction.CHANGE,'alias.n',2),),open_prefix=True)
    before=next(r.expression for r in roots if r.stage=='OVERRIDE' and r.version==0)
    missing=query.projections[query.project(before,('missing',))]
    assert missing.kind is K.OPEN  # an earlier provider could have supplied it
    assert query.projections[query.project(before,())].members_complete is False
    after=query.projections[query.project(selected,('known',))]
    assert after.kind is K.OPEN   # do not pretend an unsupported alias write preserved other facts
    demand=next(d for d in query.read_demands if d.phase=='UPDATE_INTERMEDIATE')
    assert demand.snapshot==before and demand.path==('alias',)
    assert query.projections[demand.projection].root==before
    assert 'INTERMEDIATE_UPDATE_ALIAS_EFFECT_PENDING' in {o.code for o in query.obligations}
