
def module_entry_catalog(composition, *, max_files=4096):
    """Independent original MODULE roots, without changing function eligibility.

    This is a metadata candidate catalog, not CodeType, activation or namespace
    proof. Normal lower_entry must resolve the exact readonly exec-root witness.
    It deliberately does not add MODULE to DefinitionKind or invent bodies.
    """
    from scar.ir.program.module_entries import ModuleCatalogEntry, ModuleUnitSource
    from scar.ir.v2.ids import OperationDefinitionID
    _need(type(composition) is CompositionIndex and type(max_files) is int and max_files > 0
          and composition.inventory_file_count <= max_files, 'module metadata catalog ceiling exceeded')
    result, seen = [], set()
    for fi, file in enumerate(composition.document['files']):
        raw = composition.inventory_file(fi)
        snapshot = decode(SourceSnapshot, raw['snapshot'])
        _need(raw['context'] is not None, 'module catalog requires exact original source context')
        context = decode(SourceContextDigest, raw['context'])
        for wire in file['module_roots']:
            _need(type(wire) is str and wire.startswith('opdef:'), 'invalid original MODULE identity')
            initializer = OperationDefinitionID(wire[len('opdef:'):])
            _need(initializer.wire == wire, 'module root wire identity differs')
            unit = ModuleUnitSource(snapshot, context.namespace_root, initializer)
            key = _hash(encode(unit))
            _need(key not in seen, 'duplicate fully qualified module source unit')
            seen.add(key)
            result.append(ModuleCatalogEntry(unit, context, fi))
    return tuple(result)
