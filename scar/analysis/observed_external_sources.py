"""Find code-equivalent current external source without importing target code.

Typed code captures are inputs, not proof that every captured template ran.
Current file bytes and compatible compiler recipes do not establish historical
source identity, the original compile request, or a callable's environment.
"""
from collections import Counter, defaultdict
from hashlib import sha256
import json
from pathlib import Path
import re
import sys
import time
from types import CodeType

from scar.analysis.call_compilation import supported_future_flag_mask
from scar.analysis.source_consumer_parents import _stamp
from scar.analysis.source_stage import _durable_bytes, _durable_mkdir
from scar.analysis.source_template_links import _json
from scar.ir.program.call_edges import CodeCapture
from scar.ir.record_codec import decode, encode
from scar.trace.code_snapshot import describe_code


SCHEMA = 'scar.observed-external-source-matches'
_FALSE = ('target_executed', 'original_compile_options_proven', 'historical_source_version_proven',
    'execution_namespace_proven', 'capture_implies_body_entry', 'source_code_temporal_pairing_proven',
    'first_stage_complete')


def _producer(): return sha256(Path(__file__).read_bytes()).hexdigest()


def _receipt(path, raw):
    return dict(path=str(path), bytes=len(raw), sha256=sha256(raw).hexdigest())


def _source_candidate(filename):
    path = Path(filename)
    if path.is_absolute():
        return path, dict(kind='ABSOLUTE_CAPTURE_FILENAME'), None
    match = re.fullmatch(r'<frozen ([^<>]+)>', filename)
    if match is None:
        return None, None, 'NO_ABSOLUTE_OR_OFFICIAL_FROZEN_SOURCE_CANDIDATE'
    module = match.group(1)
    if not all(part.isidentifier() for part in module.split('.')):
        return None, None, 'INVALID_FROZEN_MODULE_CANDIDATE'
    # This is CPython's built-in metadata lookup, not the programmable
    # meta_path/importlib.find_spec route. No target module is imported.
    import _imp
    from importlib._bootstrap import FrozenImporter
    info = _imp.find_frozen(module)
    providers = [(module, info)] if info is not None else []
    if not providers:
        # co_filename uses the original module spelling. Frozen registries
        # can register that source under another name; use their own origname
        # field, never a hand-maintained importlib/stdlib alias table.
        for registered in _imp._frozen_module_names():
            candidate_info = _imp.find_frozen(registered)
            if candidate_info is not None and candidate_info[2] == module:
                providers.append((registered, candidate_info))
    if not providers:
        return None, None, 'FROZEN_MODULE_NOT_PRESENT_IN_CURRENT_RUNTIME'
    locations = {}
    for registered, (_, is_package, original_name) in providers:
        filename, _ = FrozenImporter._resolve_filename(original_name, registered, is_package)
        if filename is not None:
            locations.setdefault((filename, original_name, is_package), []).append(registered)
    if not locations:
        return None, None, 'OFFICIAL_FROZEN_SOURCE_LOCATION_UNAVAILABLE'
    if len(locations) != 1:
        return None, None, 'OFFICIAL_FROZEN_SOURCE_METADATA_AMBIGUOUS'
    (filename, original_name, is_package), registered_names = next(iter(locations.items()))
    return Path(filename), dict(kind='OFFICIAL_FROZEN_METADATA', module=module,
        original_name=original_name, is_package=is_package, registered_names=registered_names,
        stdlib_dir=getattr(sys, '_stdlib_dir', None),
        resolver='CPYTHON_FROZEN_IMPORTER_RESOLVE_FILENAME'), None


def _paths(root, maximum):
    pending = [((), root)]; count = 0
    while pending:
        path, code = pending.pop(); count += 1
        if count > maximum: raise ValueError('compiler child traversal budget exceeded')
        yield path, code
        for ordinal in range(len(code.co_consts)-1, -1, -1):
            child = code.co_consts[ordinal]
            if type(child) is CodeType: pending.append(((*path, ordinal), child))


def match_external_sources(captures, known, out, *, max_file_bytes=1_000_000,
        max_total_bytes=8_000_000, max_attempts=512, max_seconds=60,
        max_sources=64, max_captures=10_000, max_code_objects=20_000):
    """Snapshot bounded current sources and retain every exact replay match.

    A group owns one raw source and root descriptor; all compatible flags and
    optimization levels remain alternatives. ``analysis_recipe`` is merely
    one representation for later source lowering, never an observed request.
    """
    started = time.monotonic(); out = Path(out).absolute()
    if out.resolve() != out or out.exists(): raise ValueError('fresh canonical external source output required')
    limits = dict(max_file_bytes=max_file_bytes, max_total_bytes=max_total_bytes, max_attempts=max_attempts,
        max_seconds=max_seconds, max_sources=max_sources, max_captures=max_captures, max_code_objects=max_code_objects)
    if (any(type(value) is not int or value < 1 for name,value in limits.items() if name != 'max_seconds')
            or type(max_seconds) not in (int,float) or max_seconds <= 0
            or type(captures) is not tuple or len(captures) > max_captures
            or any(type(capture) is not CodeCapture for capture in captures)):
        raise ValueError('bounded typed code captures and positive analysis budgets required')
    known = set(known)
    selected = tuple(c for c in captures if (c.process_id,c.code.key) not in known)
    by_filename = defaultdict(list)
    for capture in selected: by_filename[capture.code.filename].append(capture)
    _durable_mkdir(out); _durable_mkdir(out/'sources')
    capture_raw = _json(encode(captures)); _durable_bytes(out/'captures.json', capture_raw, replace=False)
    capture_receipt = _receipt(out/'captures.json', capture_raw)
    sources = {}; matches = []; groups = {}; reasons = {}; guards = {}; read_cache = {}
    attempts = spent = 0; errors = Counter(); complete = True; budget_reason = None
    future = supported_future_flag_mask()
    for filename, wanted in sorted(by_filename.items()):
        if budget_reason is not None:
            for c in wanted: reasons[c.process_id,c.code.key] = budget_reason
            continue
        candidate, discovery, reason = _source_candidate(filename)
        if candidate is None:
            for c in wanted: reasons[c.process_id,c.code.key] = reason
            continue
        try:
            physical = candidate.resolve(strict=True)
            if not physical.is_file(): raise ValueError('SOURCE_CANDIDATE_NOT_A_REGULAR_FILE')
            if physical not in read_cache:
                if len(read_cache) >= max_sources: raise ValueError('SOURCE_COUNT_BUDGET_EXHAUSTED')
                before = _stamp(physical)
                if before[2] > max_file_bytes: raise ValueError('SOURCE_FILE_BYTE_BUDGET_EXHAUSTED')
                if spent+before[2] > max_total_bytes: raise ValueError('SOURCE_TOTAL_BYTE_BUDGET_EXHAUSTED')
                with physical.open('rb') as stream: raw = stream.read(max_file_bytes+1)
                if _stamp(physical) != before or len(raw) != before[2]: raise ValueError('SOURCE_CHANGED_DURING_READ')
                read_cache[physical] = raw; spent += len(raw)
            raw = read_cache[physical]
            if candidate.resolve(strict=True) != physical: raise ValueError('SOURCE_PATH_TARGET_CHANGED')
        except (OSError, ValueError) as error:
            reason = str(error)
            if 'BUDGET_EXHAUSTED' in reason: complete = False
            for c in wanted: reasons[c.process_id,c.code.key] = reason
            continue
        original = _receipt(candidate, raw)
        guards[candidate] = physical, _stamp(physical)
        raw_sha = sha256(raw).hexdigest(); relative = 'sources/'+raw_sha+'.py'
        if not (out/relative).exists(): _durable_bytes(out/relative, raw, replace=False)
        source_id = sha256(_json((str(candidate),filename,raw_sha))).hexdigest()
        sources[source_id] = dict(original=original, physical_path=str(physical),
            snapshot=dict(path=relative, bytes=len(raw), sha256=raw_sha), discovery=discovery)
        # Necessary metadata cheaply rejects unrelated children. Only complete
        # structural descriptor equality below can create a correspondence.
        lookup = defaultdict(list)
        for capture in wanted:
            code = capture.code
            lookup[code.filename,code.qualname,code.first_line,code.flags].append(capture)
        flags = sorted({0, *(c.code.flags & future for c in wanted)})
        source_groups = {}
        for flags_value in flags:
            for optimize in (0,1,2):
                if attempts >= max_attempts or time.monotonic()-started > max_seconds:
                    complete = False; budget_reason = 'COMPILER_REPLAY_BUDGET_EXHAUSTED'; break
                attempts += 1
                recipe = dict(filename=filename, mode='exec', flags=flags_value, dont_inherit=True, optimize=optimize)
                try:
                    root = compile(raw, filename, 'exec', flags=flags_value, dont_inherit=True, optimize=optimize)
                    found = []
                    for const_path, child in _paths(root, max_code_objects):
                        possible = lookup.get((child.co_filename,child.co_qualname,child.co_firstlineno,child.co_flags),())
                        if not possible: continue
                        descriptor = describe_code(child)
                        for capture in possible:
                            if descriptor == encode(capture.code):
                                found.append(dict(capture=encode(capture), constant_path=list(const_path)))
                except (SyntaxError, ValueError, TypeError, OverflowError, RecursionError) as error:
                    errors[type(error).__name__] += 1; continue
                if not found: continue
                root_code = describe_code(root)
                key = sha256(_json((source_id,root_code))).hexdigest()
                if key not in source_groups:
                    source_groups[key] = dict(group=key, source=source_id, analysis_recipe=recipe,
                        root_code=root_code, matched_captures=found)
                    groups[key] = dict(compatible_recipes=[])
                elif source_groups[key]['matched_captures'] != found:
                    raise ValueError('equal root descriptors have conflicting source correspondence paths')
                groups[key]['compatible_recipes'].append(recipe)
            if budget_reason is not None: break
        matches.extend(source_groups.values())
        for capture in wanted:
            reasons[capture.process_id,capture.code.key] = (budget_reason
                or 'NO_FULL_CODE_DESCRIPTOR_MATCH_IN_BOUNDED_CURRENT_SOURCE_REPLAY')
    matched = {(entry['capture']['process_id'],entry['capture']['code']['key'])
        for match in matches for entry in match['matched_captures']}
    unmatched = [dict(capture=encode(capture), reason=reasons.get((capture.process_id,capture.code.key),
        'NO_FULL_CODE_DESCRIPTOR_MATCH_IN_BOUNDED_CURRENT_SOURCE_REPLAY'))
        for capture in selected if (capture.process_id,capture.code.key) not in matched]
    for original,(physical,stamp) in guards.items():
        if original.resolve(strict=True) != physical or _stamp(physical) != stamp:
            raise ValueError('external source changed during matching')
    report = dict(schema=SCHEMA, schema_version=1, python=sys.version,
        implementation_sha256=_producer(), captures=capture_receipt, sources=sources,
        matches=matches, groups=groups, unmatched=unmatched, limits=limits,
        search_complete=complete, search_domain=dict(mode='exec', optimize=[0,1,2],
            flags='ZERO_OR_CAPTURED_FUTURE_FLAGS', dont_inherit=True),
        capture_contract='CALLER_SUPPLIED_TYPED_CODE_REFERENCES_NOT_FRAME_ENTRY_PROOF',
        counts=dict(captures=len(captures), known=len(captures)-len(selected), requested=len(selected),
            matched_captures=len(matched), unmatched_captures=len(unmatched), source_files=len(read_cache),
            source_representations=len(sources), source_bytes=spent, replay_attempts=attempts,
            groups=len(groups), compatible_recipes=sum(len(g['compatible_recipes']) for g in groups.values()),
            failed_compiles=dict(errors)), **{name:False for name in _FALSE}, seconds=time.monotonic()-started)
    _durable_bytes(out/'result.json', _json(report), replace=False)
    ExternalSourceMatches(out)
    return report


class ExternalSourceMatches:
    """Receipt-bound current-source candidates, with no compiler-event claims."""
    def __init__(self, path):
        self.path = Path(path).absolute()
        if self.path.resolve() != self.path: raise ValueError('canonical external source report required')
        self.raw = (self.path/'result.json').read_bytes(); self.report = report = json.loads(self.raw)
        if ((report['schema'],report['schema_version']) != (SCHEMA,1) or report['python'] != sys.version
                or report['implementation_sha256'] != _producer()
                or any(report[name] is not False for name in _FALSE)):
            raise ValueError('external source report producer/runtime/contract differs')
        self._guards = {}; self._parents = {self.path/'result.json':self.raw}
        self.captures = decode(tuple[CodeCapture,...],json.loads(self._admit(report['captures'])))
        self.sources, self.matches, self.groups = report['sources'], report['matches'], report['groups']
        for source in self.sources.values():
            self._admit(source['original'], physical=source['physical_path'])
            self._admit(self._snapshot(source))
        capture_set = set(self.captures)
        for match in self.matches:
            if match['source'] not in self.sources or match['analysis_recipe'] not in self.groups[match['group']]['compatible_recipes']:
                raise ValueError('external source match has no retained source/recipe group')
            for entry in match['matched_captures']:
                if decode(CodeCapture,entry['capture']) not in capture_set:
                    raise ValueError('external source match references an absent typed capture')
        self.check()

    def _snapshot(self, source):
        receipt = source['snapshot']; relative = Path(receipt['path'])
        if relative.is_absolute() or '..' in relative.parts:
            raise ValueError('external source snapshot escapes its report')
        return dict(receipt,path=str(self.path/relative))

    def _admit(self, receipt, *, physical=None):
        path = Path(receipt['path']); resolved = path.resolve(strict=True)
        if not path.is_absolute() or physical is not None and resolved != Path(physical):
            raise ValueError('external source receipt path target differs')
        before = _stamp(resolved)
        with resolved.open('rb') as stream: raw = stream.read(receipt['bytes']+1)
        if (_stamp(resolved) != before or len(raw) != receipt['bytes'] or sha256(raw).hexdigest() != receipt['sha256']):
            raise ValueError('external source byte receipt differs')
        self._guards[path] = resolved,before
        return raw

    def read_source(self, source_id):
        self.check(); receipt = self._snapshot(self.sources[source_id])
        return self._admit(receipt)

    def check(self):
        if any(path.read_bytes() != raw for path,raw in self._parents.items()) or json.loads(self.raw) != self.report:
            raise ValueError('external source report changed')
        for path,(resolved,stamp) in self._guards.items():
            if path.resolve(strict=True) != resolved or _stamp(resolved) != stamp:
                raise ValueError('external source material changed')
        return len(self._parents)+len(self._guards)

    def guard_stamps(self):
        self.check()
        return {**{resolved:stamp for resolved,stamp in self._guards.values()},
            **{path:_stamp(path) for path in self._parents}}
