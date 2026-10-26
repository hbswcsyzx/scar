import torch


def leaf(value):
    return torch.add(value, value)


def bridge(callback, value):
    return callback(value)


def blocked(values):
    return leaf(*values)


class Box:
    def step(self, value):
        return leaf(value)


def run(box, value, values):
    first = bridge(leaf, value)
    blocked(values)
    return box.step(first)
