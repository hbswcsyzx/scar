"""Check the model specification inventory and observe independent Python cases.

This does not execute SCAR graphs or certify their implementation.
"""
from __future__ import annotations

import argparse
import ast
import copy
import hashlib
import importlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import time
import uuid


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def grammar_inventory(catalog):
    base_names = (
        'mod', 'stmt', 'expr', 'pattern', 'type_param', 'expr_context',
        'operator', 'unaryop', 'boolop', 'cmpop', 'excepthandler',
    )
    legacy = {'Suite', 'AugLoad', 'AugStore', 'Param'}
    classes = {}
    for base_name in base_names:
        for cls in getattr(ast, base_name).__subclasses__():
            if cls.__name__ not in legacy:
                classes[cls.__name__] = cls
    for name in ('comprehension', 'arguments', 'arg', 'keyword', 'alias',
                 'withitem', 'match_case', 'TypeIgnore'):
        classes[name] = getattr(ast, name)
    owners = {}
    for line in catalog.read_text().splitlines():
        if not line.startswith('| ') or line.count('|') != 4:
            continue
        columns = [item.strip() for item in line.split('|')[1:-1]]
        if columns[0] in ('协议族', '---'):
            continue
        for name in re.findall(r'`([A-Za-z_][A-Za-z_0-9]*)`', columns[1]):
            owners.setdefault(name, []).append(columns[0])
    missing = sorted(set(classes) - set(owners))
    extra = sorted(set(owners) - set(classes))
    duplicates = {name: value for name, value in owners.items() if len(value) != 1}
    assert not (missing or extra or duplicates), (missing, extra, duplicates)
    return {
        'status': 'PASS', 'scope': 'canonical AST ownership index only',
        'constructs': len(classes), 'protocol_families': len({x[0] for x in owners.values()}),
        'missing': missing, 'extra': extra, 'duplicates': duplicates,
        'records': [{'name': name, 'fields': list(cls._fields),
                     'owner': owners[name][0]} for name, cls in sorted(classes.items())],
        'legacy_exclusions': sorted(legacy),
        'field_evaluation_rules_complete': False,
        'automatic_lowering_complete': False,
    }


def observations():
    results = []

    def record(name, observed, obligation):
        results.append({'case': name, 'status': 'PASS', 'observed': observed,
                        'model_obligation': obligation})

    def replaced():
        try:
            return 1
        finally:
            return 2

    assert replaced() == 2
    record('finally_replaces_completion', 2, 'pending completion and cleanup dispatch')

    def referenced():
        value = [1]
        try:
            return value
        finally:
            value.append(2)

    assert referenced() == [1, 2]
    record('return_payload_is_reference', [1, 2], 'post-state independent of return reference')

    class Suppress:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return True

    def suppressed():
        with Suppress():
            raise ValueError('expected')
        return 3

    def returned():
        with Suppress():
            return 7
        return 99

    assert (suppressed(), returned()) == (3, 7)
    record('with_suppresses_raise_only', [3, 7], 'typed cleanup variants')

    shared = [0]
    entered = []

    def suspended():
        entered.append('entered')
        yield shared[0]
        yield shared[0]
        return 22

    generator = suspended()
    assert entered == []
    first = next(generator)
    shared[0] = 4
    second = next(generator)
    try:
        next(generator)
    except StopIteration as exception:
        final = exception.value
    else:
        raise AssertionError('expected exhaustion')
    assert (first, second, final) == (0, 4, 22)
    record('generator_creation_resume_and_return', [first, second, final],
           'saved frame plus current shared world; yield and final return adapters')

    def factory(initial):
        state = initial

        def read():
            return state

        def write(value):
            nonlocal state
            state = value

        return read, write

    read_a, write_a = factory(1)
    read_b, _ = factory(2)
    assert read_a.__code__ is read_b.__code__
    write_a(9)
    assert (read_a(), read_b()) == (9, 2)
    record('same_code_different_shared_cells', [9, 2], 'implicit environment and cell state')

    def unbound():
        return local
        local = 1

    try:
        unbound()
    except UnboundLocalError:
        record('unreachable_assignment_affects_scope', 'UnboundLocalError',
               'compile scope retains nonexecuted source')
    else:
        raise AssertionError('expected unbound local')

    values = [3]
    old = values[0]
    values[0] = 9
    assert (old, values[0]) == (3, 9)
    record('read_before_overwrite', [old, values[0]], 'WAR order; state version is not snapshot')

    effects = []

    class CustomCopy:
        def __deepcopy__(self, memo):
            effects.append('copied')
            return [8]

    copied = copy.deepcopy(CustomCopy())
    assert copied == [8] and effects == ['copied']
    source = [1]
    other = copy.deepcopy(source)
    other[0] = 6
    assert source == [1]
    record('copy_dispatch_and_independent_mutation', [copied, effects, source, other],
           'actual copy protocol; lineage forks; equality does not imply alias')

    buffer = bytearray(b'abcd')
    view = memoryview(buffer)[1:3]
    identity = id(view)
    before = bytes(view).decode()
    buffer[1] = ord('z')
    after = bytes(view).decode()
    assert id(view) == identity and (before, after) == ('bc', 'zc')
    view.release()
    record('same_view_reference_changed_content', [before, after],
           'reference denotation separate from current content and overlapping storage')

    with tempfile.TemporaryDirectory(prefix='scar-model-spec-probe-') as temporary:
        root = Path(temporary)
        path = root / 'data'
        path.write_bytes(b'abc')
        first_fd = os.open(path, os.O_RDONLY)
        duplicate = os.dup(first_fd)
        separate = os.open(path, os.O_RDONLY)
        try:
            reads = [os.read(first_fd, 1).decode(), os.read(duplicate, 1).decode(),
                     os.read(separate, 1).decode()]
        finally:
            for descriptor in (first_fd, duplicate, separate):
                os.close(descriptor)
        assert reads == ['a', 'b', 'a']
        path.write_bytes(b'xyz')
        assert path.read_bytes() == b'xyz'
        record('file_entity_description_handle_and_content', reads + ['xyz'],
               'dup shares offset, open need not; path identity is not content stability')

        module_name = 'scar_model_probe_' + uuid.uuid4().hex
        log = root / 'initialization.txt'
        (root / (module_name + '.py')).write_text(
            'from pathlib import Path\n'
            f'with Path({str(log)!r}).open("a") as stream:\n'
            '    stream.write("init\\n")\n'
            'VALUE = 7\n')
        sys.path.insert(0, str(root))
        try:
            one = importlib.import_module(module_name)
            two = importlib.import_module(module_name)
            assert one is two and one.VALUE == 7 and log.read_text() == 'init\n'
            record('constant_import_retains_initialization_effect', [7, 'init once'],
                   'value replacement and import deletion require distinct liveness proofs')
        finally:
            sys.path.remove(str(root))
            sys.modules.pop(module_name, None)
            importlib.invalidate_caches()
    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--scar-root', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    started = time.monotonic()
    assert sys.version_info[:2] == (3, 14), sys.version
    docs = args.scar_root / 'docs'
    inputs = [docs / name for name in (
        'WHOLE_PROGRAM_MODEL.md', 'PYTHON314_PROTOCOL_CATALOG.md',
        'WHOLE_PROGRAM_MODEL_PLAN.md', 'WHOLE_PROGRAM_MODEL_REVIEW.md',
        'N2_STRUCTURED_BODY_ACCEPTANCE.md',
    )]
    broken = []
    for path in inputs:
        for target in re.findall(r'\]\(([^)]+)\)', path.read_text()):
            if '://' in target or target.startswith('#'):
                continue
            resolved = (path.parent / target.split('#')[0]).resolve()
            if resolved == (args.out / 'report.json').resolve():
                continue  # This invocation produces this declared output after all checks.
            if not resolved.exists():
                broken.append({'source': str(path), 'target': target})
    assert not broken, broken
    inventory = grammar_inventory(docs / 'PYTHON314_PROTOCOL_CATALOG.md')
    cases = observations()
    args.out.mkdir(parents=True, exist_ok=True)
    result = {
        'schema': 'scar.model-spec-review', 'schema_version': 1,
        'status': 'PASS', 'scope': 'AST index conservation and independent Python observations only',
        'python': sys.version, 'executable': sys.executable,
        'argv': sys.argv, 'driver_sha256': sha(Path(__file__)),
        'document_hashes': {str(path.relative_to(args.scar_root)): sha(path) for path in inputs},
        'local_document_links': {'status': 'PASS', 'broken': broken},
        'ast_inventory': inventory, 'independent_language_cases': cases,
        'duration_seconds': time.monotonic() - started,
        'whole_model_implemented': False, 'whole_program_graph_verified': False,
        'gpu_readiness_verified': False, 'transformation_authorized': False,
        'note': 'No SCAR graph interpreter/lowerer is called. This is not model implementation acceptance.',
    }
    (args.out / 'report.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'status': result['status'], 'constructs': inventory['constructs'],
                      'families': inventory['protocol_families'], 'cases': len(cases),
                      'duration_seconds': result['duration_seconds']}))


if __name__ == '__main__':
    main()
