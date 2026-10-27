"""D2.4 composition over an actual C1/C2B body and its finite D1 frontier."""
from scar.ir.program.ids import OperationID
from scar.ir.program.lifecycle import SessionPost
from tests.fixtures.program_publication_graphs import publication_program
from tests.fixtures.program_resumption_graphs import resumption_cleanup_invoke_program
from tests.fixtures.program_session_release_graphs import _Tail


def body_cleanup_lifecycle_program(*, binding="AFTER_OPERATION", target="value",
                                   release=True, callback=False):
    graph = publication_program(target=target, async_request=True,
                                body_graph=resumption_cleanup_invoke_program())
    for number, commit in enumerate(graph.body_outcome_commits):
        tail = _Tail(graph, commit.operation)
        owner = tail.body
        if binding == "AFTER_OPERATION":
            tail.metadata(SessionPost.COMPLETE, f"body.session.{number}")
        elif binding == "NORMAL_COMPLETION":
            tail.invoke(f"body.helper.{number}", SessionPost.COMPLETE)
        else:
            raise ValueError("unsupported fixture binding")
        if callback:
            tail.invoke(f"body.callback.{number}")
        if release:
            tail.release(number)
        graph = tail.finish()
        if release and binding == "NORMAL_COMPLETION":
            # The helper's actual RAISE has its own partial state and retains F.
            failure = _Tail(graph, OperationID(f"body.helper.{number}.raise.exit"), body=owner)
            failure.release(100 + number)
            graph = failure.finish()
    return graph
