def construct(owner, xs):
    a, b = (transform(t, knob=owner.knob) for t in xs)
    return a
