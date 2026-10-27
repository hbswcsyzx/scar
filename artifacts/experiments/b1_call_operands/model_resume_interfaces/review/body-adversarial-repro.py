"""IR-only probe: repeated SavedInput aliases do not add capture producers."""
from dataclasses import replace
import json

from scar.ir.program.control import ProtocolValueKind as P
from scar.ir.program.ids import BlockID, OperationID, ValueID
from scar.ir.program.model import BlockArgument, ProtocolValue, ReferenceValue
from scar.ir.program.resumption import SavedInput
from scar.ir.program.validation import validate
from tests.fixtures.program_resumption_graphs import resumption_program


def repeated_saved_formal(*, frame):
    graph = resumption_program()
    source = next(op for op in graph.operations if op.id == OperationID("resume.suspend"))
    edge, other = source.terminator.successors
    target = next(block for block in graph.regions[0].blocks if block.id == edge.block)
    origin = BlockArgument(target.id, len(target.arguments))
    identity = ValueID("resume.alias.frame" if frame else "resume.alias.reference")
    value = (ProtocolValue(identity, graph.root, origin, P.FRAME_CONTEXT) if frame
             else ReferenceValue(identity, graph.root, origin))
    changed = replace(source, terminator=replace(source.terminator, successors=(
        replace(edge, arguments=(*edge.arguments, SavedInput(0 if frame else 1))), other)))
    return replace(graph, values=(*graph.values, value), operations=tuple(
        changed if op.id == changed.id else op for op in graph.operations), regions=(replace(
            graph.regions[0], blocks=tuple(replace(block, arguments=(*block.arguments, identity))
                if block.id == target.id else block for block in graph.regions[0].blocks)),))


def main():
    result = {}
    for name, graph in (("base", resumption_program()),
                        ("repeated_saved_reference", repeated_saved_formal(frame=False)),
                        ("repeated_saved_frame", repeated_saved_formal(frame=True))):
        result[name] = [{"code": issue.code, "path": issue.path, "message": issue.message}
                        for issue in validate(graph)]
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
