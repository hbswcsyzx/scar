# First archive replay: serialization error, not a test failure

After verified-final1572 passed, root ran the original checkpoint.py --write:
it verified source63306959...,804files, all prior1551 case identities, original
tests/fixtures/codecs/contracts and the two protected repositories, then wrote
the manifest successfully. The immediate --check returned exit1:

```text
File "checkpoint.py", line 132, in main
    assert record == json.loads(MANIFEST.read_text())
AssertionError
```

Cause: newly added A-H exact identity evidence was constructed as lists of
Python tuples. JSON serializes tuples as lists, so the logically equal replay
record was not equal under Python container equality. The source/test audit
and JUnit did not fail; the receipt comparison did.

The original verifier and first manifest are preserved byte-for-byte as
checkpoint-first-write.py / checkpoint-first-write.json. The verifier now
normalizes exact case identities to JSON lists before constructing the record.
A fresh checkpoint includes these originals and this note. No product or
test/fixture source was changed, and no pytest rerun was started for this fix.
