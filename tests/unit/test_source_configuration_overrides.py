"""Library grammar is reused without treating CLI expressions as YAML."""
from importlib.metadata import distribution,PackageNotFoundError
from types import SimpleNamespace

import pytest


def test_override_input_types_and_ordered_writes_keep_grammar_and_provenance():
    try:root=distribution('hydra-core').locate_file('hydra')
    except PackageNotFoundError:pytest.skip('optional installed grammar tools are absent')
    from scar.analysis.source_configuration_overrides import _arguments,_protocol,lower_overrides
    from scar.analysis.source_override_syntax import OverrideSyntax
    from scar.ir.program.configuration_overrides import OverrideAction,OverrideExpressionKind
    from scar.ir.program.normal_links import CodeScopeRef,CodeScopeWitness
    from scar.ir.program.source_template_links import SourceTemplateKey
    from scar.ir.program.source_productions import ProductionRegionID,ProductionPurpose
    _,function=_protocol(root);syntax=OverrideSyntax(root)
    argv=('example.py','--config-name=example','n=1e3','flag=on','flag=False','empty=',
        'none=NULL','missing=???','ref=${n}',r'quoted="a\n"',r'escaped=a\,b',
        'items=[1,true]','mapping={k:2}','+extra=3','++extra=4','~extra',
        'choice=a,b','value=func(1,key=2)')
    tokens=_arguments(function,argv)
    witness=CodeScopeWitness(CodeScopeRef('fixture',0),SourceTemplateKey(0,ProductionPurpose.ROOT),ProductionRegionID('fixture:root'),0)
    contract=SimpleNamespace(root=witness)
    rows,expressions,obligations=lower_overrides(tokens,contract,'0'*64,syntax,('INITIAL_VERSION',))
    assert [r.source.path for r in rows]==[('inputs','argv',i) for i in range(2,len(argv))]
    assert [(r.input_version,r.output_version) for r in rows]==[(i,i+1) for i in range(len(rows))]
    scalar=[expressions[r.value].literal.to_python() for r in rows[:9]]
    assert scalar==[1000.0,'on',False,'',None,'???','${n}',r'a\n','a,b']
    assert [expressions[r.value].kind for r in rows[9:11]]==[
        OverrideExpressionKind.SEQUENCE,OverrideExpressionKind.MAPPING]
    assert [r.action for r in rows[11:14]]==[OverrideAction.ADD,OverrideAction.FORCE_ADD,OverrideAction.DELETE]
    assert rows[13].value is None
    call=expressions[rows[-1].value]
    assert call.kind is OverrideExpressionKind.CALL and call.function=='func'
    assert call.argument_names==(None,'key')
    assert {o.code for o in obligations}=={'UNEVALUATED_OVERRIDE_FUNCTION','SWEEP_SELECTION_PENDING'}
