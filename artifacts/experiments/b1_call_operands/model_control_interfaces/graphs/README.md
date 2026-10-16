# C0 control graph fixture test attempts

All runs used CPython from conda environment `lewm`, with bytecode writes disabled.

- Attempt 1 omitted `PYTHONPATH` for this isolated worktree and stopped during test collection (`ModuleNotFoundError: scar`). This was a runner setup error.
- Attempt 2 added `PYTHONPATH=/tmp/scar-structured-model-280qf4mi`; 13 tests passed and 3 failed. Two failures exposed fixture mistakes (an unused loop branch operand and an invalid direct-path condition). The third test expected the control-specific landing error even though core CFG validation correctly rejected the now-unreachable exit block first. These were test/fixture issues, not product defects.
- Attempt 3 ran the frozen owned test file with `PYTHONPATH` set and passed: 16 passed.

Commands and complete outputs are preserved in the adjacent log files. The tests cover structural declarations only; they do not prove source correspondence, execution of cleanup, exception unwinding, or runtime identity.
