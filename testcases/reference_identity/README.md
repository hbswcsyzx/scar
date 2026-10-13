# Reference identity evidence fixture

This program is an input to SCAR's source and execution adapters. It has no
dependency on SCAR and is outside the `scar` package. Its names carry no special
meaning to the analyzer.

The three functions distinguish ordered parameter reads, negated identity and
two reads of the same parameter. Drivers supply ordinary objects or Tensor
references. Tensor contents may change while Python identity stays unchanged;
that observation is not a content-stability proof.

This is a graph-connection test, not a profitable optimization benchmark.
