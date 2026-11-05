"""Query-local relations over a changing may-base graph.

No result survives a call: callers replay a query when a watched base point
changes. Source class IDs and base points are opaque hashable keys. ``bases``
returns ``(packed_or_open, ((point, values), ...))``; values use the existing
solver tuples. Only ``('class', id)`` is traversed. The exact token
``('external', 'builtins.object')`` is a closed terminal, not a source class.
"""


_NO_TARGET = object()
_OBJECT = ('external', 'builtins.object')


def _walk(cls, bases, watch, *, requested=_NO_TARGET, declared=None):
    """Return (target reached, any open/override/cycle), without path expansion.

    White/gray/black colors distinguish a shared DAG child from an ancestor
    cycle. Every expanded class is read once and every distinct base point is
    watched once. A requested class is a terminal proof and is not expanded;
    all base points of its parent have already been watched before returning.
    The watch callback records dependencies and must not mutate the provider.
    """
    if requested is not _NO_TARGET and cls == requested:
        return True, False
    colors = {}
    watched = set()
    stack = []
    incomplete = False

    def enter(current):
        nonlocal incomplete
        colors[current] = 1
        if declared is not None and declared(current):
            incomplete = True
        packed, groups = bases(current)
        incomplete |= bool(packed)
        children = []
        for point, values in groups:
            if point not in watched:
                watched.add(point)
                watch(point)
            empty = True
            for value in values:
                empty = False
                if value[0] == 'class':
                    children.append(value[1])
                elif value != _OBJECT:
                    incomplete = True
            incomplete |= empty
        stack.append((current, iter(children)))

    enter(cls)
    while stack:
        current, children = stack[-1]
        for child in children:
            if requested is not _NO_TARGET and child == requested:
                return True, incomplete
            color = colors.get(child, 0)
            if color == 1:
                incomplete = True
            elif color == 0:
                enter(child)
                break
        else:
            colors[current] = 2
            stack.pop()
    return False, incomplete


def subtype_relation(cls, requested, bases, watch):
    """True for reachability; otherwise None for open/cyclic, else False.

    An open/packed base does not invalidate a separate concrete path to the
    requested class. Empty value sets are open, while a class with no declared
    base points is closed (its implicit object base is not another source ID).
    """
    reached, incomplete = _walk(cls, bases, watch, requested=requested)
    return True if reached else None if incomplete else False


def inherited_object_relation(cls, declared, bases, watch):
    """True only for a closed acyclic graph without a source override.

    ``declared(classid)`` answers whether the queried source namespace has the
    relevant override. Any reachable override, packed/open/missing base or
    cycle rejects the default. This is structural admission, not runtime MRO
    selection or a claim about mutable namespaces/metaclasses.
    """
    _, incomplete = _walk(cls, bases, watch, declared=declared)
    return not incomplete
