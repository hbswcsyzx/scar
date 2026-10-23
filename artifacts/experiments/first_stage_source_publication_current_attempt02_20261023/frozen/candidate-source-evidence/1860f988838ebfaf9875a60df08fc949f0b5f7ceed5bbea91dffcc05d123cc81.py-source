"""Original await anchors retained independently from budgeted associations.

Explicit link/case FKs supply declared, unchecked candidates only. Independent
source, advance and Drive inventories never become a Cartesian ownership join.
"""
def _key(job):
    return (job['source'], job['advance'], job.get('input_guard'),
            job['choices'], job['drive'])


def prepare(ctx, advances, links):
    from .protocol_await import _site, success_source
    by_advance = {_site(row): row for row in advances}
    grouped, templates = {}, []
    for link in links:
        grouped.setdefault((link.source, link.advance, link.drive), []).append(link)
    for (source, advance, drive), originals in grouped.items():
        row = ctx.rows.get((source.scope, source.clause, source.operation, source.slot))
        step = by_advance.get(advance)
        if row is None or step is None:
            continue
        port, forced = success_source(ctx, row)
        attachment = ctx.call_inputs.get(advance)
        cases = (None,) if attachment is None or not attachment.cases else attachment.cases
        for case in cases:
            guard = None if case is None else case.guard
            choices = forced if guard is None or guard in forced else (*forced, guard)
            conflict = any(a.operation == b.operation and a != b
                           for number, a in enumerate(choices) for b in choices[number + 1:])
            templates.append({'scope': source.scope, 'source': source,
                'source_operation': source.operation, 'source_success': port,
                'accepted_edges': forced, 'choices': choices, 'case': case,
                'input_guard': guard, 'input_case_missing': case is None,
                'advance': advance, 'advance_operation': advance.operation,
                'iterator_use': None, 'drive': drive, 'links': tuple(originals),
                'binding': None, 'status': 'NOT_CHECKED',
                'gaps': ('await_declared_association_unchecked',),
                'cursor': {'phase': 'await_declared_association', 'advance': advance},
                'choice_conflict': conflict, 'declared_anchor_only': True})
    ctx._await_declared_job_templates = tuple(templates)
    ctx._await_original_anchor_inventory = {
        'advances': tuple(by_advance), 'links': tuple(links),
        'drives': tuple((drive.operation, tuple(edge.source for edge in
            ctx.operations[drive.operation].terminator.successors)) for drive in ctx.graph.body_drives),
        'associations_total': None,
        'meaning': 'independent original anchors and declared FKs; not reached ownership or complete pairing'}
    ctx.preparation['await_declared_link_case_templates'] = len(templates)
    ctx.preparation['await_original_advance_anchors'] = len(advances)
    ctx.preparation['await_ownership_joins_precomputed'] = 0


def unchecked_suffix(ctx, jobs):
    """Present raw original tuples without deriving an unpaid suffix."""
    present = {_key(job) for job in jobs}
    result = []
    for original in ctx._await_declared_job_templates:
        if _key(original) not in present:
            result.append(original)
            present.add(_key(original))
    ctx.preparation['await_unchecked_declared_jobs_presented'] = len(result)
    return tuple(result)
