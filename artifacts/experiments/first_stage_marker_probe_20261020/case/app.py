"""An external CPU testcase, independent of SCAR and LeWM."""


def run(x, g):
    view = x.view(2, 2)
    result = x + x
    x.add_(1)
    loss = (g * g).sum()
    return view, result, loss
