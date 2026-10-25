def construct(destination, key):
    destination[f"goal_{key}"] = key
    return destination
