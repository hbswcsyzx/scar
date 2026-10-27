# Finite review: failure source and caller continuation

Base2c427b7b2923ac6e177b4ecac2200aa25ea31fa0. Root owns products, serial
execution, reports and Git. A/C own only new fixtures; B owns only new tests.
Every author froze before root ran interpreters. No reviewer ran tests/probes/
compile or Git, and no old test, fixture, contract, codec or archive was changed.

## Contract review before implementation

All three reviews separated the internal failure-to-acquisition bridge from
caller cleanup. acquisition RAISE is immutable; caller Return cannot select
acquisition NORMAL. A qualification branch is control, not a packet producer.
The actual constructor, packet definition and exception/traceback Uses are
separate original records. B accepted frozen plan3cba3699... before authoring.

## Findings and finite disposition

- Root's first static run reproduced a new-test API error, not a product
  rejection: ValueKind.PROTOCOL does not exist. B corrected only that assertion
  to ProtocolValueType/ProtocolValueKind.EXCEPTION_PACKET. The same three
  cases then reached the product's missing source_result field. All three
  supplied core/full graphs were valid, old issues empty.
- A found that structured own paths with empty helper terminals bypassed the
  source consumer bindings. Root added path-level mandatory checks and status/
  issues, with no duplicate helper responsibility. B's independent same-type
  wrong-consumer metadata case passed and required the specific failure code.
- A found a paid ownership scan was preceded by an unmetered Invoke result
  scan. Root charged the optional shared-budget path before the zip and passed
  the same shared budget through terminal/consumer and state result decoding.
  Default callers not providing shared retain their legacy behavior. A's final
  source-only review closed those two concrete findings, not the full H group.
- C reviewed exact own-result ownership: actual transfer target, original
  CompletionResult, full typed slot and matching landing formal/ValueOccurrence.
  Same activation is insufficient; forwarded/sibling values do not match.
  Missing helper association cannot be repaired by a local caller continuation.
- C reviewed actual qualification packet lookup through this helper's path;
  constructor, own packet result and exact exception/traceback Uses and values
  remain separate. Missing capture stays PARTIAL. No budget reset was found.
- B's final review found no new finite blocker: original keys/source R/full
  slots, helper delivery, source consumers and current caller completion remain
  separate, with UNKNOWN/truncation explicit. The actual final regression is
  still required; reviewer acceptance does not grant execution proof.

## Frozen author files

| File | SHA256 |
| --- | --- |
| tests/fixtures/program_await_failure_cleanup_graphs.py |6f124f5cc2e8edbaf12be54c8319aef73bad98226abebe9dfdd0789e6896c6ce |
| tests/fixtures/execution_await_failure_cleanup_graphs.py |60d13947cbbaaf5112b989f93af18bf5b82dc326647c86aca28cc23f3f616c8c |
| tests/unit/test_program_await_failure_cleanup.py |355b250564b7b6b396679b83e49c7a55eb1305c5d99d39d6432745412a267465 |
| tests/unit/test_execution_await_failure_cleanup.py |7fc6306db827eda93fb39b181a0d57f86561296f34a7a447b5258b248d57ca42 |

## Final source-only reviewed product bytes

| File under scar/ir/ | SHA256 |
| --- | --- |
| program/await_failures.py |16ed0d6021ac070da16d7a3a144bc07684d62dff36833382812e02df718b7f69 |
| execution/completion_continuations.py |9e3756c1253d93dc6de282e7db575b05f0ac6cd532837c83c5071faf8691dd37 |
| execution/await_links.py |b6fb80b5c6891671629649cdd86dfc9e09f4b042cd4eeec9ce4db9bfbf044da9 |
| execution/await_outcome_evidence.py |654aef9bec003c0cf58ee77b19b62d9137bf3632f0a59a099698fe8f4a151bbc |
| execution/await_outcomes.py |2bd2cfb9cb9341b60d879603177e86dae72d8fc83f5c696a30e8e72d6b973fb0 |

No complete A–H/16/P5/M2, automatic source recovery, native runtime, tensor
identity, transformation or LeWM performance claim follows from this review.
