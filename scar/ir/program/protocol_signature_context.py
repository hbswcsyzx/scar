"""Join declared Python protocols, port rules and original parameter records.

This is a static interface query, not source-production replay.  In particular
matching mutually consistent declarations does not establish that the source
actually produced them.  F4-C and the versioned graph reader still own that
obligation; neither this query nor its receipt authorizes transformations.
"""
from collections import defaultdict

from scar.ir.program.functions import BodyEntryInterface, BodyLoweringProfile
from scar.ir.program.ids import OperationID
from scar.ir.program.model import (
    BlockArgument, LocalBindingType, LocalBindingValue, ProtocolValue, StateVersionValue, ValueKind, ValueType,
)
from scar.ir.program.control import ProtocolValueKind
from scar.ir.program.operation_signatures import OperationSignatureIndex
from scar.ir.program.protocol_signatures import (
    ExceptionABI, ParameterOrigin, _resolve_protocol_rule, protocol_signature_catalog,
)
from scar.ir.program.protocol_signature_state import validate_protocol_state
from scar.ir.program.signature_patterns import (
    ChoiceBinding, CountBinding, ParameterKind, SignatureError, TypeBinding, TypesBinding,
)
from scar.ir.program.source import LoweringMetadata
from scar.ir.program.source_language import SourceLanguageCapability, SourceLanguageOverlay
from scar.ir.program.structured import PythonProtocolKind, StructuredBodyModel
from scar.ir.v2._validation import record_errors


class ProtocolSignatureIndex:
    """Index one original body once; resolve each query by original IDs.

    Bindings with a supported typed origin are computed here.  Remaining
    bindings may be supplied explicitly for diagnostic queries and stay
    unverified.  Operation input/result arities never select a parameter or an
    exception profile.
    """

    def __init__(self, graph, structured: StructuredBodyModel,
                 interface: BodyEntryInterface, metadata: LoweringMetadata, *,
                 language: SourceLanguageOverlay | None = None):
        self._ports = OperationSignatureIndex(graph)
        for name, value, kind in (('structured', structured, StructuredBodyModel),
                ('interface', interface, BodyEntryInterface), ('metadata', metadata, LoweringMetadata),
                ('language', language, SourceLanguageOverlay)):
            if value is None and name == 'language':
                continue
            if type(value) is not kind:
                raise SignatureError('CONTEXT_TYPE', name, 'expected exact ' + kind.__name__)
            errors = record_errors(value, kind, name)
            if errors:
                raise SignatureError('CONTEXT_RECORD', name, errors[0])
        if (structured.region != graph.root or interface.region != graph.root
                or structured.definition != interface.definition):
            raise SignatureError('CONTEXT_REGION', 'context', 'body/definition roots disagree')
        if interface.profile not in (BodyLoweringProfile.STRUCTURED_BODY, BodyLoweringProfile.STRUCTURED_ENV):
            raise SignatureError('UNSUPPORTED_BODY_PROFILE', 'interface.profile', interface.profile.value)
        snapshot = metadata.source

        def same_source(source):
            return source.path == snapshot.path and source.fingerprint == snapshot.fingerprint

        if not same_source(structured.source):
            raise SignatureError('CONTEXT_SOURCE', 'structured.source', 'source version differs')
        if language is not None and language.source != snapshot:
            raise SignatureError('CONTEXT_SOURCE', 'language.source', 'source snapshot differs')
        self._graph, self._interface, self._language, self._snapshot = graph, interface, language, snapshot
        self._rules = {row.kind: row for row in protocol_signature_catalog()}
        self._values = {row.id: row for row in graph.values}
        self._operations = {row.id: row for row in graph.operations}
        self._regions = {row.id: row for row in graph.regions}
        self._owners = {operation: region.id for region in graph.regions
                        for block in region.blocks for operation in block.operations}
        initial = self._values.get(interface.world)
        root = self._regions[interface.region]
        if (type(initial) is not StateVersionValue or initial.region != interface.region
                or type(initial.origin) is not BlockArgument or initial.origin.block != root.entry):
            raise SignatureError('CONTEXT_WORLD', 'interface.world', 'world must be an original entry state')
        self._sources = defaultdict(list)
        for row in metadata.operation_links:
            self._sources[row.operation].append(row.source)
        self._use_sources = defaultdict(list)
        for row in metadata.use_links:
            self._use_sources[row.operation].append(row)
        self._value_sources = defaultdict(list)
        for row in metadata.value_links:
            self._value_sources[row.value].append(row)
        self._protocols = {}
        for row in structured.protocols:
            if row.operation in self._protocols or row.operation not in self._operations:
                raise SignatureError('CONTEXT_PROTOCOL', 'structured.protocols', 'duplicate or missing original operation')
            sources = self._sources.get(row.operation, ())
            if (not same_source(row.source) or not sources
                    or any(source != row.source for source in sources)):
                raise SignatureError('CONTEXT_SOURCE', row.operation.wire, 'protocol and original operation source disagree')
            self._protocols[row.operation] = row
        self._lambda_entries = {}
        if language is not None:
            for row in language.lambda_bodies:
                if row.body.region in self._lambda_entries:
                    raise SignatureError('CONTEXT_LAMBDA', 'language.lambda_bodies', 'duplicate body region')
                self._lambda_entries[row.body.region] = row.body
        self._resumables = {row.region: row for row in graph.resumable_bodies}
        self._drivers = {row.region: row for row in graph.driver_interfaces}

    def _region_profile(self, operation):
        region = self._owners[operation]
        if region == self._interface.region:
            initial = self._values[self._interface.world]
            paired = (self._language is not None and
                SourceLanguageCapability.FUNCTION_TRY_314_V1 in self._language.capabilities)
            abi = ExceptionABI.EXCEPTION_TRACEBACK_WORLD if paired else ExceptionABI.EXCEPTION_WORLD
            return initial.location, abi, dict(record='BodyEntryInterface', region=region.wire,
                                               world=self._interface.world.wire)
        if region in self._lambda_entries:
            entry = self._lambda_entries[region]
            initial = self._values.get(entry.world)
            if type(initial) is not StateVersionValue or initial.region != region:
                raise SignatureError('CONTEXT_WORLD', region.wire, 'lambda world is absent or has the wrong owner')
            return initial.location, ExceptionABI.EXCEPTION_WORLD, dict(
                record='LambdaBodyDefinition.body', region=region.wire, world=entry.world.wire)
        # Only the explicitly modelled source generator recipe has this ABI.
        capabilities = self._language.capabilities if self._language is not None else ()
        if (SourceLanguageCapability.GENEXPR_314_V1 in capabilities
                or SourceLanguageCapability.GENEXPR_CREATION_314_V1 in capabilities):
            body = self._resumables.get(region)
            driver = self._drivers.get(region)
            if body is None and driver is not None:
                body = self._resumables.get(driver.body)
            if body is not None:
                return body.context_location, ExceptionABI.EXCEPTION_WORLD, dict(
                    record='ResumableBody' if driver is None else 'DriverInterface.body',
                    region=region.wire, body=body.region.wire)
        raise SignatureError('MISSING_REGION_SIGNATURE_CONTEXT', region.wire, 'no declared exception/world profile for this region')

    def _declared_frame_roots(self, operation):
        """Parse original source-port declarations before inspecting the uses.

        The declaration can be checked against a proposed graph independently
        of its arity/order. Its existence does not prove that every live root
        was declared: source-production/ownership replay is still required.
        """
        rows = self._use_sources[operation]
        if not rows:
            raise SignatureError('MISSING_SIGNATURE_CONTEXT', operation.wire, 'missing original frame port declarations')
        allowed = {'held-payload', 'held-local', 'held-temporary', 'frame-world'}
        if (any(row.role not in allowed for row in rows)
                or len({row.use for row in rows}) != len(rows)):
            raise SignatureError('FRAME_PORT_DECLARATION', operation.wire, 'unknown role or repeated declared UseID')
        if any(row.source.path != self._snapshot.path or row.source.fingerprint != self._snapshot.fingerprint for row in rows):
            raise SignatureError('CONTEXT_SOURCE', operation.wire, 'frame port source version differs')
        worlds = [row for row in rows if row.role == 'frame-world']
        ports = sorted((row for row in rows if row.role != 'frame-world'), key=lambda row: row.index)
        if (len(worlds) != 1 or worlds[0].index != 0 or not ports
                or [row.index for row in ports] != list(range(len(ports)))
                or ports[0].role != 'held-payload'
                or any(row.role == 'held-payload' for row in ports[1:])):
            raise SignatureError('FRAME_PORT_DECLARATION', operation.wire, 'frame payload/world or contiguous declaration indices differ')
        uses = {row.id: row for row in self._operations[operation].uses}
        expected = tuple(row.use for row in ports) + (worlds[0].use,)
        if expected != tuple(row.id for row in self._operations[operation].uses):
            raise SignatureError('FRAME_PORT_ORDER', operation.wire, 'original declared UseID order differs from operation ports')
        types, references, temporary_seen = [], [], False
        for row in ports[1:]:
            if row.role == 'held-local':
                if temporary_seen:
                    raise SignatureError('FRAME_PORT_DECLARATION', operation.wire, 'local roots must precede temporary roots')
                value_id = uses[row.use].value
                # A merge token's source role is CONTROL (or PARAMETER),
                # while a local definition uses LOCAL_BINDING. The explicit
                # slot field, not that orthogonal phase role, names its slot.
                sources = [source for source in self._value_sources[value_id] if source.slot is not None]
                if (not sources or len({source.slot for source in sources}) != 1
                        or any(source.source.path != self._snapshot.path or
                               source.source.fingerprint != self._snapshot.fingerprint for source in sources)):
                    raise SignatureError('MISSING_SIGNATURE_CONTEXT', operation.wire, 'local root has no unique original slot declaration')
                types.append(LocalBindingType(sources[0].slot))
            else:
                temporary_seen = True
                types.append(ValueType(ValueKind.REFERENCE))
            references.append(row.use.wire)
        return tuple(types), dict(record='LoweringMetadata.use_links+value_links',
                                  operation=operation.wire, uses=references,
                                  completeness='DECLARED_PORT_GROUP_ONLY')

    def _declared_invoke_parameter(self, operation, kind):
        """Parse a closed source-port group, then compare original UseIDs.

        Empty groups have no separate source marker in the historical format.
        They are explicitly recorded as declarations, not as an AST absence
        proof. Forwarded caller contexts are not source arguments.
        """
        rows = self._use_sources[operation]
        if (not rows or len({row.use for row in rows}) != len(rows)
                or any(row.source.path != self._snapshot.path or row.source.fingerprint != self._snapshot.fingerprint for row in rows)):
            raise SignatureError('INVOKE_PORT_DECLARATION', operation.wire, 'missing, repeated or wrong-version source ports')
        original = self._operations[operation]
        worlds = [row for row in rows if row.role == 'state']
        forwarded = [row for row in rows if row.role == 'caller-edge']
        ports = [row for row in rows if row.role not in ('state', 'caller-edge')]
        if len(worlds) != 1 or worlds[0].index != 0:
            raise SignatureError('INVOKE_PORT_DECLARATION', operation.wire, 'expected one declared state port at index zero')
        if forwarded:
            edges = original.terminator.successors
            uses = {row.id: row for row in original.uses}
            if sorted(row.index for row in forwarded) != list(range(len(edges))):
                raise SignatureError('INVOKE_FORWARD_DECLARATION', operation.wire, 'caller forwarding must cover the original edges')
            for row in forwarded:
                use = uses.get(row.use)
                value = self._values.get(use.value) if use else None
                if (row.use not in edges[row.index].arguments or type(value) is not ProtocolValue
                        or value.protocol is not ProtocolValueKind.DRIVE_CALLER_CONTEXT):
                    raise SignatureError('INVOKE_FORWARD_DECLARATION', operation.wire, 'not an original caller-context forwarding use')
        K = PythonProtocolKind
        if kind is K.CALL_FUNCTION_EX:
            by_role = {row.role: row for row in ports}
            positional = [name for name in ('call-positionals', 'call-starred-positionals') if name in by_role]
            if (len(by_role) != len(ports) or len(positional) != 1 or 'callee' not in by_role
                    or not set(by_role) <= {'callee', 'call-positionals', 'call-starred-positionals', 'call-keywords'}
                    or any(row.index != 0 for row in ports)):
                raise SignatureError('INVOKE_PORT_DECLARATION', operation.wire, 'invalid call callee/positionals/keyword groups')
            ordered = [by_role['callee'], by_role[positional[0]]]
            if 'call-keywords' in by_role:
                ordered.append(by_role['call-keywords'])
            value = 'PRESENT' if 'call-keywords' in by_role else 'ABSENT'
        elif kind is K.BUILD_MAP:
            groups = defaultdict(list)
            for row in ports:
                groups[row.index].append(row)
            indices = sorted(groups)
            if any(right != left + 1 for left, right in zip(indices, indices[1:])):
                raise SignatureError('INVOKE_PORT_DECLARATION', operation.wire, 'map pair indices must be a contiguous source run')
            mapping = all(row.role in ('mapping-key', 'mapping-value') for row in ports)
            keywords = all(row.role == 'call-keyword-name' or row.role.startswith('keyword:') and len(row.role) > len('keyword:') for row in ports)
            if not mapping and not keywords:
                raise SignatureError('INVOKE_PORT_DECLARATION', operation.wire, 'unknown or mixed map pair dialects')
            ordered = []
            for index in indices:
                group = groups[index]
                key = 'mapping-key' if mapping else 'call-keyword-name'
                keys = [row for row in group if row.role == key]
                vals = [row for row in group if row.role != key]
                if len(keys) != 1 or len(vals) != 1:
                    raise SignatureError('INVOKE_PORT_DECLARATION', operation.wire, 'map pair must declare exactly one key and value')
                ordered.extend((keys[0], vals[0]))
            value = len(indices)
        else:
            role = 'argument' if kind is K.BUILD_CALL_POSITIONAL_LIST else 'protocol-input'
            ordered = sorted(ports, key=lambda row: row.index)
            if (any(row.role != role for row in ordered)
                    or [row.index for row in ordered] != list(range(len(ordered)))
                    or kind is K.MAKE_ASSERTION_ERROR and len(ordered) > 1):
                raise SignatureError('INVOKE_PORT_DECLARATION', operation.wire, 'invalid declared source argument sequence')
            value = ('PRESENT' if ordered else 'ABSENT') if kind is K.MAKE_ASSERTION_ERROR else len(ordered)
        expected = tuple(row.use for row in ordered) + (worlds[0].use,)
        if expected != original.invoke_arguments:
            raise SignatureError('INVOKE_PORT_ORDER', operation.wire, 'source declaration and original invoke argument order differ')
        return value, dict(record='LoweringMetadata.use_links', operation=operation.wire,
                           uses=[row.use.wire for row in ordered],
                           completeness='DECLARED_PORT_GROUP_ONLY' if ports else 'DECLARED_EMPTY_GROUP',
                           explicit_empty_marker=False)

    def _automatic(self, operation, rule):
        """Return derived bindings plus bounded original-record references."""
        protocol = self._protocols[operation]
        parameters = {row.name: row for row in rule.signature.parameters}
        bound, origins = {}, []
        profile = None

        def add(binding, record):
            bound[binding.name] = binding
            origins.append(dict(parameter=binding.name, **record))

        for requirement in rule.requirements:
            name, origin = requirement.name, requirement.origin
            parameter = parameters[name]
            if (origin in (ParameterOrigin.SOURCE_PORTS, ParameterOrigin.CALL_SHAPE)
                    and protocol.kind in (PythonProtocolKind.BUILD_MAP, PythonProtocolKind.CALL_FUNCTION_EX,
                        PythonProtocolKind.BUILD_CALL_POSITIONAL_LIST, PythonProtocolKind.BUILD_STRING,
                        PythonProtocolKind.MAKE_ASSERTION_ERROR)):
                value, record = self._declared_invoke_parameter(operation, protocol.kind)
                binding = CountBinding(name, value) if parameter.kind is ParameterKind.COUNT else ChoiceBinding(name, value)
                add(binding, record)
            elif origin in (ParameterOrigin.STATE_DOMAIN, ParameterOrigin.EXCEPTION_PROFILE):
                if profile is None:
                    profile = self._region_profile(operation)
                location, abi, record = profile
                if origin is ParameterOrigin.STATE_DOMAIN:
                    add(TypeBinding(name, ValueType(ValueKind.STATE, location=location)), record)
                else:
                    # Some adapter protocols have a fixed ABI independent of
                    # their parent's language profile. The rule declares it.
                    choice = parameter.choices[0] if len(parameter.choices) == 1 else abi.value
                    add(ChoiceBinding(name, choice), dict(record,
                        selector='FIXED_RULE_ABI' if len(parameter.choices) == 1 else 'REGION_PROFILE'))
            elif origin in (ParameterOrigin.UNPACK_CHILDREN, ParameterOrigin.SLICE_SHAPE):
                if self._language is None:
                    continue
                rows = (self._language.unpackings if origin is ParameterOrigin.UNPACK_CHILDREN
                        else self._language.slices)
                matches = [(i, row) for i, row in enumerate(rows) if row.operation == operation]
                if len(matches) != 1 or matches[0][1].source != protocol.source:
                    raise SignatureError('MISSING_SIGNATURE_CONTEXT', operation.wire, 'missing or conflicting original shape record')
                ordinal, row = matches[0]
                if origin is ParameterOrigin.UNPACK_CHILDREN:
                    add(CountBinding(name, len(row.child_targets)),
                        dict(record='SourceLanguageOverlay.unpackings', ordinal=ordinal, selector='child_targets'))
                else:
                    add(ChoiceBinding(name, 'ABSENT' if row.step is None else 'PRESENT'),
                        dict(record='SourceLanguageOverlay.slices', ordinal=ordinal, selector='step'))
            elif origin is ParameterOrigin.FRAME_ROOTS and protocol.kind is PythonProtocolKind.FRAME_ENTER:
                region = self._owners[operation]
                if region != self._interface.region:
                    continue
                environments = [row for row in self._graph.environments if row.region == region]
                if self._interface.profile is BodyLoweringProfile.STRUCTURED_ENV:
                    if len(environments) != 1:
                        raise SignatureError('MISSING_SIGNATURE_CONTEXT', operation.wire, 'entry environment is not unique')
                    count = len(environments[0].members) + len(self._interface.parameters)
                else:
                    count = len(self._interface.parameters)
                binding = (CountBinding(name, count) if parameter.kind is ParameterKind.COUNT else
                           TypesBinding(name, (ValueType(ValueKind.REFERENCE),) * count))
                add(binding,
                    dict(record='BodyEntryInterface.parameters+EnvironmentInterface.members', region=region.wire))
            elif origin is ParameterOrigin.FRAME_ROOTS and protocol.kind is PythonProtocolKind.FRAME_EXIT:
                types, record = self._declared_frame_roots(operation)
                add(TypesBinding(name, types), record)
            elif origin is ParameterOrigin.LOCAL_BINDING:
                # Structured binding tokens are distinct from the older
                # BOUND_FRAME FrameModel facet. Use its original source port,
                # never reinterpret that facet or guess a local by position.
                roles = (('previous-binding', 'previous-exception-binding')
                         if protocol.kind is PythonProtocolKind.FRAME_BIND else
                         ('cleared-exception-binding',)
                         if protocol.kind is PythonProtocolKind.FUNCTION_CLEAR_EXCEPTION_NAME else ())
                matches = [row for row in self._use_sources[operation]
                           if row.role in roles and row.index == 0 and row.source == protocol.source]
                if len(matches) != 1:
                    continue
                use = next((row for row in self._operations[operation].uses
                            if row.id == matches[0].use), None)
                value = self._values.get(use.value) if use is not None else None
                if type(value) is not LocalBindingValue:
                    raise SignatureError('CONTEXT_BINDING', operation.wire, 'source binding port has no local-binding token')
                add(TypeBinding(name, LocalBindingType(value.slot)),
                    dict(record='LoweringMetadata.use_links->LocalBindingValue.slot',
                         operation=operation.wire, use=use.id.wire, value=value.id.wire, role=matches[0].role))
        return bound, origins

    def match(self, operation: OperationID, bindings=()):
        if type(operation) is not OperationID or operation not in self._protocols:
            raise SignatureError('MISSING_PROTOCOL', 'operation', 'expected an original typed PythonProtocol operation')
        protocol = self._protocols[operation]
        rule = self._rules[protocol.kind]
        if rule.signature is None:
            # Preserve the catalogue's explicit refusal, not a generic fallback.
            _resolve_protocol_rule(rule, ())
        automatic, origins = self._automatic(operation, rule)
        if type(bindings) is not tuple:
            raise SignatureError('BINDINGS_TYPE', 'bindings', 'expected exact tuple')
        for binding in bindings:
            if type(binding) not in (ChoiceBinding, CountBinding, TypeBinding, TypesBinding):
                raise SignatureError('UNREGISTERED_VARIANT', 'bindings', 'expected an exact parameter binding record')
            name = getattr(binding, 'name', None)
            if type(name) is str and name in automatic:
                raise SignatureError('RESERVED_BINDING', 'bindings', 'cannot override a binding from an original typed record')
        complete = tuple(automatic.values()) + bindings
        try:
            resolved = _resolve_protocol_rule(rule, complete)
        except SignatureError as error:
            if error.code == 'MISSING_BINDING':
                supplied = set(automatic) | {binding.name for binding in bindings}
                missing = [row.name + ':' + row.origin.value for row in rule.requirements
                           if row.name not in supplied]
                raise SignatureError('MISSING_SIGNATURE_CONTEXT', operation.wire + '.parameters',
                                     'missing original parameters: ' + ', '.join(missing)) from error
            raise
        receipt = self._ports.match(operation, resolved)
        state = validate_protocol_state(self._operations[operation], self._values, resolved, rule.state_policy)
        receipt.update(state)
        receipt.update(protocol_kind=protocol.kind.value,
                       parameter_records=origins, parameter_source_records_checked=not bool(bindings),
                       parameter_provenance_checked=False, operation_family_authorized=False,
                       source_correspondence_checked=False, source_profile_requirements_checked=False,
                       frame_root_completeness_checked=False,
                       transformation_authorized=False)
        return receipt


__all__ = ['ProtocolSignatureIndex']
