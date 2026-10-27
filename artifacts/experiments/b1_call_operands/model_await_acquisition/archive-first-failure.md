# Archive checker initial execution

Root ran the checkpoint script with `--write` after the accepted1393 tests.
It exited1 at checkpoint.py line102 (`assert now == expected`) for
tests/unit/test_program_protocol_connection_records.py. No manifest was written
and no tests/workload were started.

The checker described the new AwaitBodyLink member but omitted the exact
continuation indentation change43->47 spaces present in the tested patch.
Root corrected only the archive expectation, retaining the tested source
bytes and its7f7e7d77… fingerprint. This is an archive-helper error, not a
product regression and not another test attempt.
