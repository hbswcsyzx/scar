"""Read-only body occurrence queries over strict canonical wire documents."""
from pathlib import Path
import json

from scar.ir.program.codec import loads as load_program
from scar.ir.record_codec import encode
from scar.ir.v2.ids import Identifier

from .codec import loads as load_execution
from .ids import OperationOccurrenceID, RegionActivationID
from .query import ExecutionIndex


def _wire_id(text, expected):
    prefix = expected.prefix + ':'
    if type(text) is not str or not text.startswith(prefix) or not text[len(prefix):]:
        raise ValueError(f'expected canonical {expected.prefix}:<value> wire ID')
    result = expected(text[len(prefix):])
    if result.wire != text:
        raise ValueError('noncanonical wire ID')
    return result


def _projection(value):
    """Keep record encoding; only project view maps' typed keys to wire keys."""
    if type(value) is dict:
        result = {}
        for key, item in value.items():
            projected = key.wire if isinstance(key, Identifier) else key
            if type(projected) is not str:
                raise ValueError('query map key has no canonical string projection')
            if projected in result:
                raise ValueError('query map keys collide after canonical wire projection')
            result[projected] = _projection(item)
        return result
    if type(value) in (tuple, list):
        return [_projection(item) for item in value]
    return encode(value)


def query_body_execution(args):
    """Load declarations and call existing queries; never execute the program."""
    flags = {'source_runtime_verified': False, 'transformation_authorized': False}
    try:
        inputs = tuple(Path(name).resolve() for name in (args.program, args.execution))
        output = None if args.out is None else Path(args.out).resolve()
        if output is not None and any(
                output == path or output.exists() and path.exists() and output.samefile(path)
                for path in inputs):
            raise ValueError('output path must differ from both input documents')
        identity = _wire_id(args.drive, OperationOccurrenceID) if args.drive is not None else _wire_id(
            args.activation, RegionActivationID)
        program = load_program(inputs[0].read_text(encoding='utf-8'))
        model = load_execution(inputs[1].read_text(encoding='utf-8'))
        index = ExecutionIndex(model, program)
        view = (index.drive_execution(identity, budget=args.budget) if args.drive is not None else
                index.body_activation_origin(identity, budget=args.budget))
        status = 'PARTIAL' if view['status'] == 'DECLARED' and view['validation_gaps'] else view['status']
        report = {'schema': 'scar.body-execution-query', 'schema_version': 1,
                  'status': status, 'query': _projection(view),
                  'validation_gaps': _projection(view['validation_gaps']), **flags}
        text = json.dumps(report, indent=2, ensure_ascii=True, allow_nan=False) + '\n'
        if output is not None:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(text, encoding='utf-8')
    except (OSError, ValueError, TypeError, KeyError, AttributeError, RecursionError) as error:
        print(json.dumps({'schema': 'scar.body-execution-query', 'schema_version': 1,
                          'status': 'ERROR', 'errors': [str(error)], **flags}, ensure_ascii=True))
        return 2
    print(text, end='')
    return 0


__all__ = ['query_body_execution']
