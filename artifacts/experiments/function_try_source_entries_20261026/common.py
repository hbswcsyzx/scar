"""Ordinary source-entry inputs; reuse the already reviewed I/O observer only."""
from pathlib import Path
import hashlib, importlib.util, json, time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OLD = Path('/home/zyf/AAA/scar-worktrees/source209-model/artifacts/experiments/source209_model_20261026')
SPEC = importlib.util.spec_from_file_location('source209_io_observer', OLD / 'run.py')
OBSERVER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(OBSERVER)
canonical, need = OBSERVER.canonical, OBSERVER.need

def receipt(path):
    path = Path(path); data = path.read_bytes()
    return {'path': str(path.resolve()), 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}

def save(path, value):
    with Path(path).open('xb') as stream:
        stream.write(canonical(value) + b'\n')

def normal_inputs(config, observer):
    from scar.analysis.source_attachments import SourceAttachments, SourceAttachmentBudget
    from scar.analysis.code_witness import CodeWitnessBudget
    from scar.analysis.compiler_witness_archives import CompilerWitnessArchives, CompilerArchiveBudget
    from scar.analysis.source_entry_catalog import SourceEntryCatalog
    owner = SourceAttachments(config['continuation']['path'],
        expected_report_sha256=config['continuation']['sha256'], project_root=config['project_root'],
        budget=SourceAttachmentBudget(max_report_bytes=8_000_000, max_artifact_bytes=1_000_000_000,
                                     max_record_bytes=128_000_000, cached_files=2))
    archives = CompilerWitnessArchives(tuple((x['directory'], x['manifest']['sha256']) for x in config['archives']),
        store_budget=CodeWitnessBudget(max_compile_keys=94, max_source_files=94, max_source_bytes=8_000_000,
            max_module_bytes=16_000_000, max_archive_bytes=256_000_000, max_manifest_bytes=8_000_000),
        budget=CompilerArchiveBudget(max_archives=4, max_total_modules=256,
                                    max_total_sources=256, max_declared_payload_bytes=256_000_000))
    catalog = SourceEntryCatalog(admissions=(owner,), projects=(), archives=archives,
        max_groups=8192, max_candidates=8192, max_selected_decode_bytes=1_000_000_000)
    metadata = catalog.metadata()
    need(len(metadata['groups']) == 817 and metadata['entered_invocations'] == 100438
         and len(metadata['candidates']) == 243, 'full original source catalog denominators differ')
    return owner, archives, catalog, metadata

def worker_budget():
    from scar.analysis.source_frontend_worklist import SourceFrontendBudget
    return SourceFrontendBudget(max_catalog_files=256, max_catalog_bodies=8192, max_catalog_groups=8192,
        max_dispatch_bodies=4, max_source_files=4, max_source_bytes=1_000_000,
        max_operations_per_body=10_000, max_total_operations=40_000,
        max_record_bytes=128_000_000, max_output_bytes=512_000_000, max_elapsed_seconds=900)
