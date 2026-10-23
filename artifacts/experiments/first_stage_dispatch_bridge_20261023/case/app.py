"""External CPU case: duplicate args, views, autograd and a raised dispatch."""
import json
import torch


def run():
    x = torch.arange(4.0)
    duplicate = x + x
    view = x.view(2, 2)
    g = torch.arange(4.0, requires_grad=True)
    loss = (g * g).sum()
    loss.backward()
    raised = False
    try:
        torch.mm(x, x)
    except RuntimeError:
        raised = True
    assert raised
    assert torch.equal(duplicate, 2 * x)
    assert torch.equal(g.grad, 2 * g.detach())
    assert view.shape == (2, 2)
    print(json.dumps({"result_correct": True, "grad_correct": True,
                      "expected_dispatch_exception": raised}))


run()
