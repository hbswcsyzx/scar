# Explicit maximum-reader-version assertions

D1 adds Program23 while preserving old 1–22 emission/decoding bytes. Before
the first product test, root updates only twelve existing assertions of the
current reader's maximum `SCHEMA_VERSION` from 22 to 23. Their original case
IDs, old graph inputs, wire-version expectations, roundtrip checks, old
fixtures and independent old-encoder oracles remain unchanged. This is a
declared test migration, not a measured old-product failure or a waived test.

Files: program resumption, protocol, exception-match, admission, literal,
no-body, lookup-fallback, driver, publication, state-address, session-release
codecs and lifecycle-composition codec. The new v22 independent oracle still
asserts maximum22 inside its immutable 0bbc623 archive child and v22 emitted
wire. It is deliberately not updated.

The first full affected selection returned 1389P/4F (stable741-source digest
9a9751344b85d23061055fb50b6512e8b04bfde6d88bcde3dec01a766465a5b7).
All four failures are further closed-vocabulary/version migrations omitted
from the initial migration; no product change is made to resolve them:

- Keep the exact PROTOCOL_BINDING_TYPES equality assertion, adding the one
  new canonical AwaitBodyLink class explicitly (not relaxing to a subset).
- Future-version parameters move23->24 in method-lookup, exception-match and
  lookup-fallback codec tests. Unsupported-version and boolean rejection
  messages remain strict. Their three case IDs therefore migrate `[23]` to
  `[24]` explicitly. New Program23 tests independently reject v23 without its
  capability and reject attempts to smuggle new capability into old schemas.

The archive checker verifies only these exact edits plus the twelve maximum
assertions, and normalizes precisely those three historical case IDs. It
records 1305 unchanged case identities plus three explicit identity
migrations, retaining all1308 prior obligations.
