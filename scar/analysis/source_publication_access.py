"""Open an existing qualified source publication with its pinned archives.

This only assembles ordinary readers. It neither publishes another graph nor
turns stored status fields into source or runtime qualification.
"""
from __future__ import annotations

from pathlib import Path
import re

from scar.analysis.code_witness import CodeWitnessBudget
from scar.analysis.compiler_witness_archives import CompilerArchiveBudget, CompilerWitnessArchives
from scar.analysis.program_composition import CompositionIndex, _read
from scar.analysis.source_attachments import SourceAttachmentBudget
from scar.ir.program.call_edges import CallEdgeBudget


def open_source_publication(path, *, expected_sha256,
                            call_budget=CallEdgeBudget(),
                            max_input_bytes=512_000_000,
                            max_record_bytes=128_000_000,
                            max_programs=256,
                            max_operations_per_body=10_000,
                            max_selected_decode_bytes=8_000_000_000,
                            max_context_seconds=1800):
    """Read the complete publication through the existing compact consumer.

    The root's SHA is required. Archive paths and their exact receipts come
    from that root; every archive is opened read-only. Caller ceilings bound
    the source catalog and archives as well as the original body reader.
    """
    if (type(expected_sha256) is not str
            or re.fullmatch(r'[0-9a-f]{64}', expected_sha256) is None):
        raise ValueError('source publication requires its exact SHA256')
    if type(call_budget) is not CallEdgeBudget:
        raise TypeError('source publication requires a typed call budget')
    call_budget.__post_init__()
    if any(type(value) is not int or value <= 0 for value in (
            max_input_bytes, max_record_bytes, max_programs,
            max_operations_per_body, max_selected_decode_bytes, max_context_seconds)):
        raise ValueError('source publication ceilings must be positive integers')
    root = Path(path).absolute()
    document, receipt = _read(root, max_input_bytes)
    if (receipt['raw_sha256'] != expected_sha256
            or document.get('schema') != 'scar.source-entry-publication'
            or type(document.get('schema_version')) is not int
            or document['schema_version'] not in (1, 2, 3)):
        raise ValueError('source publication root receipt or schema differs')
    declarations = document['catalog_inputs']['archives']
    if type(declarations) is not list or not declarations:
        raise ValueError('source publication has no original compiler archives')
    archives = CompilerWitnessArchives(
        tuple((str(Path(row['path']).parent), row['sha256']) for row in declarations),
        store_budget=CodeWitnessBudget(
            max_compile_keys=call_budget.max_codes,
            max_source_files=call_budget.max_source_files,
            max_source_bytes=max_input_bytes,
            max_module_bytes=max_record_bytes,
            max_archive_bytes=max_selected_decode_bytes,
            max_manifest_bytes=max_record_bytes),
        budget=CompilerArchiveBudget(
            max_total_modules=call_budget.max_codes,
            max_total_sources=call_budget.max_source_files,
            max_declared_payload_bytes=max_selected_decode_bytes))
    if archives.receipts() != declarations:
        raise ValueError('source publication compiler archive receipts differ')
    return CompositionIndex.from_source_entry_publication(
        root, expected_sha256=expected_sha256, archives=archives,
        max_input_bytes=max_input_bytes, max_record_bytes=max_record_bytes,
        max_programs=max_programs, max_operations_per_body=max_operations_per_body,
        max_catalog_groups=call_budget.max_codes,
        max_catalog_entries=call_budget.max_codes,
        max_selected_decode_bytes=max_selected_decode_bytes,
        max_context_seconds=max_context_seconds,
        attachment_budget=SourceAttachmentBudget(
            max_report_bytes=max_input_bytes,
            max_files=call_budget.max_source_files,
            max_codes=call_budget.max_codes,
            max_artifact_bytes=max_selected_decode_bytes,
            max_record_bytes=max_record_bytes,
            cached_files=1))


__all__ = ['open_source_publication']
