Root-run bounded same-SP5 comparison; prepared, not executed.

```bash
bash /home/zyf/AAA/scar-worktrees/structured-program-model/artifacts/experiments/validation_primitive_compare_resume02_20261026/run.sh
```

Three isolated fresh subprocesses, once each: baseline without cProfile; candidate without cProfile; candidate with cProfile. They normally read the same original SP5 and exact source text from its original readonly CodeWitnessStore, and call public SourceProgram.read_structure with supported STRUCTURE+source_texts. There is no140s project/catalog reconstruction, no source/CFG check removal and no graph/runtime/CodeWitness qualification.

The baseline archive is exact Git old source f1c640… . Its SCAR module is compiled only for this explicitly marked benchmark; only old _record_errors bytecode is installed into the live validation module's existing globals, leaving type/schema plans, callers and every other check unchanged. The baseline override is reported, does not modify any production file and expires with its process. Current primitive fast-path remains the candidate.

Outputs compare hashes of bytes already made by the ordinary from_dict canonical result/input equality check. A tiny identical SHA observer adds no to_dict or serialization pass; its cost is included and separately recorded. Never compare old79.986s heavy cProfile to new clean time as speedup. New cProfile gives function/call aggregates; no Tensor values, locals, source text or model dumps are saved.

Combined budget480s/outer540s, AS8GiB, input512MB including actual source/control pin SHA and metadata/code/SP5 reads, output32MB. Parent shares remaining allowance with each child; no independent512MB per child. Python import I/O excluded as before. Existing gates, production and main index remain unchanged. No automatic recovery/retry.

Preparation01 stopped before freeze: main also changed source_frontend_worklist.py after53184. Its exact current bytes are pinned and it is explicitly forbidden from the comparison's imports; it is not a benchmark implementation change. The failed preparation metadata remains in prepare-failed01.

Original comparison session9750 actualexit1 is preserved: its SHA observer hashed program_lowering._canonical str directly. Resume02 only encodes that original str to UTF-8 for digest/byte count; it returns the exact original str to from_dict unchanged. Source/helper contracts are recorded in HELPER_CONTRACT.md. Original SP5/archive text, old f1 source, current2 source SHA, budgets and three subprocess scheme remain the same.
