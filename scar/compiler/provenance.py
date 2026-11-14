"""Project retained F4 value origins through an existing optimizer mapping.

These are source references, not value versions, alias proofs or assertions
that equal provenance implies equal contents. No graph/source is reopened.
"""
from copy import deepcopy


def graph_value_sources(plan) -> dict[str, tuple[dict, ...]]:
    """Group original expression-bearing F4 records by optimized Expr ID.

    The original expression ID and complete unit/template/region/step/value
    references remain unchanged in each record. CSE/folding destinations come
    only from the retained source_operation_map; deleted destinations add no
    origin. Pure traversal and identity records never become value origins.
    Every current node is present, with an empty tuple when evidence is absent.
    """
    result = {node.id: [] for node in plan.region.nodes}
    mapping = plan.proof.get('source_operation_map', {})
    for origin in plan.region.source.origins:
        if not isinstance(origin, dict) or origin.get('kind') != 'original_f4':
            continue
        expression = origin.get('expression')
        if type(expression) is not str or not expression:
            continue
        if expression in mapping:
            destination = mapping[expression].get('optimized_node')
        else:
            destination = expression
        if destination in result:
            # Keep distinct original records and distinct destination IDs.
            # A caller annotating a schedule must not mutate the source plan.
            result[destination].append(deepcopy(origin))
    return {node: tuple(origins) for node, origins in result.items()}


__all__ = ['graph_value_sources']
