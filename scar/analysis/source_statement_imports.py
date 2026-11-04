"""Import requests, member paths and namespace writes over original F2/F3.

No imported code is executed by this producer. IMPORT_FROM retains its native
fallback contract, and star import keeps dynamic namespace effects. Runtime
importer/frame/registry expansion and exceptional ownership remain unproved.
"""
from scar.analysis.source_expression_rules import _REF, _require
from scar.ir.program import source_productions as P
from scar.ir.program.structured import PythonProtocolKind as K


def _fields(b, alias):
    _require(b.rules.source.context.syntax.nodes[alias].constructor == 'alias',
        'RULE_SHAPE', str(alias), 'import carrier must be an original alias')
    name = b.auxiliary(alias, 'name', P.ProductionDispositionKind.ROLE_PORT)
    renamed = b.auxiliary(alias, 'asname', P.ProductionDispositionKind.METADATA)
    if b.value(renamed).scalar.to_python() is not None:
        b.slots[renamed] = P.ProductionDispositionKind.ROLE_PORT
    return name, renamed


def _bind(b, root, alias, value, world):
    name, renamed = _fields(b, alias)
    site = name if b.value(renamed).scalar.to_python() is None else renamed
    ports = [p for p in b.rules._ports.get(site, ())
        if b.rules.source.frontend.bindings.ports[p].write_target is not None]
    _require(len(ports) == 1, 'BINDING_INTERFACE_FRONTIER', str(site), 'import requires one original namespace write target')
    world, = b.emit(root, P.AccessBinding(P.BindingActionKind.WRITE, ports[0]),
        (value, world), (b.world,), source=site)
    return world


def _release(b, root, value, world):
    return b.protocol(root, K.FRAME_RELEASE_TEMPORARY, (value,), world)[0]


def emit_import_statement(b, root, world):
    index = b.rules.source.statements
    aliases = index.node_items(b.occurrence, 'names')
    _require(bool(aliases), 'RULE_SHAPE', str(b.occurrence), 'import requires aliases')
    for alias in aliases:
        _fields(b, alias)
    if b.node.constructor == 'Import':
        for alias in aliases:
            source = P.ProductionOccurrence(alias)
            requested, world = b.emit(root, index.import_request(b.occurrence, b.rules.exception_abi, alias),
                (world,), (_REF, b.world), source=source)
            fields = b.role.field(alias, 'name').scalar.to_python().split('.')
            renamed = b.role.field(alias, 'asname').scalar.to_python() is not None
            if renamed and len(fields) > 1:
                owner = requested
                for component in range(1, len(fields)):
                    value, world = b.emit(root, index.import_member(alias, component, b.rules.exception_abi),
                        (owner, world), (_REF, b.world), source=source)
                    if component == len(fields)-1:
                        world = _bind(b, root, alias, value, world)
                        world = _release(b, root, value, world)
                    # Intermediate owners end before the next lookup; the last
                    # owner remains until the final binding has completed.
                    world = _release(b, root, owner, world)
                    owner = value
            else:
                world = _bind(b, root, alias, requested, world)
                world = _release(b, root, requested, world)
    else:
        b.mark('module', P.ProductionDispositionKind.ROLE_PORT)
        imported, world = b.emit(root, index.import_request(b.occurrence, b.rules.exception_abi),
            (world,), (_REF, b.world))
        if b.role.field(aliases[0], 'name').scalar.to_python() == '*':
            _require(len(aliases) == 1, 'RULE_SHAPE', str(b.occurrence), 'star import must be the only member')
            world, = b.emit(root, index.import_star(aliases[0], b.rules.exception_abi),
                (imported, world), (b.world,), source=P.ProductionOccurrence(aliases[0]))
        else:
            for alias in aliases:
                value, world = b.emit(root, index.import_member(alias, None, b.rules.exception_abi),
                    (imported, world), (_REF, b.world), source=P.ProductionOccurrence(alias))
                world = _bind(b, root, alias, value, world)
                world = _release(b, root, value, world)
        world = _release(b, root, imported, world)
    b.finish(root, (world,), (b.world,))
