Source-only return/signature review before resume02, without helper execution.

| Called helper | Actual source contract | Benchmark use |
| --- | --- | --- |
| `program_lowering._canonical(document)` (line556) | `json.dumps(...ensure_ascii=False,sort_keys=True,separators,allow_nan=False)` returns **str**, not bytes | Observer encodes UTF-8 only for SHA/byte count, returns original str unchanged; ordinary codec equality preserved |
| `SourceProgram.read_structure(document, *, max_operations, source_texts, module_code_evidence)` (line380) | Delegates from_dict verification=STRUCTURE, returns SourceProgram or raises | Timed public call; same exact archive text, no owner/runtime proof |
| `inventory_partitions._read_receipt(path, *, limit)` (line42) | `(document:dict, receipt:dict)`; reads binary payload, UTF-8 strict JSON, SHA fields/byte counts | One normal SP5 read per child; exact original physical+decoded receipts checked |
| `CodeWitnessStore.text(snapshot)` (line175) | Source artifact bytes decoded UTF-8, fingerprint checked; returns **str** | Readonly archive only, passed directly to source_texts; no live-source fallback |
| `CodeWitnessStore.receipt()` (line352) | Reads immutable manifest and returns **dict** | Exact original store receipt compared |
| Local runner `canonical(value)` | UTF-8 encoded json.dumps, returns **bytes** | Small output writing only; distinct from program_lowering helper |
| Local runner `receipt(path)` | Binary file read; returns dict(path,SHA,bytes) | Pin verification, not source authority |
| `subprocess.run(...)` | CompletedProcess; child stdout/stderr retained | Parent checks actual returncode before reading successful results |

Original9750 actualexit1 at observer str hashing was a benchmark harness error, before complete structure acceptance. New hashing uses `encoded = data.encode('utf-8')`, SHA(encoded), len(encoded), followed by return data. No normalized value changes, extra to_dict/serialize, validator bypass or production changes. Parent/family counting and pstats output operate on byte buffers or primitive function statistics as declared; no Tensor values/locals are materialized or emitted.
