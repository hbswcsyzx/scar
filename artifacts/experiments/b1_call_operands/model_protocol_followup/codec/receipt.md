# Program20 codec receipt

## Scope

Owned changes are limited to `scar/ir/program/codec.py`,
`scar/ir/program/protocol_connections.py`, the ten existing codec tests whose
assertion is the current maximum schema version, and
`tests/unit/test_program_method_lookup_codec.py`. Existing Program19 wire
assertions remain at 19. No Execution codec or old fixture bytes were changed.

The capability check is an exact scan for the four canonical delegated lookup
rules. It selects Program20 even when the independent input/consumer tables are
empty; the new regression checks that this graph round-trips as Program20 and
the public protocol query keeps missing-connection gaps. It does not infer
that the missing rows are complete.

## Focused tests

The exact command is preserved in each attempt's `command.json`; the runner was
invoked after sourcing conda and activating `lewm`, with
`PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=.`.

- `codec-attempt001`: collection failed before tests because pytest reserves
  the parametrized name `request`. The attempt is preserved with return code 2
  and unchanged source fingerprint `d5d86be065efab759377e14834fbb7713375bdbab0f8b9868d90691558c1d242`.
  The test parameter was renamed to `request_kind`.
- `codec-attempt002`: **387 passed** in 11.37 seconds across the new method
  codec test, ten max-version tests, Program connection codec, and connection
  records. Source fingerprint before and after was
  `fc5a4b495932dbc40cf798af908cb683d6dd7588e3e23d184526e16097bdd6b0`.

This was a bounded focused run, not a component or full-suite result.

## Independent Program19 oracle

The frozen v19 bytes were generated with the old encoder from commit
`7dd8c54b8d8cfdb3454b9f3b671f3412d1a914f0`, isolated from the current tree.
The retained source archive is `legacy-source-v19.tar`, SHA256
`a57e394498a8b485260b170b7e29ccfb235bfa699989c55bf7c677adf2ef6bf9`.
The oracle fixture is 44,484 bytes, SHA256
`57fe9feb47f5b186cb1b5c708c1eff56e54a61b43c597a6951a82719cfd0a5f6`; its
proof is adjacent. The old source check recorded Python 3.14.7, old codec
schema 19, and imports resolving inside the isolated tree. Generation attempts
001 and 002, commands, logs, and exit codes are retained.

Before deleting the extracted `legacy-src` tree, `verify-legacy-source.sh`
matched its sorted 157-file inventory and every archived file's SHA256 against
the tar. The verification output, command, and exit code are retained. GNU
`tar --compare` also reported UID/GID differences because the archived owner
and current extraction user differ; content hashes are the cleanup authority.
`cleanup-legacy-source.py` removed only the verified extracted directory and
retained the source tar, oracle, proof, and attempt logs.

## Final owned source hashes

- `scar/ir/program/codec.py`: `3753c0ac02667e5bc6e816f23e6c624393a04e4e86278aab01861a0f89d09d47`
- `scar/ir/program/protocol_connections.py`: `df7f63e6c8f7048b75c03c3942185d6603c295aed11953bae2679052aaef3759`
- `tests/unit/test_program_method_lookup_codec.py`: `d2a874eceb138d1936801302d33b473947d52a2ede209990857a52e945242776`

The run fingerprints contain exact hashes for all files in the focused source
set. Program20 codec support does not close the larger protocol-family gate or
claim native/runtime verification.
