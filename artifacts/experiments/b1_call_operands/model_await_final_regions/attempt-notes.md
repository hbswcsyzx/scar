# Immutable attempts and actual attribution

All Python, pytest and probes were run by root serially in conda lewm. All
authors were frozen before each attempt. Commands, stdout/stderr, JUnit and
before/after Python source registries are retained per directory. No old
tests, fixtures, contracts or schema codecs were modified.

| Directory | Actual result | Source files / digest | Attribution |
| --- | --- | --- | --- |
| first-red | 16 failed; runner 11.275083060376346s | 798 / 6074058f4531f024017c8ddbd3db373dc68fc584652f34849007c3519acc16bf | Program/boundary missing implementation view; execution newly authored selector also selected the constructor consumer with the same actual, before reaching implementation checks. Author constrained it to the original requires_final_extraction consumer. |
| static-implementation-01 | 6 passed / 4 failed; runner 6.891986642032862s | 800 / 2e347e8b8c6d71860d07988a83bf7285b3e8f8fc2ac61ea98d6b6e19ddd50ea4 | Static path checks succeeded; four positive cases exposed missing explicit family value_identity_verified=False flag. Product added the False receipt. |
| whole-implementation-01 | 16 passed; runner 11.586281695403159s | 801 / 9401ad702e35598c193b98884491974ffadf7142abf8a465b91e56faaeced084 | Initial implementation, before independent boundary review. This green source is not the final source. |
| review-fixes-01 | 20 passed / 1 failed; runner 14.109717531129718s | 804 / dab8358446363fad219e4f7939e40f8237e6bbd2d6e8c5c3e8b77ca1b1745900 | Independent may-only input and two-terminal budget cases passed. One new execution negative fixture incorrectly took .id from an OperationOccurrenceID before product query. Author fixed only that selector, retaining assertion and case. |
| verified-final | 1572 passed / 0 failure/error/skip; pytest166.49s, runner167.4104013852775s | 804 / 63306959be2dcdd2bbfe83d4fe37146e93b466b213e770c71489876ec08b906c | All prior1551 exact JUnit identities plus21 independent new cases. Focused, not full regression or automatic source/runtime recovery. |

No attempt's source registry changed during its run. Source-review-only
corrections before first execution are not presented as reproduced runtime
product defects. The two new execution test mistakes were confined to newly
authored files; all previous baseline tests/fixtures stayed byte-identical.

The final archive separately requires original A-H partial-evidence selectors
to match final JUnit. closed=[] and all original16 groups/P5/M2 remain open.
No LeWM run, GPU profile, new backend, transformation or speedup is claimed.
