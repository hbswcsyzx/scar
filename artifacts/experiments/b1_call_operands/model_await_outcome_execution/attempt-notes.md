# D5 actual attempts

Root alone runs Python/pytest in conda `lewm`; all source authors freeze during
each attempt. Every directory retains command, full log, JUnit and pre/post
source registries. Existing tests/fixtures stay byte-identical to287c906.

## first-execution

21F, no pass/error/skip, 781 sources; unchanged SHA
`9127cd346c6a64479e5c72c6199d9e1853205c6a2a57eca25169f06d33ccaf34`.
pytest17.71s / runner18.465017694979906s. Fifteen missing new query fields,
five new-test tuple-unpack errors, one real scope/call contamination:
an unassociated second helper activation raises qualification occurrence_count
from1 to2. Core graphs/captures were not rejected. New-test helper mistakes
are not counted as product defects. No product changes preceded this attempt.

## second-execution

16P5F, 783 sources; unchanged SHA
`4dafa15c4d270b9a14d4a2cbefe0033e81571bac92bd344817883c287761e079`.
pytest17.96s / runner18.736078574322164s. Dynamic outcome, exact-instance,
constructor/extractor RAISE, missing capture, source inventory and scope tests
now pass. Four failures are a new-test helper comparing static OperationID
to a supplied OperationOccurrenceID. One product failure: an empty partial
outcome enumeration under budget1 has no cursor. C corrected only the new
test's tuple/ID lookup helpers, without relaxing assertions or changing old
inputs. Root repairs the cursor separately.

Independent source review additionally found missing selected whole-packet
delivery support, late-budget treatment, static unselected-leg gap leakage,
quadratic support copying and unchecked intermediate recipe compatibility.
These are source-review findings, not measured runtime failures; subsequent
counterexamples and results are recorded separately.

## boundary-first-red

3F, 783 sources fixed at
`aafd69bec5bc7e0784ce8fd6c3e0423e000f3c2f4809ad8ef6e836c7d5ccca94`;
pytest2.57s / runner3.286437920294702s. These are product failures after valid
capture construction: late-budget inventory still claims complete, an inactive
extractor RAISE missing-adapter gap poisons actual NORMAL, and the independent
whole-packet P→terminal-packet Q edge is absent.

## third-execution

24P, 783 sources fixed at
`3e5b0c64af8d6781a73cd41fd3a40d7e2da87142fda3bb49ef706fd726262fed`;
pytest19.62s / runner20.436934138648212s. Subsequent exact-completion gap and
empty-capture fixes change sources; this green is not assigned to final bytes.

## accepted-focused (attempt name; failed, NOT accepted)

1499P2F, 783 sources fixed at
`e728d34d6545d8049164ad150a3020f2cbb5999adc8bb6ecd3acd083bae8fa95`;
pytest149.39s / runner150.32821291591972s. Both failures are preserved original
`test_execution_await_inventory` cases, budget1 with zero captures. New eager
static details/prepared-empty-job charging falsely marks an absent-capture
query as budget exhaustion. No old assertion/input is changed. The directory
retains its original attempted name and failed result; final acceptance uses
a different directory, not an overwritten log.

## empty-capture-regression

28P, 783 sources fixed at
`649f77199d3b7c0895b42160bee0af72c622231efeb91558c546b38e331fab72`;
pytest19.80s / runner20.615471832454205s. All24 new cases and the original4
uncaptured cases pass. Execution queries without any captured parent enumerate
original static keys but deliberately defer detailed static proof, recording
NOT_CHECKED plus a reason, not a fake budget failure. Static Program queries
retain normal eager derivation by default. Final raw-preparation counters were
added after this run and require the final unified source-bound acceptance.

## accepted-final

1501P/0F/0E/0skip, 783 sources unchanged before/after at
`c57e88db124d8b7f11409120acff3218339170bc63f8808030383e58a6e053c2`.
pytest147.30s / runner148.2066199425608s. This is the accepted affected focused
run on final bytes, including the explicit raw-preparation counters. Exact
old-case preservation, old input bytes, codec/frozen-contract bytes, protected
checkout state and prior archive hashes are checked by checkpoint.py separately.
No new tests or workloads are launched by that archive checker. All earlier
failed attempts remain; no attempt result or source registry was overwritten.
