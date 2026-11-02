"""Source-only declarations remain available without eagerly decoding their IR."""
import json

from scar.analysis.static_program import build_static_program
from scar.analysis.static_calls import StaticCallBudget, StaticCallSession, build_static_call_links


def test_source_only_seed_preserves_scope_and_demanded_definition_material(tmp_path):
    source = tmp_path / 'source'; source.mkdir()
    marker = tmp_path / 'target-executed'
    (source / 'provider.py').write_text('def identity(value):\n    return value\n')
    (source / 'caller.py').write_text('import provider\nresult = provider.identity(7)\n')
    (source / 'unused.py').write_text('from pathlib import Path\nPath(' + repr(str(marker)) + ').touch()\n')
    (source / 'declaration.pyi').write_text('def native(value: int) -> int: ...\n')
    model = tmp_path / 'model'
    manifest = build_static_program(source, out=model, jobs=1, phase='graph')
    before = (model / 'manifest.json').read_bytes()
    publication = build_static_call_links(model, tmp_path / 'relations')
    counts = publication['counts']
    assert counts['source_units'] == counts['source_units_enumerated'] == 4
    assert counts['source_only_units_deferred'] == 3 and counts['declaration_only_units'] == 1
    assert counts['bodies_without_artifact'] == counts['source_lexical_entries']
    assert counts.get('unit_context_load_attempts', 0) == 0
    assert publication['complete'] and not publication['scope']['whole_program_model_complete']
    assert any(f['kind'] == 'CANONICAL_BODIES_NOT_BUILT' for f in publication['frontiers'])
    full_context_bytes = sum(d['bytes'] + d['decoded_bytes'] for u in manifest['units']
        for name, d in u['artifacts'].items() if name in ('source', 'lexical', 'semantic', 'semantics', 'control'))
    assert publication['measurements']['input_bytes'] < len(before) + full_context_bytes
    assert publication['input_scope']['body_artifacts'] == 0
    assert publication['input_scope']['source_only_units'] == 3
    assert publication['input_scope']['cold_seed_input_bytes'] == publication['measurements']['input_bytes']
    # A missing executable module cannot supply a fabricated namespace. Its
    # source and signatures remain available when a real dependency asks.
    with StaticCallSession(model, out=tmp_path / 'demanded', budget=StaticCallBudget()) as session:
        assert not list(session._module_dependencies().module_bodies('provider'))
        assert session.counts['unit_context_load_attempts'] == 0
        number = next(i for i, u in enumerate(session.units) if u['path'].endswith('/provider.py'))
        context = session._unit(number)
        assert any(entry['name'] == 'identity' for _, _, entry, _ in context.definitions.values())
        assert session.counts['unit_context_load_attempts'] == 1
        assert session._unit(number) is context and session.counts['unit_cache_hits'] == 1
    assert (model / 'manifest.json').read_bytes() == before
    assert len(json.loads(before)['units']) == 4 and not marker.exists()
