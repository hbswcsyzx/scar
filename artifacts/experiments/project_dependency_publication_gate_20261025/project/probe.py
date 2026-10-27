import torch


def identity(value):
    return value


def keyword_record(value):
    return dict(value=value)


value = torch.tensor(1.0, device="cpu")
for index in range(3):
    value = identity(value) + 1
    record = keyword_record(index)
assert record["value"] == 2
assert value.device.type == "cpu"
