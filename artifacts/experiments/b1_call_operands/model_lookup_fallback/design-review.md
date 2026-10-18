# Lookup-fallback model decision

Base: 8585d7f2aa013896fa58c3759d540338b78d43a5. Frozen plan SHA:
1312d142011202ced4bd5210b2971adfec2e92b80737d49c6e8fe5825baa0c00.

Three independent source reviews compared a new lookup trigger with a narrow
independent binding. Root selected the existing protocol_bindings table plus
DelegateLookupFallback and NormalizedThrowSource. Lookup remains a zero-argument
operation without a request trigger; no producer, state or CFG is duplicated.

Independent anchors are E0 (whole injected packet), EL (lookup own RAISE) and
EM (matcher own RAISE). Raw arguments do not identify a normalized packet.
The branch and all actual own N/R completions determine paths; the attachment
does not provide a user-editable list of desired paths. All three sources and
each exact original edge/slot retain their namespaces.

The query reuses prepared source/copy/caller/CFG relations and the independent
consumer inventory. A private packet frontier query follows original positions,
owned Uses and edges with the same budget; callbacks, reevaluation and cycles
cannot imply absent consumers. C1 checks its actually consumed pending token;
unconsumed packs provide neither success nor contradiction. C1 dispatch and
source applicability of a finally override remain unproved boundaries.

Ordinary, dynamic and only-RAISE matcher cases preserve their actual result
sets. Fixed builtin enums and fact references are conditional declarations;
all native/runtime identity and transformation-authority flags remain false.

No LeWM-specific branch, detector, backend or rewrite is introduced. Original
F12–F24/X25–X27 remain sixteen OPEN groups. This checkpoint is not automatic
whole-program recovery or the complete P4/M0–M2 gate.
