# Function Try: real-entry expansion

The retained20 Try entries (578 historical calls) have19 Name/tuple handler expressions,10 multiple/as handlers,8 cross-cleanup returns and1 break (counts overlap). No package/function/variable-name rule participates. The original4-entry gate remains PREPARED_NOT_RUN; new consumers never backdate its freeze.

P0 reuses `source_heap_lowering.expression_for_heap_target` and its exact SG/AST ownership bridge for the historically omitted `ExceptHandler.type`. Evaluate it only after exceptional entry, in source order, with the normal environment/current-world, lifetime and paired-failure rules. Do not mutate archived semantics or fabricate an old computational operation. The normal CodeWitness continues to bind the whole captured function/descriptor/source; AST literals/Names/tuple construction remain ordinary typed source operations.

P1 evaluates handler clauses in order under the saved caught context, keeps first-match control explicit, resumes the original packet only after all miss, and clears an actual fast-local as-name with None-store/delete on every selected-body completion. Mapping-module cleanup is reused as a contract, not substituted for function-local SSA. The core owns C0/C1 matching, packet/current state, pending freshness and restoration.

P2 routes Return/Break/Continue through the same pending/cleanup machinery before their original targets; the return reference and retained frame roots survive cleanup. Cleanup completion resumes/replaces the original pending, never returns early or guesses a traceback. Nested/combined constructs outside the20 observed shapes may remain precise frontiers until their proper composition exists.

Keep old defaults/wire contracts. The explicit Try capability is promoted to automatic high-level options only after ordinary source/CodeWitness reader acceptance, not by fixture count. Implement/commit P0, then P1, then P2; run one bounded normal archived20-entry batch after the complete changes. Existing originals/main/other frozen trees remain unchanged; no target/episode/backend/instruction compiler is involved.
