# Public shared-body store and local Region query

The public store command processed two original source-publication requests in
6.737s, exit0, without importing or executing the target. One shared context and
two independent bodies occupy2,736,372B versus5,153,469B for the original SP5s.
Immutable content files use atomic publishing; no central writable graph table.

The public Region query of the first fragment completed exit0/2.924s, reading
172,894 stored /1,930,477 decoded bytes. Its original graph view equals the
legacy SP5 view. It reads neither shared context nor old full SP5 and grants
only typed core structure. Normal source validation uses SourceContextSession.
Writer/query costs are separate; none are workload optimization speedups.

Only the first two of161 publication requests were packed here. Existing
publisher/catalog migration and whole-program modeling remain OPEN. Source
fragments preserve exact original IDs, origins and declared decoded identities.
