# S1 state-address records author receipt

Implementation snapshot: `805c670a12ea15cf12b32395180c8fcd954beda2`.
This receipt covers only the six owned records, validator, fixture, and unit-test files listed below. It does not claim source recovery, alias disjointness, or runtime effect verification.

## Focused attempts

All attempts used the `lewm` conda environment, Python 3.14.7, `PYTHONDONTWRITEBYTECODE=1`, and `PYTHONPATH=.`. The runner and per-attempt command, stdout, stderr, JUnit, and source-before/source-after manifests are retained under this directory.

| Attempt | Result | Development correction |
| --- | --- | --- |
| `attempt001` | Exit 1; 6 passed, 7 failed of 13 | The fixture omitted `ExistingAccess`, causing six construction failures. The remaining assertion expected selector operands in the wrong order and omitted a repeated key. These were test/fixture errors. |
| `attempt002` | Exit 1; 11 passed, 3 failed of 14 | The test omitted the `InvokeStateOperand` import; its mode-negative case changed an effect to RW while the original summary was already RW; and the invoke-argument mutation targeted the wrong fixture Use. The tests/fixture were corrected to exercise the intended checks. |
| `attempt003` | Exit 0; 14 passed | First passing baseline for records and structural ownership/mode checks. |
| `attempt004` | Exit 0; 15 passed | Added a negative case proving distinct INVOKE state Uses cannot declare two refinements for the same derived `(operation, LocationID)` carrier. |
| `attempt005` | Exit 0; 15 passed | Final focused run after aligning `ResourceOwner` scope with the existing resource validator: a requirement may be owned by the exact operation or a lexical ancestor region. |

The final command was:

```sh
source /home/zyf/miniconda3/etc/profile.d/conda.sh
conda activate lewm
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. python artifacts/experiments/b1_call_operands/model_state_locations/focus.py address_records tests/unit/test_program_state_address_records.py tests/unit/test_program_state_address_validation.py
```

`attempt005` reports 15 passed in 0.45 seconds (runner duration 1.185 seconds). No full suite was run by this owner.

## Owned files and final SHA-256

| File | SHA-256 |
| --- | --- |
| `scar/ir/program/state_modes.py` | `8d841907f306ee66996b9b45b3c7b5a6a4c799361e818851dff66534e0ee519e` |
| `scar/ir/program/state_addresses.py` | `6ff4052771e4c92cf248f298131037f9a25a5bda8059e1547da44410d3577b61` |
| `scar/ir/program/state_address_validation.py` | `03c1d4f8b3e9fe991f902a4e775051b2fbc8f048b49e4758fb3431833937a096` |
| `tests/fixtures/program_state_addresses.py` | `606edb185da3499a27235bfca566f7c314f936d7567b28c3440e8c940e121eb0` |
| `tests/unit/test_program_state_address_records.py` | `5708346c2c1e3e302f9c2d5cc740bd68ac16f7d93c31e5009ce11b12282220f1` |
| `tests/unit/test_program_state_address_validation.py` | `6906462abe64cd0ed6c5805c21672d40919c20241f0195a6bf482f6d813ab778` |

The records expose exact typed owner/selector variants, retain repeated owned Uses in path order, and preserve the original single `AccessMode` enum. Validation checks original owned Uses, access mode coverage, the non-None reference envelope, resource requirement ownership, exact INVOKE state/input ports and `STATE_CONTENT` role, full-overwrite restrictions, and one refinement per derived carrier. Original state SSA is unchanged. Typed selectors do not refine legacy footprint geometry, establish alias separation, or certify source/native behavior; those remain explicit unverified conditions for later queries.
