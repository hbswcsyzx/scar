"""Reference/denominator audits of original output, not another IR or binder."""
from collections import Counter
import gzip
import json
from pathlib import Path

from config import HERE, OLD, BASELINE, REVISION, BUDGETS, EXPECTED_RUN
from prepare import load
from report_archive import write_json


def need(condition, detail):
    if not condition: raise ValueError('revision-current audit: ' + detail)


def key(value):
    return value['process_id'], value['thread_id'], value['invocation_id']


def rows(path):
    total = count = 0
    with gzip.open(path, 'rb') as stream:
        while raw := stream.readline(BUDGETS['audit_line_bytes'] + 1):
            total += len(raw); count += 1
            need(len(raw) <= BUDGETS['audit_line_bytes'] and raw.endswith(b'\n')
                and total <= BUDGETS['audit_stream_decoded_bytes']
                and count <= BUDGETS['audit_stream_rows'], 'output audit stream ceiling exceeded')
            yield json.loads(raw)


def snapshot(index):
    revision = load(REVISION / 'summary.json')
    header = index.inventory_component('header')
    counts = Counter(body['status'] for file in index.document['files'] for body in file['bodies'])
    need(len(index.document['files']) == revision['source_files'], 'published source denominator differs')
    need(sum(counts.values()) == revision['static_body_denominator'], 'published static-body denominator differs')
    need(dict(counts) == revision['header_summary']['body_statuses'], 'active body accounting differs')
    changed = index.publication_header()['changed_body_keys']
    active = {}
    for row in changed:
        fi, bi = row['file_index'], row['body_index']
        body = index.document['files'][fi]['bodies'][bi]
        expected = next(value for value in revision['active_bodies']
            if value['definition']['wire'] == body['definition'])
        need(body['namespace'] == expected['namespace'], 'published replacement namespace differs')
        old_namespace = row['expectation']['expected_namespace']
        need(body['namespace'] != old_namespace, 'changed body retained its previous namespace')
        active[body['definition']] = {'operation': row['operation'], 'file_index': fi, 'body_index': bi,
            'namespace': body['namespace'], 'historical_namespace': old_namespace,
            'program_canonical_sha256': body['program_canonical_sha256'], 'root': body['root']}
    need(len(active) == len(revision['active_bodies']), 'revision changed-body scope differs')
    result = {'source_files': len(index.document['files']), 'static_bodies': sum(counts.values()),
        'body_statuses': dict(counts), 'changed_bodies': active,
        'published_snapshot_reused': True, 'publisher_reexecuted': False,
        'historical_old_graph_typed_legality_asserted': False,
        'whole_lifetime_established': False, 'transformation_authorized': False}
    write_json(HERE / 'snapshot-audit.json', result)
    return active


def dynamic(index, connected, document, changed, result_directory):
    source_dir = Path(connected['source_directory'])
    source = connected['source_report']
    previous = load(OLD / 'result/source/bindings.json')['bindings']
    current = load(source_dir / 'bindings.json')['bindings']
    old = {(row['process_id'], row['code']): row for row in previous}
    new = {(row['process_id'], row['code']): row for row in current}
    need(len(new) == len(current) and set(new) == set(old), 'original process/code group denominator differs')
    by_definition, categories, changed_counts = {}, Counter(), {}
    for group, row in new.items():
        before = old[group]
        need(all(row[name] == before[name] for name in
            ('entered_invocations', 'definition', 'code_capture', 'snapshot', 'source')),
            'original static proof/group weight changed')
        if before['status'] == 'UNRESOLVED':
            need(row['status'] == 'UNRESOLVED', 'unresolved source was silently promoted')
        if row['body'] is None: continue
        ref = row['body']['reference']; fi, bi = ref['file_index'], ref['body_index']
        body = index.document['files'][fi]['bodies'][bi]
        need(body['definition'] == row['definition']['definition']['wire']
            and index.document['files'][fi]['snapshot'] == row['snapshot'], 'body/source qualification differs')
        for a, b in (('namespace', 'namespace'), ('canonical_locator', 'graph_locator'),
                     ('metadata_locator', 'metadata_locator'), ('inventory_locator', 'inventory_locator'),
                     ('program_canonical_sha256', 'program_canonical_sha256')):
            need(row['body'][a] == body[b], 'active original body locator/hash differs')
        definition = body['definition']
        need(definition not in by_definition or by_definition[definition] == row['body'],
            'bare definition is ambiguous across original qualified bodies')
        by_definition[definition] = row['body']
        category = changed[definition]['operation'] if definition in changed else 'OTHER_ACTIVE_NAMESPACE'
        categories[category] += row['entered_invocations']
        if definition in changed:
            entry = changed_counts.setdefault(definition, {'groups': 0, 'calls': 0, 'namespace': body['namespace']})
            entry['groups'] += 1; entry['calls'] += row['entered_invocations']
    report = connected['operand_report']
    groups = Counter((edge.entry.invocation.process_id, edge.entry.code) for edge in report.frame_model.edges)
    need(groups == Counter({group: row['entered_invocations'] for group, row in new.items()}),
        'owned current raw/source group weights differ')
    original_summary = load(OLD / 'result/source/report.json')['summary']
    need(len(groups) == original_summary['entered_code_groups']
        and len(report.frame_model.codes) == original_summary['code_captures']
        and sum(groups.values()) == original_summary['invocations']
        and len(report.frame_model.exits) == original_summary['exits'], 'original frame denominator changed')
    baseline_summary = load(BASELINE / 'summary.json')
    need(len(report.operands.events) == baseline_summary['reader_counts']['operand_events'], 'operand denominator changed')
    need(report.environments['summary']['events'] == baseline_summary['current']['environment_summary']['events'],
        'environment denominator changed')
    # Every output invocation is checked against the freshly owned in-memory
    # raw edge. No historical invocation stream supplies current observations.
    entries = {(e.entry.invocation.process_id, e.entry.invocation.thread_id, e.entry.invocation.invocation_id):
        new[e.entry.invocation.process_id, e.entry.code] for e in report.frame_model.edges}
    raw_entries = {(e.entry.invocation.process_id, e.entry.invocation.thread_id, e.entry.invocation.invocation_id):
        e.entry for e in report.frame_model.edges}
    observed, activations, namespaces, seen = Counter(), 0, Counter(), set()
    for row in rows(source_dir / 'invocations.jsonl.gz'):
        invocation = key(row['invocation']); binding = entries[invocation]
        need(invocation not in seen, 'current source output repeated an InvocationKey')
        seen.add(invocation)
        anchor = raw_entries[invocation].anchor
        need(row['anchor'] == {'path': anchor.path, 'line_number': anchor.line_number,
            'line_sha256': anchor.line_sha256, 'index': anchor.index}, 'current invocation raw anchor differs')
        need(row['source_binding_index'] == binding['binding_index'] and row['code'] == binding['code'],
            'current invocation does not select its fresh binding')
        observed[binding['process_id'], binding['code']] += 1
        namespace = binding['body']['namespace'] if binding['body'] is not None else None
        need(row['region_namespace'] == namespace, 'invocation carries a stale namespace')
        if row['region_activation'] is not None:
            need(namespace is not None and not row['suspended'], 'activation has no eligible current body')
            need(row['region_activation']['entry']['run']['value'] == EXPECTED_RUN,
                'activation is outside the original current Run')
            need(row['region_activation']['region'] == binding['body']['reference']['identity'],
                'activation region differs from the active qualified body')
            activations += 1
        if namespace is not None:
            namespaces[json.dumps(namespace, sort_keys=True, separators=(',', ':'))] += 1
    need(observed == groups and seen == set(raw_entries), 'fresh invocation output lost/repeated original members')
    marker_count = slots = 0; marker_statuses = Counter()
    for row in rows(result_directory / 'connections/dispatch/associations.jsonl.gz'):
        marker_count += 1; slots += len(row['qualified_slot_path_indices'])
        marker_statuses[row['status']] += 1
        need(row['direct_callsite_established'] is False, 'marker invented a direct callsite')
    baseline = load(BASELINE / 'dynamic-audit.json')
    need((marker_count, slots) == (baseline['markers'], baseline['marker_slots']), 'original marker denominator changed')
    need(source['run']['id']['value'] == EXPECTED_RUN, 'current source Run identity changed')
    result = {'current_groups': len(groups), 'current_invocations': sum(observed.values()),
        'current_exits': len(report.frame_model.exits), 'captured_codes': len(report.frame_model.codes),
        'operand_events': len(report.operands.events), 'environment_events': report.environments['summary']['events'],
        'current_activations': activations, 'current_body_groups': sum(row['body'] is not None for row in current),
        'current_body_calls': sum(row['entered_invocations'] for row in current if row['body'] is not None),
        'binding_statuses': dict(Counter(row['status'] for row in current)),
        'source_summary': source['summary'], 'changed_body_actual_current_counts': changed_counts,
        'body_call_namespace_categories': dict(categories),
        'namespace_invocation_counts': [{'namespace': json.loads(k), 'calls': v} for k, v in sorted(namespaces.items())],
        'markers': marker_count, 'marker_slots': slots, 'marker_statuses': dict(marker_statuses),
        'entry_parameter_occurrences': len(report.entry_parameters),
        'operand_route_summary': report.routing.summary(), 'environment_summary': report.environments['summary'],
        'counts_derived_from_fresh_current_outputs': True, 'historical_counts_used_as_results': False,
        'logical_contents_world_effects_or_readiness_established': False}
    write_json(HERE / 'dynamic-audit.json', result)
    scope = reference_scopes(index, document, changed, entries, by_definition)
    write_json(HERE / 'reference-scope-audit.json', scope)
    return result, scope


def reference_scopes(index, document, changed, entries, by_definition):
    """Resolve original references through the already selected qualified bodies.

    Existing SBA supplies full typed admission and ID validation. This audit
    checks all namespace scopes without decoding source graphs a second time.
    It neither assigns effects nor invents graph/Use identities.
    """
    totals = Counter(); scoped = Counter()
    def body_for(invocation, definition=None):
        binding = entries[key(invocation)]
        need(binding['body'] is not None, 'core reference has no fresh qualified body')
        if definition is not None:
            need(binding['definition']['definition'] == definition, 'reference definition differs from invocation')
        return binding['body']
    def check_scope(value, body, table):
        definition = body['namespace']['body']['definition']['wire']
        category = changed[definition]['operation'] if definition in changed else 'OTHER_ACTIVE_NAMESPACE'
        totals[table] += 1; scoped[table + ':' + category] += 1
    for row in document['entry_parameters']:
        body = body_for(row['owner']); check_scope(row, body, 'formal')
    routing = document['routing']
    for row in routing['templates']:
        body = by_definition[row['definition']['wire']]
        need(row['region'] == body['reference']['identity'], 'template root differs from active body')
        check_scope(row, body, 'template')
    for row in routing['returns']:
        body = body_for(row['invocation'], row['definition'])
        need(row['region'] == body['reference']['identity'], 'return root differs from active body')
        check_scope(row, body, 'return')
    for table in ('argument_routes', 'completion_routes'):
        for row in routing[table]:
            caller = body_for(row['caller'], row['caller_definition'])
            callee = body_for(row['callee'], row['callee_definition'])
            need(row['caller_region'] == caller['reference']['identity']
                and row['callee_region'] == callee['reference']['identity'], 'route namespace/root differs')
            check_scope(row, caller, table + '.caller')
            check_scope(row, callee, table + '.callee')
    for row in document['environments']['bindings']:
        body = body_for(row['invocation'], row['definition'])
        need(row['body_namespace'] == body['namespace'], 'environment retained a stale body namespace')
        need(row['region'] == body['reference']['identity'], 'environment root differs from active body')
        check_scope(row, body, 'environment')
    return {'reference_rows': dict(totals), 'reference_namespace_categories': dict(scoped),
        'changed_body_namespace_scopes': changed,
        'program_id_validation_performed_by_existing_SBA': True,
        'additional_source_graph_decodes_in_this_audit': 0,
        'qualified_scope_comes_from_fresh_invocation_binding': True,
        'historical_bad_graph_typed_or_reused': False, 'original_report_unchanged_by_audit': True,
        'whole_lifetime_established': False, 'world_equivalence_established': False,
        'transformation_authorized': False}
