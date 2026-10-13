"""Complete manual IR examples, not recovered source or optimization proofs."""
from dataclasses import replace

from scar.ir.program.ids import BlockID, LocationID, OperationID, RegionID, UseID, ValueID
from scar.ir.program.model import (
    AccessMode, Behavior, Block, BlockArgument, DataValue, ExitKind, ExitPort,
    Footprint, FootprintKind, LiteralOrigin, Operation, OperationResult, OrderEdge,
    ProgramGraph, ReferenceValue, Region, Stability, StateAccess, StateLocation,
    StateVersionValue, Successor, Terminator, TerminatorKind, Use, UseRole,
    ValueKind, ValueType,
)


def use(name, value, role=UseRole.DATA):
    return Use(UseID(name), ValueID(value), role)


def state_type(location):
    return ValueType(ValueKind.STATE, location=LocationID(location))


def data(name, region, origin, kind="builtins.int"):
    return DataValue(ValueID(name), RegionID(region), origin, kind)


def state(name, region, origin, location):
    return StateVersionValue(ValueID(name), RegionID(region), origin, LocationID(location))


def argument(block, index):
    return BlockArgument(BlockID(block), index)


def result(operation, index=0):
    return OperationResult(OperationID(operation), index)


def operation(name, behaviors, uses=(), results=(), **kwargs):
    return Operation(OperationID(name), name, behaviors, uses,
                     tuple(ValueID(item) for item in results), **kwargs)


def block(name, arguments, operations):
    return Block(BlockID(name), tuple(ValueID(item) for item in arguments),
                 tuple(OperationID(item) for item in operations))


def successor(name, *uses):
    return Successor(BlockID(name), tuple(UseID(item) for item in uses))


def branch_state_program():
    """Read/update a buffer and append a log, or explicitly raise with old state."""
    interval = Footprint(FootprintKind.INTERVAL, 0, 1)
    values = (
        data("input", "root", argument("entry", 0)),
        data("condition", "root", argument("entry", 1), "builtins.bool"),
        ReferenceValue(ValueID("reference"), RegionID("root"), argument("entry", 2),
                       "buffer-reference", (LocationID("buffer"),), interval),
        state("buffer.initial", "root", argument("entry", 3), "buffer"),
        state("log.initial", "root", argument("entry", 4), "log"),
        state("buffer.normal", "root", argument("normal", 0), "buffer"),
        state("log.normal", "root", argument("normal", 1), "log"),
        state("buffer.failure", "root", argument("failure", 0), "buffer"),
        state("log.failure", "root", argument("failure", 1), "log"),
        data("read.value", "root", result("read")),
        data("sum.value", "root", result("sum")),
        state("buffer.updated", "root", result("write"), "buffer"),
        state("log.updated", "root", result("emit"), "log"),
        data("error", "root", LiteralOrigin("explicit failure"), "builtins.str"),
    )
    choose = operation("choose", (Behavior.CONTROL,), (
        use("choose.condition", "condition"),
        use("choose.normal.buffer", "buffer.initial", UseRole.STATE_CONTENT),
        use("choose.normal.log", "log.initial", UseRole.STATE_CONTENT),
        use("choose.failure.buffer", "buffer.initial", UseRole.STATE_CONTENT),
        use("choose.failure.log", "log.initial", UseRole.STATE_CONTENT),
    ), terminator=Terminator(TerminatorKind.BRANCH, (
        successor("normal", "choose.normal.buffer", "choose.normal.log"),
        successor("failure", "choose.failure.buffer", "choose.failure.log"),
    ), condition=UseID("choose.condition")))
    read = operation("read", (Behavior.READ,), (
        use("read.reference", "reference", UseRole.REFERENCE),
        use("read.state", "buffer.normal", UseRole.STATE_CONTENT),
    ), ("read.value",), accesses=(StateAccess(
        LocationID("buffer"), UseID("read.state"), AccessMode.READ,
        footprint=interval, reference=UseID("read.reference")),), effects_complete=True)
    add = operation("sum", (Behavior.COMPUTE,), (
        use("sum.left", "input"), use("sum.right", "read.value"),
    ), ("sum.value",), effects_complete=True)
    write = operation("write", (Behavior.WRITE,), (
        use("write.reference", "reference", UseRole.REFERENCE),
        use("write.value", "sum.value"),
        use("write.state", "buffer.normal", UseRole.STATE_CONTENT),
    ), ("buffer.updated",), accesses=(StateAccess(
        LocationID("buffer"), UseID("write.state"), AccessMode.WRITE,
        ValueID("buffer.updated"), interval, reference=UseID("write.reference")),),
        effects_complete=True)
    emit = operation("emit", (Behavior.READ, Behavior.WRITE), (
        use("emit.value", "sum.value"), use("emit.state", "log.normal", UseRole.STATE_CONTENT),
    ), ("log.updated",), accesses=(StateAccess(
        LocationID("log"), UseID("emit.state"), AccessMode.READ_WRITE,
        ValueID("log.updated")),), effects_complete=True)
    done = operation("done", (Behavior.CONTROL,), (
        use("done.value", "sum.value"),
        use("done.buffer", "buffer.updated", UseRole.STATE_CONTENT),
        use("done.log", "log.updated", UseRole.STATE_CONTENT),
    ), terminator=Terminator(TerminatorKind.RETURN, exit="normal",
                            values=tuple(UseID(f"done.{suffix}") for suffix in ("value", "buffer", "log"))))
    fail = operation("fail", (Behavior.CONTROL,), (
        use("fail.error", "error"),
        use("fail.buffer", "buffer.failure", UseRole.STATE_CONTENT),
        use("fail.log", "log.failure", UseRole.STATE_CONTENT),
    ), terminator=Terminator(TerminatorKind.RAISE, exit="failure",
                            values=tuple(UseID(f"fail.{suffix}") for suffix in ("error", "buffer", "log"))))
    region = Region(RegionID("root"), "branch, update and observable log", BlockID("entry"), (
        block("entry", ("input", "condition", "reference", "buffer.initial", "log.initial"), ("choose",)),
        block("normal", ("buffer.normal", "log.normal"), ("read", "sum", "write", "emit", "done")),
        block("failure", ("buffer.failure", "log.failure"), ("fail",)),
    ), (
        ExitPort("normal", ExitKind.NORMAL, (ValueType(ValueKind.DATA, "builtins.int"), state_type("buffer"), state_type("log"))),
        ExitPort("failure", ExitKind.RAISE, (ValueType(ValueKind.DATA, "builtins.str"), state_type("buffer"), state_type("log"))),
    ))
    return ProgramGraph(region.id, (region,), (choose, read, add, write, emit, done, fail), values, (
        StateLocation(LocationID("buffer"), "mutable buffer", 4, Stability.INTERNAL),
        StateLocation(LocationID("log"), "observable append history", stability=Stability.EXTERNAL),
    ), (OrderEdge(OperationID("read"), OperationID("write")),))


def loop_state_program():
    """Finite graph with a header parameter, zero-trip exit and state backedge."""
    values = (
        data("limit", "loop", argument("loop.entry", 0)),
        state("initial", "loop", argument("loop.entry", 1), "counter"),
        state("header.state", "loop", argument("header", 0), "counter"),
        state("body.state", "loop", argument("body", 0), "counter"),
        state("exit.state", "loop", argument("exit", 0), "counter"),
        data("counter.value", "loop", result("read.counter")),
        data("continue", "loop", result("compare"), "builtins.bool"),
        state("incremented", "loop", result("increment"), "counter"),
    )
    enter = operation("enter", (Behavior.CONTROL,), (use("enter.state", "initial", UseRole.STATE_CONTENT),),
        terminator=Terminator(TerminatorKind.JUMP, (successor("header", "enter.state"),)))
    read = operation("read.counter", (Behavior.READ,), (use("read.counter.state", "header.state", UseRole.STATE_CONTENT),),
        ("counter.value",), accesses=(StateAccess(LocationID("counter"), UseID("read.counter.state"), AccessMode.READ),),
        effects_complete=True)
    compare = operation("compare", (Behavior.COMPUTE,), (
        use("compare.counter", "counter.value"), use("compare.limit", "limit")), ("continue",), effects_complete=True)
    choose = operation("loop.choose", (Behavior.CONTROL,), (
        use("loop.condition", "continue"), use("loop.body.state", "header.state", UseRole.STATE_CONTENT),
        use("loop.exit.state", "header.state", UseRole.STATE_CONTENT)),
        terminator=Terminator(TerminatorKind.BRANCH, (
            successor("body", "loop.body.state"), successor("exit", "loop.exit.state")), condition=UseID("loop.condition")))
    increment = operation("increment", (Behavior.READ, Behavior.WRITE), (
        use("increment.state", "body.state", UseRole.STATE_CONTENT),), ("incremented",),
        accesses=(StateAccess(LocationID("counter"), UseID("increment.state"), AccessMode.READ_WRITE,
                              ValueID("incremented")),), effects_complete=True)
    backedge = operation("backedge", (Behavior.CONTROL,), (use("backedge.state", "incremented", UseRole.STATE_CONTENT),),
        terminator=Terminator(TerminatorKind.JUMP, (successor("header", "backedge.state"),)))
    done = operation("loop.done", (Behavior.CONTROL,), (
        use("loop.done.value", "counter.value"), use("loop.done.state", "exit.state", UseRole.STATE_CONTENT)),
        terminator=Terminator(TerminatorKind.RETURN, exit="normal",
                              values=(UseID("loop.done.value"), UseID("loop.done.state"))))
    region = Region(RegionID("loop"), "loop-carried counter", BlockID("loop.entry"), (
        block("loop.entry", ("limit", "initial"), ("enter",)),
        block("header", ("header.state",), ("read.counter", "compare", "loop.choose")),
        block("body", ("body.state",), ("increment", "backedge")),
        block("exit", ("exit.state",), ("loop.done",)),
    ), (ExitPort("normal", ExitKind.NORMAL, (ValueType(ValueKind.DATA, "builtins.int"), state_type("counter"))),))
    return ProgramGraph(region.id, (region,), (enter, read, compare, choose, increment, backedge, done), values,
                        (StateLocation(LocationID("counter"), "loop counter", stability=Stability.INTERNAL),))


def shared_body_calls_program():
    """Two calls share a body while result/use and state transitions stay distinct."""
    values = (
        data("caller.input", "caller", argument("caller.entry", 0)),
        state("caller.initial", "caller", argument("caller.entry", 1), "calls"),
        data("call1.result", "caller", result("call1", 0)),
        state("call1.state", "caller", result("call1", 1), "calls"),
        data("call2.result", "caller", result("call2", 0)),
        state("call2.state", "caller", result("call2", 1), "calls"),
        data("body.input", "callee", argument("callee.entry", 0)),
        state("body.initial", "callee", argument("callee.entry", 1), "calls"),
        data("body.result", "callee", result("twice")),
        state("body.updated", "callee", result("count.call"), "calls"),
    )
    calls = tuple(operation(f"call{index}", (Behavior.CONTROL,), (
        use(f"call{index}.input", "caller.input"),
        use(f"call{index}.state", "caller.initial" if index == 1 else "call1.state", UseRole.STATE_CONTENT)),
        (f"call{index}.result", f"call{index}.state"), callee=RegionID("callee"),
        call_arguments=(UseID(f"call{index}.input"), UseID(f"call{index}.state"))) for index in (1, 2))
    done = operation("caller.done", (Behavior.CONTROL,), (
        use("caller.return1", "call1.result"), use("caller.return2", "call2.result"),
        use("caller.return.state", "call2.state", UseRole.STATE_CONTENT)),
        terminator=Terminator(TerminatorKind.RETURN, exit="normal",
                              values=(UseID("caller.return1"), UseID("caller.return2"), UseID("caller.return.state"))))
    twice = operation("twice", (Behavior.COMPUTE,), (
        use("twice.left", "body.input"), use("twice.right", "body.input")), ("body.result",), effects_complete=True)
    count = operation("count.call", (Behavior.READ, Behavior.WRITE), (
        use("count.state", "body.initial", UseRole.STATE_CONTENT),), ("body.updated",),
        accesses=(StateAccess(LocationID("calls"), UseID("count.state"), AccessMode.READ_WRITE,
                              ValueID("body.updated")),), effects_complete=True)
    body_done = operation("callee.done", (Behavior.CONTROL,), (
        use("callee.return", "body.result"), use("callee.return.state", "body.updated", UseRole.STATE_CONTENT)),
        terminator=Terminator(TerminatorKind.RETURN, exit="normal",
                              values=(UseID("callee.return"), UseID("callee.return.state"))))
    caller = Region(RegionID("caller"), "two independent calls", BlockID("caller.entry"), (
        block("caller.entry", ("caller.input", "caller.initial"), ("call1", "call2", "caller.done")),),
        (ExitPort("normal", ExitKind.NORMAL, (ValueType(ValueKind.DATA, "builtins.int"), ValueType(ValueKind.DATA, "builtins.int"), state_type("calls"))),))
    callee = Region(RegionID("callee"), "shared body", BlockID("callee.entry"), (
        block("callee.entry", ("body.input", "body.initial"), ("twice", "count.call", "callee.done")),),
        (ExitPort("normal", ExitKind.NORMAL, (ValueType(ValueKind.DATA, "builtins.int"), state_type("calls"))),), parent=caller.id)
    return ProgramGraph(caller.id, (caller, callee), (*calls, done, twice, count, body_done), values,
                        (StateLocation(LocationID("calls"), "call counter", stability=Stability.INTERNAL),))


def save_payload_program(label="save video"):
    """Same encode/write structure for video or tensor labels; neither library is parsed."""
    values = (
        data("payload", "save", argument("save.entry", 0), "opaque_payload"),
        state("file.before", "save", argument("save.entry", 1), "file"),
        data("encoded", "save", result("encode"), "bytes"),
        state("file.after", "save", result("file.write"), "file"),
    )
    encode = operation("encode", (Behavior.COMPUTE, Behavior.REPRESENT),
                       (use("encode.payload", "payload"),), ("encoded",), effects_complete=True)
    write = operation("file.write", (Behavior.WRITE,), (
        use("file.write.data", "encoded"), use("file.write.before", "file.before", UseRole.STATE_ORDER)),
        ("file.after",), accesses=(StateAccess(LocationID("file"), UseID("file.write.before"), AccessMode.WRITE,
                                              ValueID("file.after"), Footprint(FootprintKind.WHOLE), True),),
        effects_complete=True)
    done = operation("save.done", (Behavior.CONTROL,), (use("save.return", "file.after", UseRole.STATE_CONTENT),),
        terminator=Terminator(TerminatorKind.RETURN, exit="normal", values=(UseID("save.return"),)))
    region = Region(RegionID("save"), label, BlockID("save.entry"), (
        block("save.entry", ("payload", "file.before"), ("encode", "file.write", "save.done")),),
        (ExitPort("normal", ExitKind.NORMAL, (state_type("file"),)),))
    return ProgramGraph(region.id, (region,), (replace(encode, label=f"{label}: encode"), write, done), values,
                        (StateLocation(LocationID("file"), "output file", stability=Stability.EXTERNAL),))
