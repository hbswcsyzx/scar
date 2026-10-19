# Immutable D6 attempts

- `first-red`: 24 failed,1.41s; 19 missing public copy-consumer API,5 genuine
  typed ordinary CALL packet carriers rejected by core. 788 sources unchanged,
  SHA76dbd0f026a0a806270d48f99fc382b27b6785d6d11ab2560852697107206e18.
- `implementation-01`:38 passed/2 failed,3.26s; mixed return lost pre-call
  proof and recursion lost internal call anchor. 790 sources unchanged,
  SHA79222692df45ad8184fd70adc6910bd4f5392de556c10f573c384eaa71f002d6.
- `implementation-02`:40 passed,3.19s;790 stable sources,
  SHA320bd1d49d8e33a5a34dc766785a5085864bc6a8006c1b5b3f618a7c0112a1d1.
  This does not certify subsequent reviewed cache/budget fixes.
- `review-regression`:50 passed,4.05s;793 stable sources,
  SHAc425ed1e8d5ea6a80ecc286ed5bfec39c0f68a0a856ad64e05961dfd3ba38ffc.
  Includes34 independently authored new cases and16 existing control cases.
- `accepted-final` (original attempt name, FAILED):1549 passed/2 failed,
  153.11s;793 unchanged sources at c425ed1e. Delaying full protocol validation
  exposed a real dependency: lifecycle terminal derivation reads NoEntry rows.
  Two old malformed-route negatives raised ValueError before a rejection
  report. Old test inputs stayed unchanged; the failed directory is retained.
- `no-entry-regression`:86 passed,4.53s;793 unchanged sources,
  SHA2f3580d5b720a26ebe9f6a9b58e9cba2f1671d92b983b7866f265688913d2d49.
  Structural NoEntry admission now precedes lifecycle derivation; full payload
  validation still runs with the prepared return-aware context. No unresolved
  payload grants lifecycle seeds.
- `verified-final`: final unified affected selection includes every old1501
  case, the new34 and the added existing16. Actual1551 passed/0 failure/error/
  skipped;151.93s pytest,152.8156958548352s runner.793 stable sources,
  SHA2f3580d5b720a26ebe9f6a9b58e9cba2f1671d92b983b7866f265688913d2d49.
  Its immutable result/JUnit/source registry is authoritative.

Source-read issues are labeled as such in independent-review.md. Existing
test/fixture inputs and case identities are unchanged, with no migrations.
All commands use the existing conda lewm; measured pytest durations are not
program profiling/benchmark or performance speedup.
