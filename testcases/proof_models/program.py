"""External source model testcase; analysis must not execute this program."""


def stage(left, right, values, manager):
    token = ()
    marker = 1 + 2
    alias = token
    same = left is right
    different = left is not right
    if same:
        chosen = left
    else:
        chosen = right
    for item in values:
        inner = item is left
        if inner:
            continue
        break
    try:
        with manager:
            result = callback(chosen)
    finally:
        cleanup()
    return alias, marker, same, different


raise RuntimeError("Source model testcase must never be executed by SCAR")
