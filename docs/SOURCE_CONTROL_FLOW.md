# Source control-flow overlay v2

`SourceControlFlowGraph` is a bounded, source-replayed Python AST control
skeleton. It records statement order and selected structured branches as
typed nodes and edges. Its summary status is always `CONSTRUCTION_ONLY`; it
does not authorize source edits, prove effects, or certify a MOVE.

## Build and replay

Build the overlay with:

```python
graph = build_source_control_flow(semantic, source_semantics,
                                  sources=optional_decoded_source_map,
                                  budget=ControlFlowBudget())
```

When `sources` is omitted, the builder reads the local module files using
Python's source encoding rules. It never imports or executes target code.
Supplied source must cover exactly the local module paths. Source fingerprints
must match both the SemanticGraph and SourceSemanticsGraph snapshots, and the
source-semantics overlay is replay-validated before CFG construction.

`SourceControlFlowGraph.from_dict` and `from_json` perform strict structural
decoding and reference checks. They cannot establish that an edge or insertion
point came from source. Use `validate_source_control_flow(graph, semantic,
source_semantics, sources=..., verification_budget=...)` to rebuild and
compare the complete overlay against its source inputs.

An `InsertionPoint` identifies `ENTRY`, `BEFORE`, or `AFTER`, the actual suite,
the insertion node, and (for statement anchors) a source atom and source
version. A statement without a unique fingerprinted source atom can still
appear as a CFG gap node, but it gets no advertised insertion point.

## Modeled control and gaps

Module and synchronous function bodies get independent lexical-scope entries.
Same-scope `if` and `while`/`for` bodies get child-suite entries. An `if` always
keeps both branch edges; the builder does not evaluate predicates, including
literal `True` and `False`. Loops retain a body edge, zero-trip/else route,
backedge, and source-matched `break` and `continue` routes. A `return` goes to
the lexical function's normal exit and does not fall through to the next
statement.

Potentially raising statements get `MAY_RAISE` edges to the current suite's
exception exit. Explicit `raise` gets a `RAISE` edge. Child-suite exceptional
exits propagate to their parent suite. These edges are conservative structural
possibilities, not claims that an exception occurs.

`try`, `with`, async iteration, `yield`/`await`, class namespace execution,
`match`, and any statement outside the explicit supported subset get a typed
gap and an `UNKNOWN_CONTINUATION` edge. Their nested function bodies and class
methods may be retained as independent lexical scopes, but no execution edge
is inferred from a declaration, class namespace, or opaque control region to
those bodies. Unsupported suites do not borrow parent source order.

Branch truth, loop iteration count, user iteration, exception handlers,
context-manager suppression, class construction, asynchronous scheduling,
generator suspension, and dynamic dispatch are not interpreted. Gaps make
queries conservative. A `Scope.body` containment relation is never treated as
an executed CFG edge.

## Bounded queries

`query_reachability`, `query_dominance`, and `query_must_execute` revalidate the
mutable graph and consume a `ControlFlowBudget`. Budgets cover source bytes,
AST nodes, CFG nodes/edges, construction work, nesting, graph validation,
adjacency construction, gap traversal, and path-search work. Exhausted
construction raises `ValueError`; an exhausted query returns `UNKNOWN`.

Queries accept a `QueryMode`. `query_reachability` and `query_dominance` default
to `NORMAL`; `query_must_execute` defaults to `ALL_PATHS`. Callers evaluating
legality must pass `ALL_PATHS` explicitly:

- `NORMAL` excludes typed exception edges and asks about represented normal
  completion paths.
- `ALL_PATHS` includes exception edges and asks about both normal and
  exceptional routes represented by this overlay.

`CANDIDATE` means only that a structural property holds in the reconstructed
bounded graph. `UNKNOWN` means a gap, unresolved branch/loop feasibility,
possible exception, or budget limit prevents a complete answer. Query
validators (`validate_*_query`) recompute the structural request on the graph;
they do not replay source. Before relying on a candidate as source evidence,
call `validate_source_control_flow` once and bind that graph and source digest
to the caller's context. Decoding a report or carrying a stored status never
establishes source correspondence. None of these statuses approves a MOVE or
REUSE.
