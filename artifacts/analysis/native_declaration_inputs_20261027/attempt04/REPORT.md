# Native declaration mixed-status readback

This run normally read the first published native declaration fragment (256 original operation rows) and joined every native input port to the retained metadata index. It did not rebuild the declaration publication or rescan the raw ETO.

The full metadata source pass covered 310410 rows and 420444 leaves (47577389 stored and 1149320637 decoded bytes) in 62.146 s. The typed fragment reader consumed 256 operations and 687 input ports in 11.526 s. Total actual wall time was 74.124 s; terminal exit was 0. Normal core validation was valid with 0 issues.

All 687 input endpoints were returned: 285 exact metadata path matches and 402 explicit no-leaf frontiers; `NO_RETAINED_METADATA_ROW` was 0. Thus the mixed dispositions are not omissions.

## Independent disposition axes

`NativeInputIndex.finalize` sets a row-level canonical status separately from each metadata leaf's association. The valid pairs are: available boundary + `ASSOCIATED`, or unavailable boundary + either `ASSOCIATED` or `CANONICAL_NATIVE_BOUNDARY_UNAVAILABLE`. The old check compared those separate fields for equality. The earlier node-17 sample had unavailable/unavailable and therefore concealed that bug.

Matched pairs in this first fragment:

- `CANONICAL_BOUNDARY_AVAILABLE` / `ASSOCIATED`: 83
- `CANONICAL_NATIVE_BOUNDARY_UNAVAILABLE` / `CANONICAL_NATIVE_BOUNDARY_UNAVAILABLE`: 202

Unmatched inputs had these row-level statuses but no metadata leaf at their exact input path:

- `CANONICAL_BOUNDARY_AVAILABLE` / no leaf: 94
- `CANONICAL_NATIVE_BOUNDARY_UNAVAILABLE` / no leaf: 308

The new DTO records `prior_canonical_status` and `prior_metadata_association` independently. Its compatibility decoder accepts the previous wire shape and supplies `None` for the new field; a prior serialized row was decoded successfully. No content identity, alias, normal completion, or resource readiness is asserted.
