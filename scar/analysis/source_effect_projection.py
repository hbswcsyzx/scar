"""Project source effects without executing values or decoding other bodies.

Original binding/content access tables refine individual fields when those
adapters are already attached. Unknown callbacks, physical allocation and
object contents remain unknown independently of known source accesses.
"""
from scar.analysis.source_effects import classify_instruction
from scar.analysis.source_namespace_interfaces import NamespacePlanView
from scar.ir.effects import Knowledge as K
from scar.ir.program import source_state as S, source_productions as P
from scar.ir.program import normal_graph as G, model as M
from scar.ir.program.control import LanguageCompletionKind as C
from scar.ir.program.normal_targets import GlobalPort


COLLECTION_FIELDS = ('reads', 'writes', 'allocates', 'frees', 'aliases', 'escapes')
SCALAR_FIELDS = ('rng_effect', 'may_raise', 'external_effect', 'ordering_effect')
_IDENTITY_INTRINSICS = (P.ReferenceIsNone, P.ReferenceIdentical, P.InvertCondition)


def project_effects(source, point):
    source.ensure(point)
    step = source.records[point.node]
    if type(step) is not P.ProductionStep:
        raise TypeError('source effect summaries require an original operation')
    anchor = source.nodes[point.node].anchor
    context = source.effect_contexts.get(anchor.template)
    if context is None:
        context = NamespacePlanView(source.unit, source.plans[anchor.template])
        source.effect_contexts[anchor.template] = context
    rule = classify_instruction(step.instruction)
    def state(type_): return type(type_) is M.ValueType and type_.kind is M.ValueKind.STATE
    inputs = tuple(context.value(value) for value in step.arguments if state(context.emitter.value(value)[1]))
    outputs = tuple(GlobalPort(source.unit, context.emitter.port(step.id, G.PortKind.RESULT, n, completion))
        for completion in step.completions for n, type_ in enumerate(completion.types) if state(type_))
    fields = {name:S.SourceEffectSet() for name in COLLECTION_FIELDS}
    scalar = {name:K.UNKNOWN for name in SCALAR_FIELDS}
    missing = ()
    provider = source.effect_provider
    if provider is not None:
        provider.check(point)
        request = provider.effects(point)
        missing = request.missing_rules
        accesses = tuple((n, provider.accesses[n]) for n in request.accesses)
        if any(a.operation != point.node for _, a in accesses):
            raise ValueError('source effect access belongs to a different operation')
        read = tuple(n for n, a in accesses if a.kind is S.BindingAccessKind.READ)
        write = tuple(n for n, a in accesses if a.kind in (S.BindingAccessKind.WRITE, S.BindingAccessKind.DELETE))
        content = provider.content_provider
        contents = () if content is None else tuple((n, content.accesses[n])
            for n in content.operation_accesses.get(point.node, ()))
        if any(a.operation != point.node for _, a in contents):
            raise ValueError('source content effect belongs to a different operation')
        reads = tuple(n for n, a in contents if a.kind.value in ('GET', 'UPDATE'))
        writes = tuple(n for n, a in contents if a.kind.value in ('SET', 'DELETE', 'UPDATE'))
        fields['reads'] = S.SourceEffectSet(K.UNKNOWN, read, reads)
        fields['writes'] = S.SourceEffectSet(K.UNKNOWN, write, writes)
        # A direct lexical load has no mapping/descriptor callback. This
        # neither selects an instance nor proves referenced object contents.
        if (type(step.instruction) is P.AccessBinding and step.instruction.action is P.BindingActionKind.READ
                and len(accesses) == 1 and accesses[0][1].alternatives
                and all(provider.locations[a.location].interface.kind == 'LEXICAL_BINDING'
                    for a in accesses[0][1].alternatives)):
            fields['reads'] = S.SourceEffectSet(K.KNOWN, read, reads)
            fields['writes'] = S.SourceEffectSet(K.NONE)
            for name in ('rng_effect', 'external_effect', 'ordering_effect'): scalar[name] = K.NONE
    elif rule.resolution.value == 'ADDRESS_RULE':
        missing = ('SOURCE_STATE_ADDRESS_PROVIDER_NOT_ATTACHED',)
    if type(step.instruction) in _IDENTITY_INTRINSICS:
        fields['reads'] = fields['writes'] = S.SourceEffectSet(K.NONE)
        for name in SCALAR_FIELDS: scalar[name] = K.NONE
    elif any(completion.kind is C.RAISE for completion in step.completions):
        # A declared exceptional route is possible, not an observed raise.
        scalar['may_raise'] = K.KNOWN
    unresolved = tuple(name for name in COLLECTION_FIELDS if fields[name].knowledge is K.UNKNOWN) + \
        tuple(name for name in SCALAR_FIELDS if scalar[name] is K.UNKNOWN)
    return S.SourceEffectSummary(point.node, rule, inputs, outputs,
        *(fields[name] for name in COLLECTION_FIELDS), *(scalar[name] for name in SCALAR_FIELDS),
        unresolved, missing)
