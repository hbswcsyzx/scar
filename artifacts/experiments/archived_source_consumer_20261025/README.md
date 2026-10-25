# Archived CP2 consumption

One existing published 92-operation body was read through public
InventoryPartitions.typed_body with exact archived text while all reads of
live LeWM source were forbidden. It passed in 8.143 seconds; no target
execution, compilation, lowering, publisher, composer or runtime binder ran.
The exact four current source files are recorded in receipt.json.

Composer now forwards an optional source_texts argument. SourceBodyAccess
selects archived text before reading a CP2; CP1 keeps its previous path.
Those two forwarding changes are implemented; this check exercises the CP2
reader rather than claiming a fresh composer or SBA runtime execution.

The original publication gate's FAILED_ENV_FREEZE is unchanged. Static
published body count is 846; the latest full runtime connection remains 843.
