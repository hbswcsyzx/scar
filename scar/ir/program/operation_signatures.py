"""Match explicit port contracts against original canonical graph interfaces.

This F4-B1 query does not select a language rule or authorize a lowering.  The
caller supplies an already instantiated contract; the later rule catalogue
must justify its family, parameters and source witness.  In particular, a
successful match says nothing about purity or whether two calls are reusable.
"""
from scar.ir.program.ids import OperationID, UseID
from scar.ir.program.model import (
    CompletionResult, OperationResult, ProgramGraph, Terminator, TerminatorKind,
    value_type,
)
from scar.ir.program.signature_patterns import (
    SignatureError, SignatureForm, validate_resolved_signature,
)
from scar.ir.program.validation import require_valid


class OperationSignatureIndex:
    """Reuse one validated fragment's original ID indexes across port queries.

    Building the index is linear in the fragment.  A match visits only the
    selected operation's interface and its completion landing arguments; it
    neither reparses source nor duplicates a function/loop body.
    """

    def __init__(self, graph: ProgramGraph):
        if type(graph) is not ProgramGraph:
            raise SignatureError('GRAPH_TYPE', 'graph', 'expected exact ProgramGraph')
        try:
            require_valid(graph)
        except (TypeError, ValueError) as error:
            raise SignatureError('GRAPH_INVALID', 'graph', str(error)) from error
        self._operations = {row.id: row for row in graph.operations}
        self._values = {row.id: row for row in graph.values}
        self._blocks = {block.id: block for region in graph.regions for block in region.blocks}

    def match(self, operation_id: OperationID, signature):
        """Check ordered types/original result sites, never infer a signature.

        Core control terminators and region-call interfaces are separate rule
        families.  They are explicitly outside this first projection, rather
        than being guessed from their labels or treated as ordinary calls.
        """
        validate_resolved_signature(signature)
        if type(operation_id) is not OperationID:
            raise SignatureError('OPERATION_ID', 'operation', 'expected exact OperationID')
        try:
            operation = self._operations[operation_id]
        except KeyError as error:
            raise SignatureError('MISSING_OPERATION', 'operation', operation_id.wire) from error
        path = operation_id.wire
        uses = {use.id: use for use in operation.uses}

        def check_types(expected, actual, at):
            if len(expected) != len(actual):
                raise SignatureError('PORT_ARITY', at, f'expected {len(expected)}, found {len(actual)}')
            for ordinal, (wanted, found) in enumerate(zip(expected, actual)):
                if type(wanted) is not type(found) or wanted != found:
                    raise SignatureError('PORT_TYPE', at + f'[{ordinal}]', 'declared port type differs')

        def types_of_values(identities):
            return tuple(value_type(self._values[identity]) for identity in identities)

        if signature.form is SignatureForm.ORDINARY:
            if operation.terminator is not None or operation.callee is not None:
                raise SignatureError('UNSUPPORTED_INTERFACE', path, 'ordinary projection needs a local nonterminator')
            arguments = tuple(use.id for use in operation.uses)
            check_types(signature.arguments, types_of_values(tuple(use.value for use in operation.uses)), path + '.arguments')
            check_types(signature.results, types_of_values(operation.results), path + '.results')
            for ordinal, identity in enumerate(operation.results):
                origin = self._values[identity].origin
                if type(origin) is not OperationResult or origin != OperationResult(operation.id, ordinal):
                    raise SignatureError('RESULT_ORIGIN', path + f'.results[{ordinal}]', 'not the original result ordinal')
            completions = []
        else:
            terminator = operation.terminator
            if type(terminator) is not Terminator or terminator.kind is not TerminatorKind.INVOKE:
                raise SignatureError('INTERFACE_FORM', path, 'expected an original INVOKE interface')
            arguments = operation.invoke_arguments
            check_types(signature.arguments, types_of_values(tuple(uses[identity].value for identity in arguments)), path + '.arguments')
            wanted = {row.kind: row.types for row in signature.completions}
            actual = {row.kind: row.types for row in operation.completions}
            if wanted.keys() != actual.keys():
                raise SignatureError('COMPLETION_KINDS', path + '.completions', 'normal/raise alternatives differ')
            for kind, types in wanted.items():
                check_types(types, actual[kind], path + '.completions.' + kind.value)
            accounted = set(arguments)
            completions = []
            for edge_index, edge in enumerate(terminator.successors):
                block = self._blocks[edge.block]
                bindings, forwarded = [], []
                for argument, identity in zip(edge.arguments, block.arguments):
                    if type(argument) is CompletionResult:
                        check_types((wanted[edge.kind][argument.index],), types_of_values((identity,)),
                                    path + f'.edges[{edge_index}].result[{argument.index}]')
                        bindings.append(dict(result_index=argument.index, block_argument=identity.wire))
                    elif type(argument) is UseID:
                        accounted.add(argument)
                        forwarded.append(dict(use=argument.wire, block_argument=identity.wire))
                    else:
                        raise SignatureError('COMPLETION_PORT', path, 'unregistered completion argument')
                completions.append(dict(kind=edge.kind.value, successor_index=edge_index,
                                        block=edge.block.wire, results=bindings, forwarded=forwarded))
            if accounted != uses.keys():
                raise SignatureError('UNASSIGNED_USE', path + '.uses', 'every use must be an argument or an edge forwarding use')

        return dict(operation=operation_id.wire, form=signature.form.value,
                    arguments=[identity.wire for identity in arguments],
                    results=[identity.wire for identity in operation.results],
                    completions=completions, ports_checked=True,
                    operation_family_authorized=False, parameter_provenance_checked=False,
                    source_correspondence_checked=False, state_relations_checked=False,
                    use_roles_checked=False, transformation_authorized=False)


__all__ = ['OperationSignatureIndex']
