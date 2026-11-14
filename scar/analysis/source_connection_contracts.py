"""Independent, schema-total checks for shared source entry references.

The input denominator is ProductionInstruction, not the producer's emitted
edges. This layer checks local template connections only; runtime dispatch,
object identity, effects and resource placement require separate evidence.
"""
from collections import Counter
from dataclasses import fields, is_dataclass
from functools import lru_cache
from hashlib import sha256
import argparse
import gzip
import json
from pathlib import Path
import time
from typing import get_args, get_origin, get_type_hints

from scar.ir.program import source_productions as P
from scar.ir.program.control import LanguageCompletionKind
from scar.ir.program.source_effects import EffectFamily
from scar.ir.record_codec import decode


class ConnectionContractError(ValueError):
    pass


def _stamp(value):
    return value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns


# Paths describe the *declared schema*. '*' expands a tuple, not executions.
# None denotes a control destination, which must not create a template entry.
_REFERENCE_RULES = {
    P.BuildFunctionAnnotations: ((('body',), P.CompilationEdgeKind.CODE_DECLARATION),),
    P.BuildLazyExpression: ((('body',), P.CompilationEdgeKind.CODE_DECLARATION),),
    P.DeferClassBody: ((('body',), P.CompilationEdgeKind.CODE_DECLARATION),),
    P.BuildClassAnnotations: ((('body',), P.CompilationEdgeKind.CODE_DECLARATION),),
    P.BuildScopeAnnotations: ((('body',), P.CompilationEdgeKind.CODE_DECLARATION),),
    P.DeferRegion: ((('body',), P.CompilationEdgeKind.CODE_DECLARATION),),
    P.ApplyRegion: ((('invocation', 'region'), P.CompilationEdgeKind.CALL),),
    P.InvokeTypeParameterFactory: ((('invocation', 'region'), P.CompilationEdgeKind.TYPE_FACTORY),),
    P.BranchControl: (
        (('on_true', 'region'), P.CompilationEdgeKind.CALL),
        (('on_false', 'region'), P.CompilationEdgeKind.CALL)),
    P.LoopControl: (
        (('condition',), P.CompilationEdgeKind.LOOP_CONDITION),
        (('condition', 'advance', 'region'), P.CompilationEdgeKind.LOOP_CONDITION),
        (('condition', 'exhausted'), P.CompilationEdgeKind.LOOP_EXIT),
        (('body',), P.CompilationEdgeKind.LOOP_BODY),
        (('otherwise',), P.CompilationEdgeKind.LOOP_EXIT)),
    P.HandleCompletions: (
        (('protected', 'region'), P.CompilationEdgeKind.CALL),
        (('routes', '*', 'target'), None),
        (('routes', '*', 'handler'), P.CompilationEdgeKind.COMPLETION_HANDLER)),
    P.TransferCompletion: ((('target',), None),),
    P.SuspendExecution: ((('routes', '*', 'region'), P.CompilationEdgeKind.RESUME),),
}

# A handle reference is not a body activation. These cases have distinct
# original namespace ABIs, rather than a fabricated common function ABI.
_ENVIRONMENT_RULES = {
    P.ReferenceEnvironment: ('source', False),
    P.EnterRootBody: ('interface', True),
    P.EnterDeferredBody: ('environment', True),
    P.EnterClassBody: ('interface', True),
    P.EnterTypeParameters: ('environment', True),
    P.EnterEvaluationRequest: ('environment', True),
}


def body_entry_rules():
    """The complete body-entry family, excluding environment handle reads."""
    connection_reference_catalog()
    return tuple((kind, field) for kind, (field, is_entry) in _ENVIRONMENT_RULES.items() if is_entry)


@lru_cache(None)
def _region_fields(kind, path=(), active=()):
    """Find all region-address fields independently of producer branches.

    ProductionParameter.region addresses a data operand's owner; it is not
    a code-entry reference. The existing value/ownership layer checks it.
    """
    if kind is P.ProductionRegionID:
        return frozenset((path,))
    if kind in active or kind in (P.ProductionParameter, P.ProductionResult):
        return frozenset()
    args = get_args(kind)
    if args:
        suffix = ('*',) if get_origin(kind) is tuple else ()
        return frozenset().union(*(_region_fields(arg, path + suffix, active + (kind,))
            for arg in args if arg is not Ellipsis))
    if isinstance(kind, type) and is_dataclass(kind):
        return frozenset().union(*(_region_fields(field_type, path + (name,), active + (kind,))
            for name, field_type in get_type_hints(kind).items()))
    return frozenset()


def connection_reference_catalog():
    """Classify every instruction and every declared region-reference field.

    New instructions enter the denominator automatically. A new reference
    field cannot fall through to an empty producer/validator branch together.
    No-reference does not imply no effects or no runtime implementation.
    """
    from scar.analysis.source_effects import catalog as effect_catalog
    instructions = get_args(P.ProductionInstruction)
    effects = {row.instruction: row for row in effect_catalog()}
    if not set(_REFERENCE_RULES) <= set(instructions):
        raise ConnectionContractError('reference rule for an undeclared instruction')
    expected_entries = {kind for kind in instructions
        if effects[kind.__name__].family is EffectFamily.ENVIRONMENT_ENTRY}
    if set(_ENVIRONMENT_RULES) != expected_entries:
        raise ConnectionContractError('environment rules differ from their closed instruction family')
    rows = []
    for kind in instructions:
        rules = _REFERENCE_RULES.get(kind, ())
        declared = _region_fields(kind)
        actual = [path for path, _ in rules]
        if len(set(actual)) != len(actual) or set(actual) != declared:
            raise ConnectionContractError(f'{kind.__name__}: region-field rules differ from schema; '
                f'missing={sorted(declared-set(actual))}, extra={sorted(set(actual)-declared)}')
        rows.append(dict(instruction=kind.__name__, family=effects[kind.__name__].family.value,
            references=[dict(path=list(path), relation=None if edge is None else edge.value,
                role='CONTROL_DESTINATION' if edge is None else 'TEMPLATE_ENTRY') for path, edge in rules],
            child_interface=kind is P.EvaluateChild))
    return dict(schema='scar.source-connection-reference-catalog', schema_version=1,
        implementation_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),
        instructions=rows, instruction_count=len(rows),
        region_reference_fields=sum(len(row['references']) for row in rows),
        environment_protocols=[dict(instruction=kind.__name__, descriptor=field,
            body_entry=is_entry, required_relations=(['SCOPE', 'FORMALS', 'CURRENT_WORLD', 'COMPLETIONS']
                if is_entry else ['ENVIRONMENT_HANDLE']))
            for kind, (field, is_entry) in _ENVIRONMENT_RULES.items()],
        local_connection_schema_complete=True, runtime_connections_checked=False,
        first_stage_complete=False)


@lru_cache(None)
def _field_part(kind, name):
    return P.CompilationPathPart(P.CompilationPathKind.FIELD,
        tuple(field.name for field in fields(kind)).index(name))


def _at_path(value, path, wire=()):
    if not path:
        yield wire, value
    elif path[0] == '*':
        if type(value) is not tuple:
            raise ConnectionContractError('tuple reference path has a non-tuple value')
        for index, item in enumerate(value):
            yield from _at_path(item, path[1:], wire + (
                P.CompilationPathPart(P.CompilationPathKind.ITEM, index),))
    elif is_dataclass(value) and path[0] in {field.name for field in fields(value)}:
        yield from _at_path(getattr(value, path[0]), path[1:],
            wire + (_field_part(type(value), path[0]),))
    # An optional value or another declared Union alternative has no edge.


def required_entry_references(instruction):
    """Enumerate obligations from the schema contract, never producer output."""
    if type(instruction) not in get_args(P.ProductionInstruction):
        raise ConnectionContractError('instruction outside the exact closed input domain')
    if type(instruction) is P.EvaluateChild:
        yield (), P.CompilationEdgeKind.CHILD, instruction
    for path, kind in _REFERENCE_RULES.get(type(instruction), ()):
        if kind is not None:
            for wire, target in _at_path(instruction, path):
                if type(target) is P.ProductionRegionID:
                    yield wire, kind, target


def validate_connection_plan(plan):
    """Check all required local entries and ownership without unrolling loops.

    The ordinary production validator remains responsible for value types,
    state sequencing and completion ABI. This independent pass prevents its
    producer and expected-edge enumeration from sharing an omission.
    """
    if type(plan) is not P.SourceProductionPlan:
        raise ConnectionContractError('exact original source production plan required')
    connection_reference_catalog()
    flow = plan.compilation_flow
    if flow is None:
        raise ConnectionContractError('MISSING_CONTEXT_FLOW')
    if tuple(port.region for port in flow.ports) != tuple(region.id for region in plan.regions):
        raise ConnectionContractError('MISSING_OR_REORDERED_REGION_CONTEXT_PORT')
    ports = {port.region: port for port in flow.ports}
    if len(ports) != len(flow.ports) or any(min(port.source_scope, port.code_scope) < 0
            for port in flow.ports):
        raise ConnectionContractError('INVALID_REGION_CONTEXT_PORT')
    expected = {}; entry_count = 0
    regions = {region.id: region for region in plan.regions}
    for step in plan.steps:
        if step.region not in ports:
            raise ConnectionContractError('STEP_WITHOUT_REGION_CONTEXT')
        protocol = _ENVIRONMENT_RULES.get(type(step.instruction))
        if protocol is not None and protocol[1]:
            descriptor = getattr(step.instruction, protocol[0]); region = regions[step.region]
            if not region.steps or region.steps[0] != step.id:
                raise ConnectionContractError('BODY_ACTIVATION_IS_NOT_FIRST')
            if ports[region.id].source_scope != descriptor.scope:
                raise ConnectionContractError('BODY_ACTIVATION_SCOPE_DIFFERS')
            if step.arguments != tuple(P.ProductionParameter(region.id, i)
                    for i in range(len(region.parameters))):
                raise ConnectionContractError('BODY_FORMALS_NOT_CONNECTED')
            if not region.parameters or region.parameters[-1] != descriptor.world:
                raise ConnectionContractError('BODY_CURRENT_WORLD_NOT_CONNECTED')
            if (len(step.completions) != 1
                    or step.completions[0].kind is not LanguageCompletionKind.FALLTHROUGH
                    or step.completions[0].target is not None
                    or step.completions[0].types != (descriptor.world,)):
                raise ConnectionContractError('BODY_ENTRY_COMPLETION_DIFFERS')
            entry_count += 1
        for path, kind, target in required_entry_references(step.instruction):
            key = step.id, path
            if key in expected:
                raise ConnectionContractError('DUPLICATE_REQUIRED_REFERENCE')
            expected[key] = kind, target, ports[step.region]
    actual = {}
    for edge in flow.edges:
        key = edge.step, edge.path
        if key in actual:
            raise ConnectionContractError('DUPLICATE_ENTRY_EDGE')
        actual[key] = edge
    missing, extra = set(expected)-set(actual), set(actual)-set(expected)
    if missing or extra:
        raise ConnectionContractError(f'ENTRY_RELATION_COVERAGE: missing={len(missing)}, extra={len(extra)}')
    for key, (kind, target, caller) in expected.items():
        edge = actual[key]
        if edge.kind is not kind:
            raise ConnectionContractError('WRONG_ENTRY_RELATION_KIND')
        if type(target) is P.EvaluateChild:
            destination = edge.target
            if (type(destination) is not P.CompilationChildTarget
                    or (destination.field, destination.purpose) != (target.field, target.purpose)
                    or min(destination.source_scope, destination.code_scope) < 0):
                raise ConnectionContractError('WRONG_CHILD_INTERFACE')
        else:
            if edge.target != target or target not in ports:
                raise ConnectionContractError('WRONG_LOCAL_ENTRY_TARGET')
            destination = ports[target]
        transition = (P.CompilationTransition.QUALIFY_SITE
            if caller.code_scope == destination.code_scope else P.CompilationTransition.ENTER_CODE)
        if edge.transition is not transition:
            raise ConnectionContractError('WRONG_CODE_CONTEXT_TRANSITION')
        if (transition is P.CompilationTransition.ENTER_CODE and kind not in (
                P.CompilationEdgeKind.CHILD, P.CompilationEdgeKind.CODE_DECLARATION,
                P.CompilationEdgeKind.TYPE_FACTORY)):
            raise ConnectionContractError('CONTROL_TRANSFER_CHANGES_CODE_OWNER')
    return dict(instructions=len(plan.steps), regions=len(plan.regions),
        required_entry_relations=len(expected), checked_entry_relations=len(actual),
        body_entry_interfaces=entry_count)


def audit_tables(paths, *, expected=None):
    """Stream retained recipe tables; never import or execute target code.

    This is an additional relation gate, not authentication of the original
    material's source/parent receipts. The frontend admits those separately.
    """
    started = time.monotonic()
    catalog = connection_reference_catalog()
    totals = Counter(); inputs = []
    for path in paths:
        path = Path(path).resolve()
        before = path.stat()
        digest = sha256()
        # Hash stored bytes, then stream/decode one plan at a time.
        with path.open('rb') as stream:
            for block in iter(lambda: stream.read(1024*1024), b''):
                digest.update(block)
        if expected is not None and (before.st_size, digest.hexdigest()) != expected[str(path)]:
            raise ConnectionContractError('table differs from its admitted material receipt')
        opener = gzip.open if path.suffix == '.gz' else open
        with opener(path, 'rt', encoding='utf8') as stream:
            for line in stream:
                row = json.loads(line)
                if type(row) is not dict:
                    raise ConnectionContractError('material row must be a record')
                status = row.get('status')
                if status == 'PARENT_SOURCE_DESCRIPTOR':
                    if 'plan' in row or row.get('purpose') != P.ProductionPurpose.DESCRIPTOR.value or not row.get('owner'):
                        raise ConnectionContractError('invalid parent-owned source descriptor')
                    totals['parent_descriptors'] += 1
                    continue
                if status == 'SOURCE_NOT_SCHEDULED':
                    if 'plan' in row or not row.get('suppression', {}).get('reason'):
                        raise ConnectionContractError('suppressed row needs its original reason')
                    totals['suppressed_occurrences'] += 1
                    continue
                if status not in ('LOCAL_SOURCE_RULE', 'LOCAL_CONTEXT_SOURCE_RULE') or type(row.get('plan')) is not dict:
                    raise ConnectionContractError('unadmitted recipe row disposition: '+str(status))
                plan = decode(P.SourceProductionPlan, row['plan'], record_tags=P.PRODUCTION_RECORD_TAGS)
                totals.update(validate_connection_plan(plan)); totals['plans'] += 1
        if _stamp(path.stat()) != _stamp(before):
            raise ConnectionContractError('source table changed during relation gate')
        inputs.append(dict(path=str(path), bytes=before.st_size, sha256=digest.hexdigest()))
    return dict(schema='scar.source-connection-gate', schema_version=1,
        local_connection_schema_complete=catalog['local_connection_schema_complete'],
        local_entry_relations_complete=bool(inputs), checked_tables=len(inputs), inputs=inputs,
        counts=dict(totals), target_executed=False, runtime_connections_checked=False,
        material_admission_checked=False, first_stage_complete=False, seconds=time.monotonic()-started)


def main(argv=None):
    parser = argparse.ArgumentParser(prog='scar connection-contract', description=__doc__)
    parser.add_argument('--table', action='append', default=[], help='original recipe JSONL[.gz]')
    parser.add_argument('--materials', action='append', default=[], help='original recipe material directory')
    parser.add_argument('--out', required=True, help='fresh JSON report file')
    args = parser.parse_args(argv)
    paths = list(map(Path, args.table)); expected = {}; reports = []
    for material in args.materials:
        directory = Path(material).resolve()
        report = directory/'result.json'; raw = report.read_bytes(); document = json.loads(raw)
        reports.append((report, raw))
        if document.get('status') != 'LOCAL_RULES_VERIFIED' or document.get('mode') != 'COLLECTION':
            raise ConnectionContractError('original admitted recipe collection required')
        # The declared material units are the denominator, not discovered files.
        for row in document['units']:
            artifact = row.get('artifact')
            if artifact is None:
                raise ConnectionContractError('declared material unit has no table')
            path = (directory/artifact['path']).resolve()
            if not path.is_relative_to(directory):
                raise ConnectionContractError('table outside its original material directory')
            paths.append(path)
            expected[str(path)] = artifact['bytes'], artifact['sha256']
    if len({path.resolve() for path in paths}) != len(paths):
        raise ConnectionContractError('duplicate input table')
    from scar.analysis.source_connection_domains import connection_domains
    if args.table and args.materials:
        raise ConnectionContractError('select direct tables or admitted materials')
    domains = connection_domains()
    if not domains['type_domains_closed']:
        raise ConnectionContractError('connection input classification domains are open')
    result = audit_tables(paths, expected=expected if args.materials else None)
    if any(path.read_bytes() != raw for path, raw in reports):
        raise ConnectionContractError('material receipt changed during relation gate')
    result['material_reports'] = [dict(path=str(path), sha256=sha256(raw).hexdigest())
        for path, raw in reports]
    result['domains'] = domains
    result['input_type_domains_closed'] = domains['type_domains_closed']
    result['reference_catalog'] = connection_reference_catalog()
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open('x') as stream:
        json.dump(result, stream, indent=2, allow_nan=False); stream.write('\n')
    print(json.dumps({key: value for key, value in result.items()
        if key not in ('inputs', 'domains', 'reference_catalog')}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
