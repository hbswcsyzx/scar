"""Join compiler-inserted CALLs to existing F4 protocol operations.

The full caller code was checked by the code provider. Source spans select
candidate recipes; compiler markers and the original protocol ABI then select
an operation. Ordinary Python argument binding is deliberately not involved.
"""
from collections import defaultdict
from dataclasses import dataclass
from types import CodeType
import dis

from scar.analysis.source_namespace_interfaces import NamespacePlanView
from scar.analysis.source_reference_slice import source_port
from scar.ir.program import normal_targets as T, source_productions as P
from scar.ir.program.normal_graph import SourceTemplateKey
from scar.ir.program.normal_links import CodeScopeWitness
from scar.ir.program.providers import ProviderFactReference
from scar.ir.program.structured import PythonProtocolKind as K


@dataclass(frozen=True, slots=True)
class ProtocolSite:
    kind: str
    definition: ProviderFactReference
    operation: T.GlobalPort
    arguments: tuple[T.GlobalPort, ...]
    result: T.GlobalPort
    world: T.GlobalPort
    result_world: T.GlobalPort
    body: T.Body
    owner: CodeScopeWitness
    rule: str


def protocol_index(index, caller):
    from scar.analysis.source_observed_calls import _span
    key = caller.unit, caller.scope.owner, caller.capture.code.key
    cache = index._protocol_static
    if key in cache: return cache[key]
    instructions = tuple(dis.get_instructions(caller.code, adaptive=False, show_caches=False))
    positions = defaultdict(list)
    for ordinal, instruction in enumerate(instructions):
        if instruction.opname in ('CALL', 'CALL_KW', 'CALL_FUNCTION_EX'):
            positions[tuple(instruction.positions)].append((ordinal, instruction))
    syntax = index._source_syntax(caller.unit)
    wanted = []
    for occurrence, node in enumerate(syntax.nodes):
        if node.constructor not in ('GeneratorExp', 'ClassDef'): continue
        span = _span(syntax, occurrence)
        if span in positions:
            purpose = P.ProductionPurpose.VALUE if node.constructor == 'GeneratorExp' else P.ProductionPurpose.STATEMENT
            wanted.append((SourceTemplateKey(occurrence, purpose), node.constructor, span))
    source = index.view.unit(caller.unit); facts = source.facts
    missing = tuple(t for t, _, _ in wanted if t not in index._contexts[caller.unit])
    for template, plan in source.material.plans(missing).items():
        index._plans[caller.unit][template] = plan
        index._contexts[caller.unit][template] = NamespacePlanView(caller.unit, plan)
    result = defaultdict(list)
    for template, constructor, span in wanted:
        context = index._contexts[caller.unit][template]
        for step in context.plan.steps:
            ins = step.instruction
            if constructor == 'GeneratorExp':
                if not (type(ins) is P.ApplyPythonProtocol and ins.protocol is K.CREATE_GENEXPR): continue
                # This ABI consists of five environment components, captured
                # cells and the initial iterator, followed by the world.
                if len(step.arguments) < 7: raise ValueError('generator creation lost its protocol arguments')
                env = step.arguments[:5]
                if not all(type(v) is P.ProductionResult and v.step == env[0].step and v.index == n
                        for n, v in enumerate(env)):
                    raise ValueError('generator creation changed its original function environment')
                producer = context.steps[env[0].step]
                if not (type(producer.instruction) is P.ApplyPythonProtocol
                        and producer.instruction.protocol is K.MAKE_GENEXPR_FUNCTION):
                    raise ValueError('generator creation lacks its original function constructor')
                declarations = [(n, fn) for n, fn in enumerate(facts.functions)
                    if fn.template == template and source_port(facts, fn.value) == context.result(producer)]
                kind, table = 'CREATE_GENEXPR', 'functions'
            else:
                call = type(ins) is P.ApplyLanguageAction and ins.action is P.LanguageActionKind.CALL
                packed = type(ins) is P.ApplyPythonProtocol and ins.protocol is K.CALL_FUNCTION_EX
                if not (call or packed) or ins.selectors[0].occurrence != template.occurrence: continue
                declarations = [(n, cls) for n, cls in enumerate(facts.classes)
                    if cls.template == template and source_port(facts, cls.value) == context.result(step)]
                kind, table = 'BUILD_CLASS', 'classes'
            owner = context.owner(step.region)
            if owner.owner != caller.scope.owner: continue
            if len(declarations) != 1: raise ValueError('protocol operation needs one original definition fact')
            ordinal, declaration = declarations[0]
            world, after = context.worlds(step)
            if context.value(step.arguments[-1]) != world:
                raise ValueError('protocol changed its original last-world argument')
            definition = index.slicer.fact(facts, table, ordinal)
            site = ProtocolSite(kind, definition, context.site(step),
                tuple(context.value(v) for v in step.arguments[:-1]), context.result(step), world, after,
                T.Body(caller.unit, declaration.template, declaration.body), owner,
                'GENERATOR_CODE_MAKE_FUNCTION_ITERATOR_CALL' if kind == 'CREATE_GENEXPR'
                    else 'CLASS_BUILD_CODE_MAKE_FUNCTION_CALL')
            markers = [n for n, x in enumerate(instructions) if x.opname == 'LOAD_CONST'
                and type(x.argval) is CodeType and tuple(x.positions) == span
                and (kind != 'CREATE_GENEXPR' or x.argval.co_name == '<genexpr>')]
            for n, instruction in positions[span]:
                before = [m for m in markers if m < n
                    and any(x.opname == 'MAKE_FUNCTION' and tuple(x.positions) == span
                        for x in instructions[m + 1:n])]
                if len(before) != 1: continue
                if kind == 'CREATE_GENEXPR':
                    valid = instruction.opname == 'CALL' and instruction.arg == 0 and n > 0 \
                        and instructions[n - 1].opname in ('GET_ITER', 'GET_AITER')
                else:
                    valid = any(x.opname == 'LOAD_BUILD_CLASS' and tuple(x.positions) == span
                        for x in instructions[:before[0]])
                    if call:
                        valid = valid and instruction.opname in ('CALL', 'CALL_KW') \
                            and instruction.arg == len(step.arguments) - 2
                    else: valid = valid and instruction.opname == 'CALL_FUNCTION_EX'
                if valid: result[instruction.offset].append(site)
    cache[key] = dict(result)
    return cache[key]
