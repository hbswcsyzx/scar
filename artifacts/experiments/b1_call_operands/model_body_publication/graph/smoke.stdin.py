from itertools import product
from tests.fixtures.program_publication_graphs import publication_program
from scar.ir.program.validation import require_valid
from scar.ir.program.codec import dumps, loads
count = 0
for target, extra, subset, create, direct in product(('start', 'value', 'packet'), (False, True), (False, True), (False, True), (False, True)):
    graph = publication_program(target=target, extra_domain=extra, strict_subset=subset, create=create, direct_owner=direct)
    require_valid(graph)
    wire = dumps(graph)
    assert dumps(loads(wire)) == wire
    count += 1
print({'valid_declared_paths': count, 'scope': 'manual D2.1 IR only'})
